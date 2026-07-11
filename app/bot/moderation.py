import time
from collections import defaultdict, deque
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import ChatPermissions
from sqlalchemy import select

from app.bot.openrouter import classify_message
from app.db import async_session
from app.models import Filter, FlaggedMessage, Group, ModLog

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


async def log_action(group_id: int, action: str, target_user_id: int, reason: str) -> None:
    async with async_session() as session:
        session.add(ModLog(group_id=group_id, action=action, target_user_id=target_user_id, reason=reason))
        await session.commit()
    await _post_to_log_channel(group_id, action, target_user_id, reason)


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


async def moderate_message(bot: Bot, group_id: int, user_id: int, message_id: int, text: str) -> None:
    if not text:
        return

    regex_hit = await check_regex_filters(group_id, text)
    if regex_hit:
        await _take_action(bot, group_id, user_id, message_id, "delete", regex_hit)
        return

    try:
        result = await classify_message(text)
    except RuntimeError:
        # All free models were unavailable for this call — don't block the
        # chat on it, just skip AI moderation for this one message.
        return

    severity = result.get("severity", "none")
    category = result.get("category", "none")
    confidence = float(result.get("confidence", 0) or 0)

    if severity == "high":
        await _take_action(bot, group_id, user_id, message_id, "delete_and_ban", category)
    elif severity in ("medium", "low"):
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


async def _take_action(bot: Bot, group_id: int, user_id: int, message_id: int, action: str, reason: str) -> None:
    await delete_silently(bot, group_id, message_id)
    if action == "delete_and_ban":
        try:
            await bot.ban_chat_member(group_id, user_id)
        except Exception:
            pass
    await log_action(group_id, action, user_id, reason)
