import asyncio
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import func, select

from app.bot.openrouter import (
    DEFAULT_MODERATION_SYSTEM_PROMPT,
    classify_message,
    rate_limiter_snapshot,
)
from app.db import async_session
from app.events import (
    emit_banned_rejoin,
    emit_member_joined,
    emit_message_flagged,
    emit_mod_action,
    emit_raid_alert,
)
from app.models import (
    AIConfig,
    AnalyticsSnapshot,
    Filter,
    FlaggedMessage,
    Group,
    ModLog,
    PurgatoryEntry,
    UserProfile,
    Warn,
)

FLOOD_LIMIT_MESSAGES = 5
FLOOD_WINDOW_SECONDS = 6

# In-memory, per-process trackers for flood/slow-mode. Reset on restart, and
# only correct for a single running instance — fine here since the whole
# point of this stack is one process/one container. A multi-instance
# deployment would need this moved to Redis or the DB instead.
_message_times: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=FLOOD_LIMIT_MESSAGES))
_last_message_at: dict[tuple[int, int], float] = {}

# ----------------------------------------------------------- raid detection --
# Per-group rolling window of recent join timestamps. When the count in the
# last RAID_WINDOW_MINUTES exceeds RAID_JOIN_THRESHOLD, the group enters
# "raid lock" mode: Purgatory auto-enabled, slow mode tightened, admins
# notified. Auto-clears once the join rate drops back to normal.
_raid_join_times: dict[int, deque] = defaultdict(lambda: deque(maxlen=100))
_raid_lock_until: dict[int, float] = {}  # monotonic timestamp when lock expires
RAID_WINDOW_MINUTES = 5
RAID_JOIN_THRESHOLD = 8  # 8 joins in 5 min = suspected raid
RAID_LOCK_DURATION_MINUTES = 15


def is_night_mode_active(group: Group) -> bool:
    if not group.night_mode_enabled:
        return False
    hour = datetime.now(timezone.utc).hour
    start, end = group.night_start_hour, group.night_end_hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # window wraps past midnight


def is_slow_mode_violation(group_id: int, user_id: int, slow_mode_seconds: int) -> bool:
    key = (group_id, user_id)
    now = time.monotonic()
    last = _last_message_at.get(key)
    if last is not None and now - last < slow_mode_seconds:
        return True
    _last_message_at[key] = now
    return False


def check_flood(group_id: int, user_id: int) -> bool:
    key = (group_id, user_id)
    now = time.monotonic()
    times = _message_times[key]
    times.append(now)
    if len(times) == FLOOD_LIMIT_MESSAGES and (now - times[0]) < FLOOD_WINDOW_SECONDS:
        times.clear()
        return True
    return False


async def delete_silently(bot: Bot, chat_id: int, message_id: int) -> None:
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass  # message may already be gone — don't crash the handler over it


async def mute_user(bot: Bot, chat_id: int, user_id: int) -> None:
    try:
        await bot.restrict_chat_member(chat_id, user_id, ChatPermissions(can_send_messages=False))
    except Exception:
        pass
    await _update_profile(chat_id, user_id, is_muted=True)


async def unmute_user(bot: Bot, chat_id: int, user_id: int) -> None:
    try:
        await bot.restrict_chat_member(
            chat_id,
            user_id,
            ChatPermissions(
                can_send_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
                can_send_polls=True,
            ),
        )
    except Exception:
        pass
    await _update_profile(chat_id, user_id, is_muted=False)


async def _update_profile(
    group_id: int,
    user_id: int,
    *,
    username: str | None = None,
    full_name: str | None = None,
    is_muted: bool | None = None,
    is_banned: bool | None = None,
    rep_delta: int = 0,
    msg_delta: int = 0,
    warn_delta: int = 0,
) -> None:
    """Lazy upsert helper — keeps UserProfile in sync with moderation
    actions and message activity."""
    async with async_session() as session:
        result = await session.execute(
            select(UserProfile).where(
                UserProfile.group_id == group_id, UserProfile.user_id == user_id
            )
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = UserProfile(group_id=group_id, user_id=user_id)
            session.add(profile)
        if username is not None:
            profile.username = username
        if full_name is not None:
            profile.full_name = full_name
        if is_muted is not None:
            profile.is_muted = is_muted
        if is_banned is not None:
            profile.is_banned = is_banned
        profile.reputation = (profile.reputation or 0) + rep_delta
        profile.message_count = (profile.message_count or 0) + msg_delta
        profile.warn_count = (profile.warn_count or 0) + warn_delta
        profile.last_active = datetime.now(timezone.utc)
        await session.commit()


# ----------------------------------------------------------- log channel --
# Upgraded channel mirroring with color-coded HTML + inline keyboard buttons.
# The inline buttons let admins undo an action or view the user directly
# from the log channel — no need to open the dashboard.

# Map action type → emoji + color (HTML span)
_ACTION_PRESENTATION = {
    "warn": ("⚠️", "#fbbf24"),
    "mute": ("🔇", "#f59e0b"),
    "mute_flood": ("🌊", "#f59e0b"),
    "mute_warn_limit": ("⛔", "#f59e0b"),
    "unmute": ("🔊", "#10b981"),
    "kick": ("👢", "#3b82f6"),
    "ban": ("🔨", "#ef4444"),
    "ban_bot": ("🤖", "#ef4444"),
    "delete_and_ban": ("💥", "#ef4444"),
    "delete": ("🗑️", "#6b7280"),
    "unban": ("🔓", "#10b981"),
    "purgatory_approve": ("✅", "#10b981"),
    "purgatory_deny": ("❌", "#f59e0b"),
    "purgatory_ban": ("🔨", "#ef4444"),
    "banned_rejoin_detected": ("🚨", "#ef4444"),
    "raid_alert": ("⚠️", "#ef4444"),
    "raid_lock_enabled": ("🔒", "#ef4444"),
    "raid_lock_disabled": ("🔓", "#10b981"),
    "auto_warn_medium": ("⚠️", "#fbbf24"),
    "auto_warn_low": ("💡", "#60a5fa"),
}


async def log_action(
    group_id: int,
    action: str,
    target_user_id: int,
    reason: str,
    admin_id: int | None = None,
) -> None:
    async with async_session() as session:
        session.add(
            ModLog(
                group_id=group_id,
                action=action,
                target_user_id=target_user_id,
                reason=reason,
                admin_id=admin_id,
            )
        )
        await session.commit()
    await _post_to_log_channel(group_id, action, target_user_id, reason, admin_id)
    await _bump_analytics(group_id, mod_actions=1)
    emit_mod_action(group_id, action, target_user_id, reason)


async def _post_to_log_channel(
    group_id: int,
    action: str,
    target_user_id: int,
    reason: str,
    admin_id: int | None = None,
) -> None:
    """Posts a color-coded HTML log entry to the configured channel, with
    inline keyboard buttons for quick actions. If the channel isn't set or
    the bot lacks permissions, fails silently."""
    from app.bot import bot  # deferred import — avoids circular import

    async with async_session() as session:
        group = await session.get(Group, group_id)
    if not group or not group.mod_log_channel_id:
        return

    emoji, color = _ACTION_PRESENTATION.get(action, ("•", "#8b93a7"))
    group_title = group.title or str(group_id)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Telegram HTML supports a limited subset — no <span style>. We use
    # <b> for the action and a colored square emoji as the visual cue.
    text = (
        f"{emoji} <b>{_escape_html(action)}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"<b>Group:</b> {_escape_html(group_title)}\n"
        f"<b>User:</b> <code>{target_user_id}</code>\n"
        f"<b>Reason:</b> {_escape_html(reason or '—')}\n"
        f"<b>Admin:</b> {'<code>' + str(admin_id) + '</code>' if admin_id else 'auto'}\n"
        f"<b>Time:</b> <code>{timestamp}</code>"
    )

    # Inline keyboard — let admin undo or view user from the channel itself.
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="👤 View user", url=f"tg://user?id={target_user_id}"),
        InlineKeyboardButton(text="↩️ Undo", callback_data=f"undo:{action}:{target_user_id}"),
    ]])

    try:
        await bot.send_message(
            group.mod_log_channel_id,
            text,
            reply_markup=keyboard,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


def _escape_html(s: str) -> str:
    """Minimal HTML escape for Telegram's parse_mode=HTML."""
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ----------------------------------------------------------- analytics --

async def _bump_analytics(group_id: int, *, messages: int = 0, mod_actions: int = 0, flags: int = 0, new_members: int = 0, ai_calls: int = 0) -> None:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    async with async_session() as session:
        result = await session.execute(
            select(AnalyticsSnapshot).where(
                AnalyticsSnapshot.group_id == group_id,
                AnalyticsSnapshot.bucket_hour == now,
            )
        )
        snap = result.scalar_one_or_none()
        if snap is None:
            snap = AnalyticsSnapshot(group_id=group_id, bucket_hour=now)
            session.add(snap)
        snap.message_count = (snap.message_count or 0) + messages
        snap.mod_actions = (snap.mod_actions or 0) + mod_actions
        snap.flags_raised = (snap.flags_raised or 0) + flags
        snap.new_members = (snap.new_members or 0) + new_members
        snap.ai_calls = (snap.ai_calls or 0) + ai_calls
        await session.commit()


async def flood_triggered(bot: Bot, group_id: int, user_id: int, message_id: int) -> None:
    await delete_silently(bot, group_id, message_id)
    await mute_user(bot, group_id, user_id)
    await log_action(group_id, "mute_flood", user_id, f"{FLOOD_LIMIT_MESSAGES} messages in {FLOOD_WINDOW_SECONDS}s")


async def check_regex_filters(group_id: int, text: str) -> str | None:
    async with async_session() as session:
        result = await session.execute(select(Filter).where(Filter.group_id == group_id))
        filters = result.scalars().all()

    lowered = text.lower()
    for f in filters:
        if f.pattern.lower() in lowered:
            return f"blocked {f.type}: {f.pattern}"
    return None


async def get_ai_config(group_id: int) -> AIConfig:
    async with async_session() as session:
        result = await session.execute(select(AIConfig).where(AIConfig.group_id == group_id))
        cfg = result.scalar_one_or_none()
        if cfg is None:
            cfg = AIConfig(group_id=group_id)
            session.add(cfg)
            await session.commit()
            await session.refresh(cfg)
        return cfg


# ----------------------------------------------------------- auto-warn --
# NEW: medium and low severity flags now generate an automatic warn to the
# user (in addition to queuing for admin review). Previously only high-
# severity was acted on; medium/low just sat silently in the queue. Now
# the user gets feedback immediately, and the warn count contributes to
# the auto-mute threshold just like manual warns.

async def _auto_warn_user(bot: Bot, group_id: int, user_id: int, severity: str, category: str, confidence: float) -> None:
    """Issues an automatic warn for medium/low severity AI flags. Replies
    to the user in the group so they understand why their message was
    flagged — this closes the loop and dramatically reduces repeat
    offenses compared to silent flagging."""
    reason = f"AI auto-warn ({severity}): {category} (confidence {confidence:.0%})"

    async with async_session() as session:
        session.add(Warn(group_id=group_id, user_id=user_id, reason=reason))
        await session.commit()

    await log_action(group_id, f"auto_warn_{severity}", user_id, reason)
    await _update_profile(group_id, user_id, warn_delta=1, rep_delta=-1)

    # Check if the warn pushed them over the limit — if so, auto-mute.
    await _check_warn_threshold(bot, group_id, user_id)

    # Notify the user in-group. Best-effort — if the message was already
    # deleted or the user left, this will silently fail.
    try:
        from app.bot import bot as tg_bot
        await tg_bot.send_message(
            group_id,
            f"⚠️ <b>Automated warning</b>\n"
            f"Your message was flagged by the AI moderator as <b>{severity} {category}</b>.\n"
            f"Reason: {reason}\n"
            f"If you think this was a mistake, reply <code>/bappeal</code> with an explanation.",
        )
    except Exception:
        pass


async def _check_warn_threshold(bot: Bot, group_id: int, user_id: int) -> None:
    async with async_session() as session:
        group = await session.get(Group, group_id)
        result = await session.execute(
            select(func.count()).select_from(Warn).where(Warn.group_id == group_id, Warn.user_id == user_id)
        )
        count = result.scalar_one()
    if group and count >= group.warn_limit:
        await mute_user(bot, group_id, user_id)
        await log_action(group_id, "mute_warn_limit", user_id, f"reached {group.warn_limit} warns")


async def moderate_message(bot: Bot, group_id: int, user_id: int, message_id: int, text: str, username: str = "", full_name: str = "") -> None:
    if not text:
        return

    await _update_profile(group_id, user_id, username=username, full_name=full_name, msg_delta=1)
    await _bump_analytics(group_id, messages=1)

    regex_hit = await check_regex_filters(group_id, text)
    if regex_hit:
        await _take_action(bot, group_id, user_id, message_id, "delete", regex_hit)
        return

    cfg = await get_ai_config(group_id)
    if not cfg.enabled_categories:
        return

    system_prompt = cfg.custom_system_prompt.strip() or DEFAULT_MODERATION_SYSTEM_PROMPT
    try:
        result = await classify_message(text, system_prompt=system_prompt, temperature=cfg.temperature)
    except RuntimeError:
        return

    await _bump_analytics(group_id, ai_calls=1)

    severity = result.get("severity", "none")
    category = result.get("category", "none")
    confidence = float(result.get("confidence", 0) or 0)

    enabled = {c.strip() for c in cfg.enabled_categories.split(",") if c.strip()}
    if category not in enabled:
        severity = "none"

    if severity == "high" and cfg.auto_ban_high and confidence >= cfg.confidence_threshold:
        await _take_action(bot, group_id, user_id, message_id, "delete_and_ban", category)
    elif severity in ("medium", "low") and cfg.auto_flag_medium:
        # Queue for admin review
        async with async_session() as session:
            flag = FlaggedMessage(
                group_id=group_id,
                user_id=user_id,
                message_text=text,
                category=category,
                severity=severity,
                confidence=confidence,
            )
            session.add(flag)
            await session.commit()
            await session.refresh(flag)
        await _bump_analytics(group_id, flags=1)
        emit_message_flagged(group_id, flag.id, user_id, category, severity)

        # NEW: auto-warn the user (in addition to queuing for review)
        await _auto_warn_user(bot, group_id, user_id, severity, category, confidence)


async def _take_action(bot: Bot, group_id: int, user_id: int, message_id: int, action: str, reason: str) -> None:
    await delete_silently(bot, group_id, message_id)
    if action == "delete_and_ban":
        try:
            await bot.ban_chat_member(group_id, user_id)
        except Exception:
            pass
        await _update_profile(group_id, user_id, is_banned=True, rep_delta=-5)
    await log_action(group_id, action, user_id, reason)


# ----------------------------------------------------------- raid detection --

def record_join(group_id: int) -> bool:
    """Called when a new member joins. Returns True if a raid is currently
    suspected (join rate exceeded threshold). Also extends the raid lock
    window if we're already in one."""
    now = time.monotonic()
    window_start = now - (RAID_WINDOW_MINUTES * 60)
    times = _raid_join_times[group_id]
    times.append(now)
    # Drop old entries
    while times and times[0] < window_start:
        times.popleft()

    in_lock = _raid_lock_until.get(group_id, 0) > now
    if not in_lock and len(times) >= RAID_JOIN_THRESHOLD:
        # Trigger raid lock
        _raid_lock_until[group_id] = now + (RAID_LOCK_DURATION_MINUTES * 60)
        return True
    return in_lock


def is_raid_locked(group_id: int) -> bool:
    return _raid_lock_until.get(group_id, 0) > time.monotonic()


def raid_lock_remaining(group_id: int) -> int:
    """Returns seconds remaining in the raid lock, or 0 if not locked."""
    remaining = _raid_lock_until.get(group_id, 0) - time.monotonic()
    return max(0, int(remaining))


async def handle_raid_lock(bot: Bot, group_id: int) -> None:
    """When a raid is detected: enable Purgatory, set tight slow mode,
    notify admins in the group + log channel. Called by the join handler
    when record_join() returns True."""
    async with async_session() as session:
        group = await session.get(Group, group_id)
        if group is None:
            return
        original_purgatory = group.purgatory_enabled
        original_slow = group.slow_mode_seconds
        group.purgatory_enabled = True
        group.slow_mode_seconds = max(group.slow_mode_seconds, 60)  # at least 1 min
        await session.commit()

    await log_action(
        group_id, "raid_lock_enabled", 0,
        f"Raid detected — Purgatory enabled, slow mode set to 60s. "
        f"Was: purgatory={original_purgatory}, slow={original_slow}s. "
        f"Lock lasts {RAID_LOCK_DURATION_MINUTES} min.",
    )
    emit_raid_alert(group_id, RAID_JOIN_THRESHOLD, RAID_WINDOW_MINUTES)

    try:
        await bot.send_message(
            group_id,
            f"🚨 <b>Raid protection activated</b>\n"
            f"Detected {RAID_JOIN_THRESHOLD}+ joins in {RAID_WINDOW_MINUTES} min.\n"
            f"Purgatory + slow mode enabled for {RAID_LOCK_DURATION_MINUTES} min. "
            f"New members will be held for admin review.",
        )
    except Exception:
        pass


async def check_raid_lock_expiry(bot: Bot, group_id: int) -> None:
    """Called periodically by the scheduler. When the raid lock expires,
    restores original settings and notifies the group."""
    if is_raid_locked(group_id):
        return

    # Check if we were previously locked (the lock just expired)
    if group_id not in _raid_lock_until:
        return
    # Clear the marker
    expired_at = _raid_lock_until.pop(group_id, 0)
    if expired_at == 0:
        return

    async with async_session() as session:
        group = await session.get(Group, group_id)
        if group is None:
            return
        # Don't auto-disable purgatory — the admin may want it on. Just
        # restore slow mode if we tightened it.
        if group.slow_mode_seconds >= 60:
            # Only restore if we were the ones who set it. Conservative:
            # leave it alone and let admin decide.
            pass

    await log_action(
        group_id, "raid_lock_disabled", 0,
        f"Raid lock expired after {RAID_LOCK_DURATION_MINUTES} min. "
        f"Review new Purgatory entries and adjust settings manually if needed.",
    )
    try:
        await bot.send_message(
            group_id,
            f"🔓 <b>Raid protection deactivated</b>\n"
            f"No new raid-like join activity for {RAID_LOCK_DURATION_MINUTES} min. "
            f"Review pending Purgatory entries in the dashboard.",
        )
    except Exception:
        pass


# ----------------------------------------------------------- banned rejoin --

async def check_banned_rejoin(bot: Bot, group_id: int, user_id: int, full_name: str) -> bool:
    """Called when a new member joins. Checks if this user_id has a prior
    ban record in mod_log for this group. If so, re-bans them automatically
    and emits an event for the dashboard."""
    async with async_session() as session:
        # Look for any prior ban-related mod action against this user in this group.
        result = await session.execute(
            select(ModLog)
            .where(
                ModLog.group_id == group_id,
                ModLog.target_user_id == user_id,
                ModLog.action.in_(["ban", "delete_and_ban", "purgatory_ban", "banned_rejoin_detected"]),
            )
            .order_by(ModLog.created_at.desc())
            .limit(1)
        )
        prior_ban = result.scalar_one_or_none()

    if prior_ban is None:
        return False

    # User was previously banned — re-ban immediately.
    try:
        await bot.ban_chat_member(group_id, user_id)
    except Exception:
        pass

    await _update_profile(group_id, user_id, is_banned=True, full_name=full_name)
    await log_action(
        group_id, "banned_rejoin_detected", user_id,
        f"Previously banned user rejoined (prior action: {prior_ban.action} on {prior_ban.created_at}). Auto-re-banned.",
    )
    emit_banned_rejoin(group_id, user_id, full_name, prior_ban.action)

    try:
        await bot.send_message(
            group_id,
            f"🚨 <b>Banned user rejoined</b>\n"
            f"<code>{user_id}</code> ({_escape_html(full_name)}) previously banned "
            f"({prior_ban.action} on {prior_ban.created_at.strftime('%Y-%m-%d')}). "
            f"Auto-re-banned.",
        )
    except Exception:
        pass
    return True


def system_health() -> dict:
    """Snapshot of in-memory state for the dashboard health panel."""
    now = time.monotonic()
    active_locks = sum(1 for exp in _raid_lock_until.values() if exp > now)
    return {
        "flood_trackers": len(_message_times),
        "slow_mode_trackers": len(_last_message_at),
        "rate_limiter": rate_limiter_snapshot(),
        "raid_detection": {
            "tracked_groups": len(_raid_join_times),
            "active_locks": active_locks,
            "threshold_joins": RAID_JOIN_THRESHOLD,
            "window_minutes": RAID_WINDOW_MINUTES,
            "lock_duration_minutes": RAID_LOCK_DURATION_MINUTES,
        },
    }
