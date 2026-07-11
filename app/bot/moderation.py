import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import ChatPermissions
from sqlalchemy import select

from app.bot.openrouter import (
    DEFAULT_MODERATION_SYSTEM_PROMPT,
    classify_message,
    rate_limiter_snapshot,
)
from app.db import async_session
from app.models import AIConfig, AnalyticsSnapshot, Filter, FlaggedMessage, Group, ModLog, UserProfile

FLOOD_LIMIT_MESSAGES = 5
FLOOD_WINDOW_SECONDS = 6

# In-memory, per-process trackers for flood/slow-mode. Reset on restart, and
# only correct for a single running instance — fine here since the whole
# point of this stack is one process/one container. A multi-instance
# deployment would need this moved to Redis or the DB instead.
_message_times: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=FLOOD_LIMIT_MESSAGES))
_last_message_at: dict[tuple[int, int], float] = {}


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
    await _post_to_log_channel(group_id, action, target_user_id, reason)
    await _bump_analytics(group_id, mod_actions=1)


async def _post_to_log_channel(group_id: int, action: str, target_user_id: int, reason: str) -> None:
    from app.bot import bot  # deferred import — avoids a circular import at module load time

    async with async_session() as session:
        group = await session.get(Group, group_id)
    if not group or not group.mod_log_channel_id:
        return
    try:
        await bot.send_message(
            group.mod_log_channel_id,
            f"<b>{action}</b> — user {target_user_id} in {group.title or group_id}\n{reason}",
        )
    except Exception:
        pass


async def _bump_analytics(group_id: int, *, messages: int = 0, mod_actions: int = 0, flags: int = 0, new_members: int = 0, ai_calls: int = 0) -> None:
    """Rolls the activity into the current hour's analytics snapshot row.
    Creates one if it doesn't exist yet — upsert pattern via SELECT+UPDATE."""
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
    """Cheap first pass using the group's word/link blocklist. Keeping this
    before the AI call matters a lot given free OpenRouter rate limits —
    obvious spam never needs to touch the AI call."""
    async with async_session() as session:
        result = await session.execute(select(Filter).where(Filter.group_id == group_id))
        filters = result.scalars().all()

    lowered = text.lower()
    for f in filters:
        if f.pattern.lower() in lowered:
            return f"blocked {f.type}: {f.pattern}"
    return None


async def get_ai_config(group_id: int) -> AIConfig:
    """Returns the per-group AI configuration row, creating a default one
    on first access so the dashboard always has something to display."""
    async with async_session() as session:
        result = await session.execute(select(AIConfig).where(AIConfig.group_id == group_id))
        cfg = result.scalar_one_or_none()
        if cfg is None:
            cfg = AIConfig(group_id=group_id)
            session.add(cfg)
            await session.commit()
            await session.refresh(cfg)
        return cfg


async def moderate_message(bot: Bot, group_id: int, user_id: int, message_id: int, text: str, username: str = "", full_name: str = "") -> None:
    if not text:
        return

    # Bump message counter + last_active for this user's profile.
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
        # All free models were unavailable for this call — don't block the
        # chat on it, just skip AI moderation for this one message.
        return

    await _bump_analytics(group_id, ai_calls=1)

    severity = result.get("severity", "none")
    category = result.get("category", "none")
    confidence = float(result.get("confidence", 0) or 0)

    # Only act on categories the admin has explicitly enabled.
    enabled = {c.strip() for c in cfg.enabled_categories.split(",") if c.strip()}
    if category not in enabled:
        severity = "none"

    if severity == "high" and cfg.auto_ban_high and confidence >= cfg.confidence_threshold:
        await _take_action(bot, group_id, user_id, message_id, "delete_and_ban", category)
    elif severity in ("medium", "low") and cfg.auto_flag_medium:
        async with async_session() as session:
            session.add(
                FlaggedMessage(
                    group_id=group_id,
                    user_id=user_id,
                    message_text=text,
                    category=category,
                    severity=severity,
                    confidence=confidence,
                )
            )
            await session.commit()
        await _bump_analytics(group_id, flags=1)


async def _take_action(bot: Bot, group_id: int, user_id: int, message_id: int, action: str, reason: str) -> None:
    await delete_silently(bot, group_id, message_id)
    if action == "delete_and_ban":
        try:
            await bot.ban_chat_member(group_id, user_id)
        except Exception:
            pass
        await _update_profile(group_id, user_id, is_banned=True, rep_delta=-5)
    await log_action(group_id, action, user_id, reason)


def system_health() -> dict:
    """Snapshot of in-memory state for the dashboard health panel."""
    return {
        "flood_trackers": len(_message_times),
        "slow_mode_trackers": len(_last_message_at),
        "rate_limiter": rate_limiter_snapshot(),
    }
