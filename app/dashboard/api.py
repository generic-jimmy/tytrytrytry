"""JSON API routes for the upgraded dashboard.

These endpoints back the SPA frontend. They are intentionally separate
from the legacy Jinja2 routes so the original server-rendered pages
keep working as a fallback. All routes under /api require a valid
session cookie and group access (the same auth the legacy pages use).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import delete, func, select

from app.auth import SESSION_COOKIE, read_session_cookie
from app.bot import bot as tg_bot
from app.bot.moderation import get_ai_config, mute_user, system_health, unmute_user
from app.bot.openrouter import AVAILABLE_MODELS, FALLBACK_MODELS, test_prompt
from app.bot.purgatory import resolve_purgatory_entry
from app.db import async_session
from app.models import (
    Admin,
    AIConfig,
    AnalyticsSnapshot,
    Appeal,
    AuditEvent,
    AutoResponse,
    CustomCommand,
    Filter,
    FlaggedMessage,
    Group,
    ModLog,
    PurgatoryEntry,
    ScheduledMessage,
    UserProfile,
    Warn,
)

router = APIRouter(prefix="/api")


# --------------------------------------------------------------- auth helpers --

async def _current_admin(request: Request) -> int:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Not signed in")
    uid = read_session_cookie(token)
    if uid is None:
        raise HTTPException(401, "Session expired")
    return uid


async def _assert_group_access(uid: int, group_id: int) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(Admin).where(Admin.telegram_user_id == uid, Admin.group_id == group_id)
        )
        if result.first() is None:
            raise HTTPException(403, "No access to this group")


async def _audit(uid: int, group_id: int, action: str, details: str = "") -> None:
    async with async_session() as session:
        session.add(AuditEvent(group_id=group_id, admin_id=uid, action=action, details=details))
        await session.commit()


def _group_id_path(request: Request) -> int:
    gid = request.path_params.get("group_id")
    if gid is None:
        raise HTTPException(400, "Missing group_id")
    try:
        return int(gid)
    except (TypeError, ValueError):
        raise HTTPException(400, "Invalid group_id")


# --------------------------------------------------------- groups & dashboard --

@router.get("/groups")
async def list_groups(request: Request):
    uid = await _current_admin(request)
    async with async_session() as session:
        result = await session.execute(
            select(Group).join(Admin, Admin.group_id == Group.id).where(Admin.telegram_user_id == uid)
        )
        groups = result.scalars().all()
    return {"groups": [{"id": g.id, "title": g.title or str(g.id), "theme": g.dashboard_theme} for g in groups]}


@router.get("/groups/{group_id}/overview")
async def group_overview(request: Request, group_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)

    async with async_session() as session:
        group = await session.get(Group, group_id)
        if group is None:
            raise HTTPException(404, "Group not found")

        messages_24h = await session.scalar(
            select(func.coalesce(func.sum(AnalyticsSnapshot.message_count), 0))
            .where(AnalyticsSnapshot.group_id == group_id, AnalyticsSnapshot.bucket_hour >= day_ago)
        )
        mod_actions_24h = await session.scalar(
            select(func.coalesce(func.sum(AnalyticsSnapshot.mod_actions), 0))
            .where(AnalyticsSnapshot.group_id == group_id, AnalyticsSnapshot.bucket_hour >= day_ago)
        )
        flags_24h = await session.scalar(
            select(func.coalesce(func.sum(AnalyticsSnapshot.flags_raised), 0))
            .where(AnalyticsSnapshot.group_id == group_id, AnalyticsSnapshot.bucket_hour >= day_ago)
        )
        new_members_24h = await session.scalar(
            select(func.coalesce(func.sum(AnalyticsSnapshot.new_members), 0))
            .where(AnalyticsSnapshot.group_id == group_id, AnalyticsSnapshot.bucket_hour >= day_ago)
        )

        total_members = await session.scalar(
            select(func.count()).select_from(UserProfile).where(UserProfile.group_id == group_id)
        )
        muted_count = await session.scalar(
            select(func.count())
            .select_from(UserProfile)
            .where(UserProfile.group_id == group_id, UserProfile.is_muted == True)  # noqa: E712
        )
        banned_count = await session.scalar(
            select(func.count())
            .select_from(UserProfile)
            .where(UserProfile.group_id == group_id, UserProfile.is_banned == True)  # noqa: E712
        )

        pending_purgatory = await session.scalar(
            select(func.count())
            .select_from(PurgatoryEntry)
            .where(
                PurgatoryEntry.group_id == group_id,
                PurgatoryEntry.status.in_(["pending", "suspicious"]),
            )
        )
        pending_flags = await session.scalar(
            select(func.count())
            .select_from(FlaggedMessage)
            .where(FlaggedMessage.group_id == group_id, FlaggedMessage.status == "pending")
        )
        pending_appeals = await session.scalar(
            select(func.count())
            .select_from(Appeal)
            .where(Appeal.group_id == group_id, Appeal.status == "pending")
        )

        recent_mod = await session.execute(
            select(ModLog).where(ModLog.group_id == group_id).order_by(ModLog.created_at.desc()).limit(10)
        )
        recent_actions = [
            {
                "id": m.id,
                "action": m.action,
                "target_user_id": m.target_user_id,
                "reason": m.reason,
                "admin_id": m.admin_id,
                "created_at": m.created_at.isoformat(),
            }
            for m in recent_mod.scalars().all()
        ]

        # Activity over the last 24 hours, broken into hourly buckets for the chart.
        bucket_result = await session.execute(
            select(AnalyticsSnapshot)
            .where(AnalyticsSnapshot.group_id == group_id, AnalyticsSnapshot.bucket_hour >= day_ago)
            .order_by(AnalyticsSnapshot.bucket_hour)
        )
        buckets = bucket_result.scalars().all()
        activity = [
            {
                "hour": b.bucket_hour.strftime("%H:%M"),
                "messages": b.message_count,
                "mod_actions": b.mod_actions,
                "flags": b.flags_raised,
                "new_members": b.new_members,
                "ai_calls": b.ai_calls,
            }
            for b in buckets
        ]

    return {
        "group": {
            "id": group.id,
            "title": group.title or str(group.id),
            "ai_moderation_enabled": group.ai_moderation_enabled,
            "purgatory_enabled": group.purgatory_enabled,
            "night_mode_enabled": group.night_mode_enabled,
            "night_start_hour": group.night_start_hour,
            "night_end_hour": group.night_end_hour,
            "slow_mode_seconds": group.slow_mode_seconds,
            "warn_limit": group.warn_limit,
            "mod_log_channel_id": group.mod_log_channel_id,
            "dashboard_theme": group.dashboard_theme,
        },
        "stats": {
            "messages_24h": int(messages_24h or 0),
            "mod_actions_24h": int(mod_actions_24h or 0),
            "flags_24h": int(flags_24h or 0),
            "new_members_24h": int(new_members_24h or 0),
            "total_members": int(total_members or 0),
            "muted_count": int(muted_count or 0),
            "banned_count": int(banned_count or 0),
            "pending_purgatory": int(pending_purgatory or 0),
            "pending_flags": int(pending_flags or 0),
            "pending_appeals": int(pending_appeals or 0),
        },
        "recent_actions": recent_actions,
        "activity": activity,
        "health": system_health(),
    }


# ------------------------------------------------------------------ members --

@router.get("/groups/{group_id}/members")
async def list_members(request: Request, group_id: int, q: str = "", status: str = "", limit: int = 100, offset: int = 0):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))

    stmt = select(UserProfile).where(UserProfile.group_id == group_id)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            (func.lower(UserProfile.username).like(like))
            | (func.lower(UserProfile.full_name).like(like))
            | (func.cast(UserProfile.user_id, __import__("sqlalchemy").String).like(like))
        )
    if status == "muted":
        stmt = stmt.where(UserProfile.is_muted == True)  # noqa: E712
    elif status == "banned":
        stmt = stmt.where(UserProfile.is_banned == True)  # noqa: E712
    elif status == "warned":
        stmt = stmt.where(UserProfile.warn_count > 0)

    total = await _scalar_count(select(func.count()).select_from(stmt.subquery()))
    stmt = stmt.order_by(UserProfile.last_active.desc().nullslast()).limit(limit).offset(offset)
    async with async_session() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return {
        "total": int(total or 0),
        "members": [
            {
                "user_id": m.user_id,
                "username": m.username,
                "full_name": m.full_name,
                "reputation": m.reputation,
                "message_count": m.message_count,
                "warn_count": m.warn_count,
                "is_muted": m.is_muted,
                "is_banned": m.is_banned,
                "first_seen": m.first_seen.isoformat() if m.first_seen else None,
                "last_active": m.last_active.isoformat() if m.last_active else None,
            }
            for m in rows
        ],
    }


async def _scalar_count(stmt) -> int:
    async with async_session() as session:
        return await session.scalar(stmt)


@router.get("/groups/{group_id}/members/{user_id}")
async def member_detail(request: Request, group_id: int, user_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        result = await session.execute(
            select(UserProfile).where(
                UserProfile.group_id == group_id, UserProfile.user_id == user_id
            )
        )
        profile = result.scalar_one_or_none()
        warns = (
            await session.execute(
                select(Warn).where(Warn.group_id == group_id, Warn.user_id == user_id).order_by(Warn.created_at.desc()).limit(50)
            )
        ).scalars().all()
        mods = (
            await session.execute(
                select(ModLog)
                .where(ModLog.group_id == group_id, ModLog.target_user_id == user_id)
                .order_by(ModLog.created_at.desc())
                .limit(50)
            )
        ).scalars().all()
    if profile is None:
        raise HTTPException(404, "No profile for this user")
    return {
        "profile": {
            "user_id": profile.user_id,
            "username": profile.username,
            "full_name": profile.full_name,
            "reputation": profile.reputation,
            "message_count": profile.message_count,
            "warn_count": profile.warn_count,
            "is_muted": profile.is_muted,
            "is_banned": profile.is_banned,
            "first_seen": profile.first_seen.isoformat() if profile.first_seen else None,
            "last_active": profile.last_active.isoformat() if profile.last_active else None,
        },
        "warns": [
            {"id": w.id, "reason": w.reason, "created_at": w.created_at.isoformat()} for w in warns
        ],
        "mod_actions": [
            {"id": m.id, "action": m.action, "reason": m.reason, "created_at": m.created_at.isoformat()}
            for m in mods
        ],
    }


@router.post("/groups/{group_id}/members/{user_id}/{action}")
async def member_action(request: Request, group_id: int, user_id: int, action: str):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    if action not in ("mute", "unmute", "ban", "unban", "reset_reputation"):
        raise HTTPException(400, "Unknown action")

    if action == "mute":
        await mute_user(tg_bot, group_id, user_id)
    elif action == "unmute":
        await unmute_user(tg_bot, group_id, user_id)
    elif action == "ban":
        try:
            await tg_bot.ban_chat_member(group_id, user_id)
        except Exception as exc:
            raise HTTPException(500, f"Ban failed: {exc}")
        async with async_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.group_id == group_id, UserProfile.user_id == user_id)
            )
            p = result.scalar_one_or_none()
            if p:
                p.is_banned = True
                await session.commit()
    elif action == "unban":
        try:
            await tg_bot.unban_chat_member(group_id, user_id)
        except Exception as exc:
            raise HTTPException(500, f"Unban failed: {exc}")
        async with async_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.group_id == group_id, UserProfile.user_id == user_id)
            )
            p = result.scalar_one_or_none()
            if p:
                p.is_banned = False
                await session.commit()
    elif action == "reset_reputation":
        async with async_session() as session:
            result = await session.execute(
                select(UserProfile).where(UserProfile.group_id == group_id, UserProfile.user_id == user_id)
            )
            p = result.scalar_one_or_none()
            if p:
                p.reputation = 0
                await session.commit()

    await _audit(uid, group_id, f"member_{action}", f"user_id={user_id}")
    return {"ok": True}


# ------------------------------------------------------------------ AI config --

@router.get("/groups/{group_id}/ai-config")
async def get_ai_config_api(request: Request, group_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    cfg = await get_ai_config(group_id)
    return {
        "id": cfg.id,
        "group_id": cfg.group_id,
        "model": cfg.model,
        "temperature": cfg.temperature,
        "confidence_threshold": cfg.confidence_threshold,
        "custom_system_prompt": cfg.custom_system_prompt,
        "auto_ban_high": cfg.auto_ban_high,
        "auto_flag_medium": cfg.auto_flag_medium,
        "enabled_categories": cfg.enabled_categories,
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
        "available_models": [{"value": v, "label": l} for v, l in AVAILABLE_MODELS],
        "default_models": FALLBACK_MODELS,
    }


@router.put("/groups/{group_id}/ai-config")
async def update_ai_config_api(request: Request, group_id: int, payload: dict = Body(...)):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    cfg = await get_ai_config(group_id)
    async with async_session() as session:
        db_cfg = await session.get(AIConfig, cfg.id)
        if db_cfg is None:
            raise HTTPException(404, "AI config missing")
        if "model" in payload:
            db_cfg.model = str(payload["model"])
        if "temperature" in payload:
            db_cfg.temperature = max(0.0, min(2.0, float(payload["temperature"])))
        if "confidence_threshold" in payload:
            db_cfg.confidence_threshold = max(0.0, min(1.0, float(payload["confidence_threshold"])))
        if "custom_system_prompt" in payload:
            db_cfg.custom_system_prompt = str(payload["custom_system_prompt"])[:8000]
        if "auto_ban_high" in payload:
            db_cfg.auto_ban_high = bool(payload["auto_ban_high"])
        if "auto_flag_medium" in payload:
            db_cfg.auto_flag_medium = bool(payload["auto_flag_medium"])
        if "enabled_categories" in payload:
            cats = ",".join(
                c.strip() for c in str(payload["enabled_categories"]).split(",") if c.strip()
            )
            db_cfg.enabled_categories = cats
        await session.commit()
    await _audit(uid, group_id, "ai_config_update", f"model={payload.get('model')}")
    return {"ok": True}


@router.post("/groups/{group_id}/ai-config/test")
async def test_ai_prompt(request: Request, group_id: int, payload: dict = Body(...)):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    cfg = await get_ai_config(group_id)
    user_prompt = str(payload.get("user_prompt", "")).strip()
    system_prompt = str(payload.get("system_prompt", "")).strip() or cfg.custom_system_prompt
    if not user_prompt:
        raise HTTPException(400, "user_prompt is required")
    try:
        result = await test_prompt(
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            model=cfg.model,
            temperature=cfg.temperature,
        )
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))
    return {"response": result}


# ---------------------------------------------------------- custom commands --

@router.get("/groups/{group_id}/custom-commands")
async def list_custom_commands(request: Request, group_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        result = await session.execute(
            select(CustomCommand).where(CustomCommand.group_id == group_id).order_by(CustomCommand.created_at.desc())
        )
        cmds = result.scalars().all()
    return {
        "commands": [
            {
                "id": c.id,
                "trigger": c.trigger,
                "response": c.response,
                "created_by": c.created_by,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in cmds
        ]
    }


@router.post("/groups/{group_id}/custom-commands")
async def add_custom_command(request: Request, group_id: int, payload: dict = Body(...)):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    trigger = str(payload.get("trigger", "")).strip().lstrip("/").lower()
    response = str(payload.get("response", "")).strip()
    if not trigger or not response:
        raise HTTPException(400, "trigger and response are required")
    async with async_session() as session:
        session.add(CustomCommand(group_id=group_id, trigger=trigger, response=response, created_by=uid))
        await session.commit()
    await _audit(uid, group_id, "custom_command_add", f"/{trigger}")
    return {"ok": True}


@router.delete("/groups/{group_id}/custom-commands/{command_id}")
async def delete_custom_command(request: Request, group_id: int, command_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        cmd = await session.get(CustomCommand, command_id)
        if cmd and cmd.group_id == group_id:
            await session.delete(cmd)
            await session.commit()
    await _audit(uid, group_id, "custom_command_delete", f"id={command_id}")
    return {"ok": True}


# ---------------------------------------------------------- auto-responses --

@router.get("/groups/{group_id}/auto-responses")
async def list_auto_responses(request: Request, group_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        result = await session.execute(
            select(AutoResponse).where(AutoResponse.group_id == group_id).order_by(AutoResponse.created_at.desc())
        )
        rows = result.scalars().all()
    return {
        "responses": [
            {
                "id": r.id,
                "trigger": r.trigger,
                "response": r.response,
                "match_type": r.match_type,
                "case_sensitive": r.case_sensitive,
                "enabled": r.enabled,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.post("/groups/{group_id}/auto-responses")
async def add_auto_response(request: Request, group_id: int, payload: dict = Body(...)):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    trigger = str(payload.get("trigger", "")).strip()
    response = str(payload.get("response", "")).strip()
    match_type = str(payload.get("match_type", "contains"))
    if match_type not in ("contains", "exact", "regex"):
        match_type = "contains"
    if not trigger or not response:
        raise HTTPException(400, "trigger and response are required")
    async with async_session() as session:
        session.add(
            AutoResponse(
                group_id=group_id,
                trigger=trigger,
                response=response,
                match_type=match_type,
                case_sensitive=bool(payload.get("case_sensitive", False)),
                enabled=bool(payload.get("enabled", True)),
            )
        )
        await session.commit()
    await _audit(uid, group_id, "auto_response_add", f"trigger={trigger}")
    return {"ok": True}


@router.put("/groups/{group_id}/auto-responses/{resp_id}")
async def update_auto_response(request: Request, group_id: int, resp_id: int, payload: dict = Body(...)):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        r = await session.get(AutoResponse, resp_id)
        if r is None or r.group_id != group_id:
            raise HTTPException(404, "Not found")
        if "trigger" in payload:
            r.trigger = str(payload["trigger"]).strip()
        if "response" in payload:
            r.response = str(payload["response"]).strip()
        if "match_type" in payload:
            r.match_type = str(payload["match_type"])
        if "case_sensitive" in payload:
            r.case_sensitive = bool(payload["case_sensitive"])
        if "enabled" in payload:
            r.enabled = bool(payload["enabled"])
        await session.commit()
    return {"ok": True}


@router.delete("/groups/{group_id}/auto-responses/{resp_id}")
async def delete_auto_response(request: Request, group_id: int, resp_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        r = await session.get(AutoResponse, resp_id)
        if r and r.group_id == group_id:
            await session.delete(r)
            await session.commit()
    return {"ok": True}


# --------------------------------------------------------- scheduled msgs --

@router.get("/groups/{group_id}/scheduled")
async def list_scheduled(request: Request, group_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        result = await session.execute(
            select(ScheduledMessage)
            .where(ScheduledMessage.group_id == group_id)
            .order_by(ScheduledMessage.scheduled_for.desc())
        )
        rows = result.scalars().all()
    return {
        "scheduled": [
            {
                "id": s.id,
                "text": s.text,
                "scheduled_for": s.scheduled_for.isoformat(),
                "repeat_hour": s.repeat_hour,
                "sent": s.sent,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in rows
        ]
    }


@router.post("/groups/{group_id}/scheduled")
async def add_scheduled(request: Request, group_id: int, payload: dict = Body(...)):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    text = str(payload.get("text", "")).strip()
    iso = str(payload.get("scheduled_for", "")).strip()
    repeat_hour = payload.get("repeat_hour")
    if not text or not iso:
        raise HTTPException(400, "text and scheduled_for are required")
    try:
        scheduled_for = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(400, "Invalid ISO datetime for scheduled_for")
    rh = None
    if repeat_hour is not None:
        try:
            rh = int(repeat_hour) % 24
        except (TypeError, ValueError):
            rh = None
    async with async_session() as session:
        session.add(
            ScheduledMessage(
                group_id=group_id,
                text=text,
                scheduled_for=scheduled_for,
                repeat_hour=rh,
                created_by=uid,
            )
        )
        await session.commit()
    await _audit(uid, group_id, "scheduled_add", f"for={scheduled_for.isoformat()}")
    return {"ok": True}


@router.delete("/groups/{group_id}/scheduled/{msg_id}")
async def delete_scheduled(request: Request, group_id: int, msg_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        s = await session.get(ScheduledMessage, msg_id)
        if s and s.group_id == group_id:
            await session.delete(s)
            await session.commit()
    return {"ok": True}


# ----------------------------------------------------------------- appeals --

@router.get("/groups/{group_id}/appeals")
async def list_appeals(request: Request, group_id: int, status: str = "pending"):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    if status not in ("pending", "approved", "denied", "all"):
        status = "pending"
    stmt = select(Appeal).where(Appeal.group_id == group_id)
    if status != "all":
        stmt = stmt.where(Appeal.status == status)
    stmt = stmt.order_by(Appeal.created_at.desc()).limit(200)
    async with async_session() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return {
        "appeals": [
            {
                "id": a.id,
                "user_id": a.user_id,
                "target_action": a.target_action,
                "reason": a.reason,
                "status": a.status,
                "admin_note": a.admin_note,
                "decided_by": a.decided_by,
                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ]
    }


@router.post("/groups/{group_id}/appeals/{appeal_id}/{decision}")
async def resolve_appeal(request: Request, group_id: int, appeal_id: int, decision: str, payload: dict = Body(default={})):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    if decision not in ("approve", "deny"):
        raise HTTPException(400, "Decision must be approve or deny")
    note = str(payload.get("note", "")).strip()
    async with async_session() as session:
        a = await session.get(Appeal, appeal_id)
        if a is None or a.group_id != group_id:
            raise HTTPException(404, "Appeal not found")
        a.status = "approved" if decision == "approve" else "denied"
        a.admin_note = note
        a.decided_by = uid
        a.decided_at = datetime.now(timezone.utc)
        await session.commit()
        if decision == "approve":
            # Lift the action against the user — best effort, may fail if the
            # user was banned long ago or is no longer in the chat.
            try:
                if "ban" in a.target_action:
                    await tg_bot.unban_chat_member(group_id, a.user_id)
                elif "mute" in a.target_action:
                    await unmute_user(tg_bot, group_id, a.user_id)
            except Exception:
                pass
    await _audit(uid, group_id, "appeal_resolve", f"id={appeal_id} decision={decision}")
    return {"ok": True}


# ------------------------------------------------------- flagged messages --

@router.get("/groups/{group_id}/flags")
async def list_flags(request: Request, group_id: int, status: str = "pending"):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    stmt = select(FlaggedMessage).where(FlaggedMessage.group_id == group_id)
    if status != "all":
        stmt = stmt.where(FlaggedMessage.status == status)
    stmt = stmt.order_by(FlaggedMessage.created_at.desc()).limit(200)
    async with async_session() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return {
        "flags": [
            {
                "id": f.id,
                "user_id": f.user_id,
                "message_text": f.message_text,
                "category": f.category,
                "severity": f.severity,
                "confidence": f.confidence,
                "status": f.status,
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in rows
        ]
    }


@router.post("/groups/{group_id}/flags/{flag_id}/{decision}")
async def resolve_flag_api(request: Request, group_id: int, flag_id: int, decision: str):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    if decision not in ("approve", "dismiss"):
        raise HTTPException(400, "Decision must be approve or dismiss")
    new_status = "approved" if decision == "approve" else "dismissed"
    async with async_session() as session:
        flag = await session.get(FlaggedMessage, flag_id)
        if flag and flag.group_id == group_id:
            flag.status = new_status
            await session.commit()
    await _audit(uid, group_id, "flag_resolve", f"id={flag_id} decision={decision}")
    return {"ok": True}


# ----------------------------------------------------------------- purgatory --

@router.get("/groups/{group_id}/purgatory")
async def list_purgatory_api(request: Request, group_id: int, tab: str = "pending"):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    if tab not in ("pending", "suspicious", "approved", "denied", "banned"):
        tab = "pending"
    async with async_session() as session:
        group = await session.get(Group, group_id)
        result = await session.execute(
            select(PurgatoryEntry)
            .where(PurgatoryEntry.group_id == group_id, PurgatoryEntry.status == tab)
            .order_by(PurgatoryEntry.joined_at.desc())
        )
        entries = result.scalars().all()
        count_result = await session.execute(
            select(PurgatoryEntry.status, func.count())
            .where(PurgatoryEntry.group_id == group_id)
            .group_by(PurgatoryEntry.status)
        )
        raw_counts = dict(count_result.all())
    counts = {status: raw_counts.get(status, 0) for status in ("pending", "suspicious", "approved", "denied", "banned")}
    return {
        "entries": [
            {
                "id": e.id,
                "user_id": e.user_id,
                "username": e.username,
                "full_name": e.full_name,
                "language_code": e.language_code,
                "is_premium": e.is_premium,
                "status": e.status,
                "joined_at": e.joined_at.isoformat() if e.joined_at else None,
                "decided_at": e.decided_at.isoformat() if e.decided_at else None,
                "decided_by": e.decided_by,
            }
            for e in entries
        ],
        "counts": counts,
        "purgatory_enabled": group.purgatory_enabled if group else True,
    }


@router.post("/groups/{group_id}/purgatory/{entry_id}/{decision}")
async def decide_purgatory_api(request: Request, group_id: int, entry_id: int, decision: str):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    if decision not in ("approve", "deny", "ban"):
        raise HTTPException(400, "Decision must be approve, deny, or ban")
    async with async_session() as session:
        entry = await session.get(PurgatoryEntry, entry_id)
    if entry and entry.group_id == group_id:
        await resolve_purgatory_entry(tg_bot, entry, decision, decided_by=uid)
    await _audit(uid, group_id, "purgatory_decide", f"id={entry_id} decision={decision}")
    return {"ok": True}


@router.post("/groups/{group_id}/purgatory/toggle")
async def toggle_purgatory_api(request: Request, group_id: int, payload: dict = Body(default={})):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    always_allow = bool(payload.get("always_allow", False))
    async with async_session() as session:
        group = await session.get(Group, group_id)
        if group:
            group.purgatory_enabled = not always_allow
            await session.commit()
    await _audit(uid, group_id, "purgatory_toggle", f"always_allow={always_allow}")
    return {"ok": True, "purgatory_enabled": not always_allow}


# ----------------------------------------------------------------- modlog --

@router.get("/groups/{group_id}/modlog")
async def list_modlog_api(request: Request, group_id: int, action: str = "", limit: int = 200, offset: int = 0):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    stmt = select(ModLog).where(ModLog.group_id == group_id)
    if action:
        stmt = stmt.where(ModLog.action == action)
    stmt = stmt.order_by(ModLog.created_at.desc()).limit(limit).offset(offset)
    async with async_session() as session:
        result = await session.execute(stmt)
        rows = result.scalars().all()
    return {
        "logs": [
            {
                "id": l.id,
                "action": l.action,
                "target_user_id": l.target_user_id,
                "reason": l.reason,
                "admin_id": l.admin_id,
                "created_at": l.created_at.isoformat() if l.created_at else None,
            }
            for l in rows
        ]
    }


# --------------------------------------------------------------- analytics --

@router.get("/groups/{group_id}/analytics")
async def analytics_api(request: Request, group_id: int, days: int = 7):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    days = max(1, min(int(days), 30))
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    async with async_session() as session:
        result = await session.execute(
            select(AnalyticsSnapshot)
            .where(AnalyticsSnapshot.group_id == group_id, AnalyticsSnapshot.bucket_hour >= start)
            .order_by(AnalyticsSnapshot.bucket_hour)
        )
        snaps = result.scalars().all()

        # Severity distribution for flagged messages (last 30 days).
        sev_result = await session.execute(
            select(FlaggedMessage.severity, func.count())
            .where(FlaggedMessage.group_id == group_id, FlaggedMessage.created_at >= start)
            .group_by(FlaggedMessage.severity)
        )
        sev_counts = dict(sev_result.all())

        cat_result = await session.execute(
            select(FlaggedMessage.category, func.count())
            .where(FlaggedMessage.group_id == group_id, FlaggedMessage.created_at >= start)
            .group_by(FlaggedMessage.category)
        )
        cat_counts = dict(cat_result.all())

        action_result = await session.execute(
            select(ModLog.action, func.count())
            .where(ModLog.group_id == group_id, ModLog.created_at >= start)
            .group_by(ModLog.action)
        )
        action_counts = dict(action_result.all())

        top_members = await session.execute(
            select(UserProfile)
            .where(UserProfile.group_id == group_id)
            .order_by(UserProfile.message_count.desc())
            .limit(10)
        )
        top = top_members.scalars().all()

    return {
        "buckets": [
            {
                "hour": b.bucket_hour.isoformat(),
                "messages": b.message_count,
                "mod_actions": b.mod_actions,
                "flags": b.flags_raised,
                "new_members": b.new_members,
                "ai_calls": b.ai_calls,
            }
            for b in snaps
        ],
        "severity_distribution": sev_counts,
        "category_distribution": cat_counts,
        "action_distribution": action_counts,
        "top_members": [
            {
                "user_id": m.user_id,
                "username": m.username,
                "full_name": m.full_name,
                "message_count": m.message_count,
                "reputation": m.reputation,
            }
            for m in top
        ],
        "days": days,
    }


# ---------------------------------------------------------------- filters --

@router.get("/groups/{group_id}/filters")
async def list_filters_api(request: Request, group_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        result = await session.execute(select(Filter).where(Filter.group_id == group_id))
        rows = result.scalars().all()
    return {
        "filters": [
            {"id": f.id, "type": f.type, "pattern": f.pattern} for f in rows
        ]
    }


@router.post("/groups/{group_id}/filters")
async def add_filter_api(request: Request, group_id: int, payload: dict = Body(...)):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    ftype = str(payload.get("type", "word"))
    pattern = str(payload.get("pattern", "")).strip()
    if ftype not in ("word", "link") or not pattern:
        raise HTTPException(400, "type must be word|link and pattern required")
    async with async_session() as session:
        session.add(Filter(group_id=group_id, type=ftype, pattern=pattern))
        await session.commit()
    await _audit(uid, group_id, "filter_add", f"{ftype}:{pattern}")
    return {"ok": True}


@router.delete("/groups/{group_id}/filters/{filter_id}")
async def delete_filter_api(request: Request, group_id: int, filter_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        f = await session.get(Filter, filter_id)
        if f and f.group_id == group_id:
            await session.delete(f)
            await session.commit()
    return {"ok": True}


# ----------------------------------------------------------------- settings --

@router.get("/groups/{group_id}/settings")
async def get_settings_api(request: Request, group_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        group = await session.get(Group, group_id)
        if group is None:
            raise HTTPException(404, "Group not found")
    return {
        "id": group.id,
        "title": group.title,
        "ai_moderation_enabled": group.ai_moderation_enabled,
        "welcome_message": group.welcome_message,
        "rules": group.rules,
        "warn_limit": group.warn_limit,
        "night_mode_enabled": group.night_mode_enabled,
        "night_start_hour": group.night_start_hour,
        "night_end_hour": group.night_end_hour,
        "slow_mode_seconds": group.slow_mode_seconds,
        "purgatory_enabled": group.purgatory_enabled,
        "mod_log_channel_id": group.mod_log_channel_id,
        "dashboard_theme": group.dashboard_theme,
    }


@router.put("/groups/{group_id}/settings")
async def update_settings_api(request: Request, group_id: int, payload: dict = Body(...)):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    async with async_session() as session:
        group = await session.get(Group, group_id)
        if group is None:
            raise HTTPException(404, "Group not found")
        if "welcome_message" in payload:
            group.welcome_message = str(payload["welcome_message"])[:4000]
        if "rules" in payload:
            group.rules = str(payload["rules"])[:8000]
        if "ai_moderation_enabled" in payload:
            group.ai_moderation_enabled = bool(payload["ai_moderation_enabled"])
        if "purgatory_enabled" in payload:
            group.purgatory_enabled = bool(payload["purgatory_enabled"])
        if "night_mode_enabled" in payload:
            group.night_mode_enabled = bool(payload["night_mode_enabled"])
        if "night_start_hour" in payload:
            try:
                group.night_start_hour = int(payload["night_start_hour"]) % 24
            except (TypeError, ValueError):
                pass
        if "night_end_hour" in payload:
            try:
                group.night_end_hour = int(payload["night_end_hour"]) % 24
            except (TypeError, ValueError):
                pass
        if "warn_limit" in payload:
            try:
                group.warn_limit = max(1, int(payload["warn_limit"]))
            except (TypeError, ValueError):
                pass
        if "slow_mode_seconds" in payload:
            try:
                group.slow_mode_seconds = max(0, int(payload["slow_mode_seconds"]))
            except (TypeError, ValueError):
                pass
        if "mod_log_channel_id" in payload:
            try:
                val = payload["mod_log_channel_id"]
                group.mod_log_channel_id = int(val) if val not in (None, "", 0) else None
            except (TypeError, ValueError):
                pass
        if "dashboard_theme" in payload:
            group.dashboard_theme = str(payload["dashboard_theme"])[:20]
        await session.commit()
    await _audit(uid, group_id, "settings_update", ",".join(sorted(payload.keys())))
    return {"ok": True}


# ----------------------------------------------------------------- audit --

@router.get("/groups/{group_id}/audit")
async def list_audit_api(request: Request, group_id: int, limit: int = 200):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    limit = max(1, min(int(limit), 500))
    async with async_session() as session:
        result = await session.execute(
            select(AuditEvent)
            .where(AuditEvent.group_id == group_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
    return {
        "events": [
            {
                "id": e.id,
                "admin_id": e.admin_id,
                "action": e.action,
                "details": e.details,
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ]
    }


# ------------------------------------------------------------------ health --

@router.get("/groups/{group_id}/health")
async def health_api(request: Request, group_id: int):
    uid = await _current_admin(request)
    await _assert_group_access(uid, group_id)
    return system_health()
