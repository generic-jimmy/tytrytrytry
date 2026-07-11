import re
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import ChatPermissions, User

from app.config import settings
from app.db import async_session
from app.models import ModLog, PurgatoryEntry

SUSPICIOUS_NAME_RE = re.compile(r".*\d{4,}$")


def allowed_bot_usernames() -> set[str]:
    names = {n.strip().lower() for n in settings.allowed_bot_usernames.split(",") if n.strip()}
    names.add(settings.telegram_bot_username.lower())
    return names


async def handle_new_bot(bot: Bot, group_id: int, user: User) -> bool:
    """Called whenever a bot joins (or is found already present via
    /bcleanbots). Returns True if it was allowed to stay, False if banned."""
    username = (user.username or "").lower()
    if username in allowed_bot_usernames():
        return True

    try:
        await bot.ban_chat_member(group_id, user.id)
    except Exception:
        pass

    async with async_session() as session:
        session.add(
            ModLog(
                group_id=group_id,
                action="ban_bot",
                target_user_id=user.id,
                reason=f"unauthorized bot @{user.username or user.id}",
            )
        )
        await session.commit()
    return False


async def _looks_suspicious(bot: Bot, user: User) -> bool:
    """Lightweight heuristics — no username with a name that's mostly
    digits, or no username and no profile photo at all. Not a strong
    signal on its own, just enough to sort a member into a separate review
    tab instead of the main pending queue."""
    if not user.username and SUSPICIOUS_NAME_RE.match(user.full_name or ""):
        return True
    if not user.username:
        try:
            photos = await bot.get_user_profile_photos(user.id, limit=1)
            if photos.total_count == 0:
                return True
        except Exception:
            pass
    return False


async def admit_to_purgatory(bot: Bot, group_id: int, user: User) -> PurgatoryEntry:
    """Mutes the new member and creates a review-queue row for them."""
    try:
        await bot.restrict_chat_member(group_id, user.id, ChatPermissions(can_send_messages=False))
    except Exception:
        pass

    suspicious = await _looks_suspicious(bot, user)
    entry = PurgatoryEntry(
        group_id=group_id,
        user_id=user.id,
        username=user.username or "",
        full_name=user.full_name or "",
        language_code=user.language_code or "",
        is_premium=bool(getattr(user, "is_premium", False)),
        status="suspicious" if suspicious else "pending",
    )
    async with async_session() as session:
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
    return entry


async def resolve_purgatory_entry(bot: Bot, entry: PurgatoryEntry, decision: str, decided_by: int) -> None:
    """decision: "approve" (unmute), "deny" (kick, can rejoin later),
    "ban" (permanent)."""
    if decision == "approve":
        try:
            await bot.restrict_chat_member(
                entry.group_id,
                entry.user_id,
                ChatPermissions(
                    can_send_messages=True,
                    can_send_other_messages=True,
                    can_add_web_page_previews=True,
                    can_send_polls=True,
                ),
            )
        except Exception:
            pass
        new_status, action = "approved", "purgatory_approve"
    elif decision == "deny":
        try:
            await bot.ban_chat_member(entry.group_id, entry.user_id)
            await bot.unban_chat_member(entry.group_id, entry.user_id)  # kick, not permanent
        except Exception:
            pass
        new_status, action = "denied", "purgatory_deny"
    elif decision == "ban":
        try:
            await bot.ban_chat_member(entry.group_id, entry.user_id)
        except Exception:
            pass
        new_status, action = "banned", "purgatory_ban"
    else:
        return

    async with async_session() as session:
        db_entry = await session.get(PurgatoryEntry, entry.id)
        if db_entry:
            db_entry.status = new_status
            db_entry.decided_by = decided_by
            db_entry.decided_at = datetime.now(timezone.utc)
        session.add(ModLog(group_id=entry.group_id, action=action, target_user_id=entry.user_id, reason=""))
        await session.commit()
