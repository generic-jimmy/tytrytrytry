import json

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import ChatMemberUpdated, Message
from sqlalchemy import func, select

from app.bot.moderation import (
    check_flood,
    flood_triggered,
    is_night_mode_active,
    is_slow_mode_violation,
    log_action,
    moderate_message,
    mute_user,
    unmute_user,
)
from app.bot.openrouter import admin_tool, interpret_admin_instruction
from app.bot.purgatory import admit_to_purgatory, allowed_bot_usernames, handle_new_bot
from app.db import async_session
from app.models import Filter, Group, Warn

router = Router()

# NOTE ON COMMAND NAMES: every admin/moderation command below is prefixed
# with "b" (e.g. /bwarn, /bmute) specifically so they don't collide with
# Rose's commands (/warn, /mute, ...) if both bots are in the same group.
# /start is left unprefixed since that's a Telegram-wide convention every
# bot is expected to answer to.


# ---------------------------------------------------------------- helpers --

async def ensure_group(group_id: int, title: str) -> None:
    async with async_session() as session:
        existing = await session.get(Group, group_id)
        if existing is None:
            session.add(Group(id=group_id, title=title))
            await session.commit()


async def sync_admin(group_id: int, user_id: int) -> None:
    """Called whenever we confirm someone is a real Telegram admin of the
    group — this is what grants them web dashboard login access for that
    group, so it stays in sync automatically without a manual setup step."""
    from app.models import Admin

    async with async_session() as session:
        result = await session.execute(
            select(Admin).where(Admin.group_id == group_id, Admin.telegram_user_id == user_id)
        )
        if result.scalar_one_or_none() is None:
            session.add(Admin(group_id=group_id, telegram_user_id=user_id))
            await session.commit()


async def is_telegram_admin(bot: Bot, group_id: int, user_id: int) -> bool:
    member = await bot.get_chat_member(group_id, user_id)
    return member.status in ("administrator", "creator")


async def require_admin(bot: Bot, message: Message, silent: bool = False) -> bool:
    if not message.from_user:
        return False
    if not await is_telegram_admin(bot, message.chat.id, message.from_user.id):
        if not silent:
            await message.reply("Admins only.")
        return False
    await sync_admin(message.chat.id, message.from_user.id)
    return True


async def _apply_action(bot: Bot, group_id: int, user_id: int, action: str, reason: str) -> None:
    if action == "warn":
        async with async_session() as session:
            session.add(Warn(group_id=group_id, user_id=user_id, reason=reason))
            await session.commit()
        await log_action(group_id, "warn", user_id, reason)
        await _check_warn_threshold(bot, group_id, user_id)
    elif action == "mute":
        await mute_user(bot, group_id, user_id)
        await log_action(group_id, "mute", user_id, reason)
    elif action == "kick":
        try:
            await bot.ban_chat_member(group_id, user_id)
            await bot.unban_chat_member(group_id, user_id)
        except Exception:
            pass
        await log_action(group_id, "kick", user_id, reason)
    elif action == "ban":
        try:
            await bot.ban_chat_member(group_id, user_id)
        except Exception:
            pass
        await log_action(group_id, "ban", user_id, reason)


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


# ------------------------------------------------------------- lifecycle --

@router.message(Command("start"))
async def start_cmd(message: Message) -> None:
    await message.answer(
        "I'm running. Add me to a group and make me an admin to start moderating. "
        "Send /bhelp in the group for the full command list. Group admins get web "
        "dashboard access automatically the first time they use an admin command."
    )


@router.message(Command("bhelp"))
async def bhelp_cmd(message: Message) -> None:
    await message.reply(
        "Commands (admin-only unless noted):\n"
        "/bwarn /bmute /bkick /bban /bunmute — reply to a message\n"
        "/bunban <user_id>\n"
        "/bwarnlimit <n> — auto-mute after n warns\n"
        "/baddfilter word|link <pattern>, /bremovefilter <pattern>, /bfilters\n"
        "/brules (anyone), /bsetrules <text>\n"
        "/bnightmode on|off [start end], /bslowmode <seconds>\n"
        "/bpurgatory on|off — hold new members for approval\n"
        "/bcleanbots — sweep admin list for unauthorized bots\n"
        "/bsetlogchannel <channel_id>\n"
        "/bsetwelcome <text>  or  /bsetwelcome ai <prompt>\n"
        "/bsummarize — reply to a message to summarize it\n"
        "/bai <instruction> — reply to a message, e.g. /bai mute for spam"
    )


@router.my_chat_member()
async def on_bot_added(event: ChatMemberUpdated) -> None:
    if event.new_chat_member.status in ("member", "administrator"):
        await ensure_group(event.chat.id, event.chat.title or "")


@router.message(F.new_chat_members)
async def welcome_new_members(message: Message, bot: Bot) -> None:
    async with async_session() as session:
        group = await session.get(Group, message.chat.id)

    for member in message.new_chat_members:
        if member.id == bot.id:
            continue  # the bot itself joining — handled by on_bot_added

        if member.is_bot:
            allowed = await handle_new_bot(bot, message.chat.id, member)
            if not allowed:
                await message.answer(f"Blocked unauthorized bot @{member.username or member.id}.")
            continue

        if group and group.purgatory_enabled:
            await admit_to_purgatory(bot, message.chat.id, member)
            await message.answer(
                f"{member.full_name} has joined and is muted pending admin approval. "
                f"Admins: review in the dashboard's Purgatory tab."
            )
        else:
            text = group.welcome_message if group else "Welcome!"
            await message.answer(f"{text}\n\nWelcome, {member.full_name}!")


# ---------------------------------------------------------- moderation --

@router.message(Command("bwarn"))
async def bwarn_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    if not message.reply_to_message:
        await message.reply("Reply to the message you want to warn the user for.")
        return
    target = message.reply_to_message.from_user
    reason = message.text.partition(" ")[2].strip() or "manual warn"
    await _apply_action(bot, message.chat.id, target.id, "warn", reason)
    await message.reply(f"Warned {target.full_name}.")


@router.message(Command("bmute"))
async def bmute_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    if not message.reply_to_message:
        await message.reply("Reply to the message from the user you want to mute.")
        return
    target = message.reply_to_message.from_user
    reason = message.text.partition(" ")[2].strip() or "manual mute"
    await _apply_action(bot, message.chat.id, target.id, "mute", reason)
    await message.reply(f"Muted {target.full_name}.")


@router.message(Command("bunmute"))
async def bunmute_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    if not message.reply_to_message:
        await message.reply("Reply to the user's message to unmute them.")
        return
    target = message.reply_to_message.from_user
    await unmute_user(bot, message.chat.id, target.id)
    await log_action(message.chat.id, "unmute", target.id, "manual unmute")
    await message.reply(f"Unmuted {target.full_name}.")


@router.message(Command("bkick"))
async def bkick_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    if not message.reply_to_message:
        await message.reply("Reply to the message from the user you want to kick.")
        return
    target = message.reply_to_message.from_user
    reason = message.text.partition(" ")[2].strip() or "manual kick"
    await _apply_action(bot, message.chat.id, target.id, "kick", reason)
    await message.reply(f"Kicked {target.full_name}.")


@router.message(Command("bban"))
async def bban_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    if not message.reply_to_message:
        await message.reply("Reply to the message from the user you want to ban.")
        return
    target = message.reply_to_message.from_user
    reason = message.text.partition(" ")[2].strip() or "manual ban"
    await _apply_action(bot, message.chat.id, target.id, "ban", reason)
    await message.reply(f"Banned {target.full_name}.")


@router.message(Command("bunban"))
async def bunban_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    arg = message.text.partition(" ")[2].strip()
    if not arg.isdigit():
        await message.reply("Usage: /bunban <user_id>")
        return
    try:
        await bot.unban_chat_member(message.chat.id, int(arg))
    except Exception:
        pass
    await log_action(message.chat.id, "unban", int(arg), "manual unban")
    await message.reply("Unbanned.")


@router.message(Command("bwarnlimit"))
async def bwarnlimit_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    arg = message.text.partition(" ")[2].strip()
    if not arg.isdigit() or int(arg) < 1:
        await message.reply("Usage: /bwarnlimit <number>")
        return
    async with async_session() as session:
        group = await session.get(Group, message.chat.id)
        if group:
            group.warn_limit = int(arg)
            await session.commit()
    await message.reply(f"Warn limit set to {arg}.")


# -------------------------------------------------------------- filters --

@router.message(Command("baddfilter"))
async def baddfilter_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    args = message.text.partition(" ")[2].strip().split(maxsplit=1)
    if len(args) != 2 or args[0].lower() not in ("word", "link"):
        await message.reply("Usage: /baddfilter word|link <pattern>")
        return
    filter_type, pattern = args[0].lower(), args[1].strip()
    async with async_session() as session:
        session.add(Filter(group_id=message.chat.id, type=filter_type, pattern=pattern))
        await session.commit()
    await message.reply(f"Added {filter_type} filter: {pattern}")


@router.message(Command("bremovefilter"))
async def bremovefilter_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    pattern = message.text.partition(" ")[2].strip()
    if not pattern:
        await message.reply("Usage: /bremovefilter <pattern>")
        return
    async with async_session() as session:
        result = await session.execute(
            select(Filter).where(Filter.group_id == message.chat.id, Filter.pattern == pattern)
        )
        rows = result.scalars().all()
        for row in rows:
            await session.delete(row)
        await session.commit()
    await message.reply(f"Removed {len(rows)} filter(s) matching: {pattern}" if rows else "No matching filter found.")


@router.message(Command("bfilters"))
async def bfilters_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    async with async_session() as session:
        result = await session.execute(select(Filter).where(Filter.group_id == message.chat.id))
        filters = result.scalars().all()
    if not filters:
        await message.reply("No filters set. Add one with /baddfilter word|link <pattern>")
        return
    lines = [f"- [{f.type}] {f.pattern}" for f in filters]
    await message.reply("Current filters:\n" + "\n".join(lines))


# ---------------------------------------------------------------- rules --

@router.message(Command("brules"))
async def brules_cmd(message: Message) -> None:
    async with async_session() as session:
        group = await session.get(Group, message.chat.id)
    await message.reply(group.rules if group and group.rules else "No rules set yet.")


@router.message(Command("bsetrules"))
async def bsetrules_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        await message.reply("Usage: /bsetrules <text>")
        return
    async with async_session() as session:
        group = await session.get(Group, message.chat.id)
        if group:
            group.rules = text
            await session.commit()
    await message.reply("Rules updated.")


# ------------------------------------------------ night mode / slow mode --

@router.message(Command("bnightmode"))
async def bnightmode_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    args = message.text.partition(" ")[2].strip().split()
    if not args or args[0].lower() not in ("on", "off"):
        await message.reply("Usage: /bnightmode on|off [start_hour] [end_hour]  (UTC, 0-23)")
        return
    enabled = args[0].lower() == "on"
    async with async_session() as session:
        group = await session.get(Group, message.chat.id)
        if group:
            group.night_mode_enabled = enabled
            if len(args) >= 3:
                try:
                    group.night_start_hour = int(args[1]) % 24
                    group.night_end_hour = int(args[2]) % 24
                except ValueError:
                    pass
            await session.commit()
    await message.reply(f"Night mode {'enabled' if enabled else 'disabled'}.")


@router.message(Command("bslowmode"))
async def bslowmode_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    arg = message.text.partition(" ")[2].strip()
    if not arg.isdigit():
        await message.reply("Usage: /bslowmode <seconds>  (0 to disable)")
        return
    seconds = int(arg)
    async with async_session() as session:
        group = await session.get(Group, message.chat.id)
        if group:
            group.slow_mode_seconds = seconds
            await session.commit()
    await message.reply(f"Slow mode set to {seconds}s." if seconds else "Slow mode disabled.")


# --------------------------------------------------------- purgatory --

@router.message(Command("bpurgatory"))
async def bpurgatory_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    arg = message.text.partition(" ")[2].strip().lower()
    if arg not in ("on", "off"):
        await message.reply("Usage: /bpurgatory on|off")
        return
    async with async_session() as session:
        group = await session.get(Group, message.chat.id)
        if group:
            group.purgatory_enabled = arg == "on"
            await session.commit()
    state = "hold new members for approval" if arg == "on" else "let new members join normally"
    await message.reply(f"Purgatory {'enabled' if arg == 'on' else 'disabled'} — the bot will now {state}.")


@router.message(Command("bcleanbots"))
async def bcleanbots_cmd(message: Message, bot: Bot) -> None:
    """Telegram's Bot API doesn't expose a full member list to bots (a
    privacy limit, not an oversight) — this can only sweep the
    administrators list, not every regular member. New unauthorized bots
    are still caught the moment they join, see purgatory.handle_new_bot."""
    if not await require_admin(bot, message):
        return
    admins = await bot.get_chat_administrators(message.chat.id)
    removed = []
    for admin in admins:
        user = admin.user
        if user.is_bot and (user.username or "").lower() not in allowed_bot_usernames():
            allowed = await handle_new_bot(bot, message.chat.id, user)
            if not allowed:
                removed.append(f"@{user.username or user.id}")
    await message.reply(
        "Removed unauthorized bots: " + ", ".join(removed) if removed else "No unauthorized bots found among current admins."
    )


@router.message(Command("bsetlogchannel"))
async def bsetlogchannel_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    arg = message.text.partition(" ")[2].strip()
    try:
        channel_id = int(arg)
    except ValueError:
        await message.reply("Usage: /bsetlogchannel <channel_id>  (bot must already be an admin there)")
        return
    async with async_session() as session:
        group = await session.get(Group, message.chat.id)
        if group:
            group.mod_log_channel_id = channel_id
            await session.commit()
    await message.reply("Log channel set.")


# -------------------------------------------------------------- AI tools --

@router.message(Command("bsetwelcome"))
async def bsetwelcome_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    arg = message.text.partition(" ")[2].strip()
    if not arg:
        await message.reply("Usage: /bsetwelcome <text>  or  /bsetwelcome ai <describe the vibe you want>")
        return

    if arg.lower().startswith("ai "):
        prompt = arg[3:].strip()
        generated = await admin_tool(
            f"Write a short, friendly welcome message for new members of a Telegram group. "
            f"Style/context: {prompt}. Keep it under 300 characters, no markdown."
        )
        new_text = generated.strip()
    else:
        new_text = arg

    async with async_session() as session:
        group = await session.get(Group, message.chat.id)
        if group:
            group.welcome_message = new_text
            await session.commit()
    await message.reply(f"Welcome message updated:\n\n{new_text}")


@router.message(Command("bsummarize"))
async def bsummarize_cmd(message: Message, bot: Bot) -> None:
    """Admin-only. Telegram bots can't pull arbitrary chat history on
    demand, so this summarizes whatever you reply to — wire in your own
    running message log later if you want a longer window."""
    if not await require_admin(bot, message):
        return
    source = message.reply_to_message.text if message.reply_to_message else None
    if not source:
        await message.reply("Reply to a message (or a pasted block of text) to summarize it.")
        return
    summary = await admin_tool(f"Summarize this group chat excerpt in 3 short bullet points:\n\n{source}")
    await message.reply(summary)


@router.message(Command("bai"))
async def bai_cmd(message: Message, bot: Bot) -> None:
    if not await require_admin(bot, message):
        return
    if not message.reply_to_message:
        await message.reply("Reply to the target user's message with /bai <instruction>, e.g. /bai mute them for spamming.")
        return
    instruction = message.text.partition(" ")[2].strip()
    if not instruction:
        await message.reply("Add an instruction after /bai, e.g. /bai ban this user.")
        return

    target = message.reply_to_message.from_user
    try:
        result = await interpret_admin_instruction(instruction)
    except RuntimeError:
        await message.reply("AI models are unavailable right now — try /bwarn /bmute /bkick /bban directly.")
        return

    action = result.get("action", "none")
    reason = result.get("reason", instruction)
    if action == "none":
        await message.reply("No action taken — didn't read that as a moderation instruction.")
        return

    await _apply_action(bot, message.chat.id, target.id, action, reason)
    await message.reply(f"Applied: {action} on {target.full_name} — {reason}")


# --------------------------------------------------------- auto-moderation --

@router.message(F.text & ~F.text.startswith("/"))
async def scan_message(message: Message, bot: Bot) -> None:
    """Runs automatically on every non-command message — the always-on
    safety layer. Separate from the admin-only tools above, which only ever
    run when an admin explicitly triggers them."""
    async with async_session() as session:
        group = await session.get(Group, message.chat.id)
    if not group:
        return

    is_admin = await is_telegram_admin(bot, message.chat.id, message.from_user.id)
    if not is_admin:
        if group.night_mode_enabled and is_night_mode_active(group):
            from app.bot.moderation import delete_silently

            await delete_silently(bot, message.chat.id, message.message_id)
            return
        if group.slow_mode_seconds and is_slow_mode_violation(message.chat.id, message.from_user.id, group.slow_mode_seconds):
            from app.bot.moderation import delete_silently

            await delete_silently(bot, message.chat.id, message.message_id)
            return
        if check_flood(message.chat.id, message.from_user.id):
            await flood_triggered(bot, message.chat.id, message.from_user.id, message.message_id)
            return

    if not group.ai_moderation_enabled:
        return
    await moderate_message(bot, message.chat.id, message.from_user.id, message.message_id, message.text)
