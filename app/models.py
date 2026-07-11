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
