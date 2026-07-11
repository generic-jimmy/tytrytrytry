from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram chat id
    title: Mapped[str] = mapped_column(String(255), default="")
    ai_moderation_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    welcome_message: Mapped[str] = mapped_column(Text, default="Welcome to the group!")
    rules: Mapped[str] = mapped_column(Text, default="")

    warn_limit: Mapped[int] = mapped_column(Integer, default=3)

    # Night mode — hours are UTC, 0-23. Non-admin messages are deleted while active.
    night_mode_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    night_start_hour: Mapped[int] = mapped_column(Integer, default=22)
    night_end_hour: Mapped[int] = mapped_column(Integer, default=6)

    # Slow mode — minimum seconds between messages per user. 0 = disabled.
    slow_mode_seconds: Mapped[int] = mapped_column(Integer, default=0)

    # Purgatory — hold new members in a muted state until an admin reviews them.
    purgatory_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Optional channel the bot posts every ModLog entry to. Bot must already
    # be an admin in that channel. Null = don't post anywhere.
    mod_log_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Theme preference for this group's dashboard (cosmetic only).
    dashboard_theme: Mapped[str] = mapped_column(String(20), default="dark")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Admin(Base):
    """Maps a Telegram user to a group for WEB DASHBOARD access. This is
    separate from Telegram's own admin list for that group — it's populated
    automatically the first time a real Telegram group admin uses an admin
    command (see bot/handlers.py: sync_admin)."""

    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    role: Mapped[str] = mapped_column(String(20), default="admin")  # admin | superadmin
    display_name: Mapped[str] = mapped_column(String(255), default="")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Warn(Base):
    __tablename__ = "warns"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModLog(Base):
    __tablename__ = "mod_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    action: Mapped[str] = mapped_column(String(50))
    target_user_id: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str] = mapped_column(Text, default="")
    admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FlaggedMessage(Base):
    """Borderline AI-moderation calls land here for a human admin to review.
    Clear-cut violations skip this and go straight to ModLog with automatic
    action instead — see bot/moderation.py."""

    __tablename__ = "flagged_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    message_text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50))
    severity: Mapped[str] = mapped_column(String(20))
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Filter(Base):
    __tablename__ = "filters"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    type: Mapped[str] = mapped_column(String(10))  # "word" or "link"
    pattern: Mapped[str] = mapped_column(String(255))


class PurgatoryEntry(Base):
    """One row per new member held for admin approval. Telegram's Bot API
    doesn't expose device/IP/hardware info (unlike the game-server-style
    panel this UI is modeled on) — these are the fields actually available
    for a Telegram user."""

    __tablename__ = "purgatory_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(255), default="")
    full_name: Mapped[str] = mapped_column(String(255), default="")
    language_code: Mapped[str] = mapped_column(String(10), default="")
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, suspicious, approved, denied, banned
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


# --------------------------------------------------------------- new tables --
# The tables below power the "major upgrades" the dashboard now exposes:
# per-user reputation, custom bot commands, auto-response triggers,
# scheduled messages, AI configuration, warning appeals, and rolled-up
# analytics snapshots.


class UserProfile(Base):
    """One row per (group, user). Tracks reputation and aggregate stats so
    the dashboard can render member profiles and identify repeat offenders
    or valuable contributors at a glance."""

    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[str] = mapped_column(String(255), default="")
    full_name: Mapped[str] = mapped_column(String(255), default="")
    reputation: Mapped[int] = mapped_column(Integer, default=0)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    warn_count: Mapped[int] = mapped_column(Integer, default=0)
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomCommand(Base):
    """Admin-defined slash commands. /<trigger> in the group replies with
    <response>. Lets admins add group-specific commands without touching
    code."""

    __tablename__ = "custom_commands"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(64))  # e.g. "discord" -> /discord
    response: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AutoResponse(Base):
    """Trigger phrase -> automated response. Unlike filters (which delete),
    auto-responses reply with a helpful message when the trigger is matched
    anywhere in a user's message."""

    __tablename__ = "auto_responses"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(255))
    response: Mapped[str] = mapped_column(Text)
    match_type: Mapped[str] = mapped_column(String(20), default="contains")  # contains|exact|regex
    case_sensitive: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScheduledMessage(Base):
    """Messages the bot will post at a future time. Repeats optionally
    supported via repeat_cron (simple hour-of-day string)."""

    __tablename__ = "scheduled_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    repeat_hour: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-23 daily repeat, null = one-shot
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AIConfig(Base):
    """Per-group AI moderation tuning. Stored separately from Group so the
    AI panel can be edited without touching core group settings."""

    __tablename__ = "ai_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), index=True)
    model: Mapped[str] = mapped_column(String(128), default="meta-llama/llama-3.3-70b-instruct:free")
    temperature: Mapped[float] = mapped_column(Float, default=0.2)
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.6)
    custom_system_prompt: Mapped[str] = mapped_column(Text, default="")
    auto_ban_high: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_flag_medium: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled_categories: Mapped[str] = mapped_column(String(255), default="spam,toxicity,threat,scam_link,other")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Appeal(Base):
    """Users can appeal a warning or ban via the bot command /bappeal.
    These show up in the dashboard Appeals tab for admin review."""

    __tablename__ = "appeals"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    target_action: Mapped[str] = mapped_column(String(50))  # warn, mute, ban
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, approved, denied
    admin_note: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalyticsSnapshot(Base):
    """Hourly rollup of activity per group. Keeps the dashboard fast even
    after months of message history — analytics queries hit this table
    instead of scanning raw mod_log rows."""

    __tablename__ = "analytics_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), index=True)
    bucket_hour: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    mod_actions: Mapped[int] = mapped_column(Integer, default=0)
    flags_raised: Mapped[int] = mapped_column(Integer, default=0)
    new_members: Mapped[int] = mapped_column(Integer, default=0)
    ai_calls: Mapped[int] = mapped_column(Integer, default=0)


class AuditEvent(Base):
    """Dashboard-driven actions (settings edits, filter changes, AI prompt
    edits, etc.) are recorded here so there's a full audit trail of who
    changed what from the UI, separate from the bot-driven mod_log."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("groups.id"), index=True)
    admin_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(100))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
