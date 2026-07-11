from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.auth import SESSION_COOKIE, create_session_cookie, read_session_cookie, verify_telegram_login
from app.bot import bot as tg_bot
from app.bot.purgatory import resolve_purgatory_entry
from app.config import settings
from app.db import async_session
from app.models import Admin, Filter, FlaggedMessage, Group, ModLog, PurgatoryEntry

router = APIRouter()
templates = Jinja2Templates(directory="app/dashboard/templates")

PURGATORY_STATUSES = ["pending", "suspicious", "approved", "denied", "banned"]


def get_current_admin(request: Request) -> int | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return read_session_cookie(token)


async def has_group_access(uid: int, group_id: int) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(Admin).where(Admin.telegram_user_id == uid, Admin.group_id == group_id)
        )
        return result.first() is not None


# -------------------------------------------------------------------- auth --

@router.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"bot_username": settings.telegram_bot_username})


@router.get("/auth/telegram/callback")
async def telegram_callback(request: Request):
    data = dict(request.query_params)
    if not verify_telegram_login(data):
        return RedirectResponse("/login?error=1")

    telegram_user_id = int(data["id"])
    async with async_session() as session:
        result = await session.execute(select(Admin).where(Admin.telegram_user_id == telegram_user_id))
        if result.first() is None:
            # Not a recognized group admin yet — they need to run an admin
            # command (e.g. /bwarn) in their group first, see bot/handlers.py.
            return RedirectResponse("/login?error=not_admin")

    response = RedirectResponse("/dashboard")
    response.set_cookie(
        SESSION_COOKIE,
        create_session_cookie(telegram_user_id),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
    )
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login")
    response.delete_cookie(SESSION_COOKIE)
    return response


# --------------------------------------------------------------- dashboard --

@router.get("/dashboard")
async def dashboard_home(request: Request):
    uid = get_current_admin(request)
    if uid is None:
        return RedirectResponse("/login")

    async with async_session() as session:
        result = await session.execute(
            select(Group).join(Admin, Admin.group_id == Group.id).where(Admin.telegram_user_id == uid)
        )
        groups = result.scalars().all()

    return templates.TemplateResponse(request, "dashboard.html", {"groups": groups})


# ------------------------------------------------------------ review queue --

@router.get("/dashboard/{group_id}/queue")
async def review_queue(request: Request, group_id: int):
    uid = get_current_admin(request)
    if uid is None:
        return RedirectResponse("/login")
    if not await has_group_access(uid, group_id):
        return RedirectResponse("/dashboard")

    async with async_session() as session:
        result = await session.execute(
            select(FlaggedMessage)
            .where(FlaggedMessage.group_id == group_id, FlaggedMessage.status == "pending")
            .order_by(FlaggedMessage.created_at.desc())
        )
        flags = result.scalars().all()

    return templates.TemplateResponse(request, "queue.html", {"flags": flags, "group_id": group_id})


@router.post("/dashboard/{group_id}/queue/{flag_id}/{decision}")
async def resolve_flag(request: Request, group_id: int, flag_id: int, decision: str):
    uid = get_current_admin(request)
    if uid is None or not await has_group_access(uid, group_id):
        return RedirectResponse("/login")
    if decision not in ("approve", "dismiss"):
        return RedirectResponse(f"/dashboard/{group_id}/queue")

    new_status = "approved" if decision == "approve" else "dismissed"
    async with async_session() as session:
        flag = await session.get(FlaggedMessage, flag_id)
        if flag and flag.group_id == group_id:
            flag.status = new_status
            await session.commit()

    return RedirectResponse(f"/dashboard/{group_id}/queue", status_code=303)


# ----------------------------------------------------------------- settings --

@router.get("/dashboard/{group_id}/settings")
async def settings_page(request: Request, group_id: int):
    uid = get_current_admin(request)
    if uid is None:
        return RedirectResponse("/login")
    if not await has_group_access(uid, group_id):
        return RedirectResponse("/dashboard")

    async with async_session() as session:
        group = await session.get(Group, group_id)
        result = await session.execute(select(Filter).where(Filter.group_id == group_id))
        filters = result.scalars().all()

    return templates.TemplateResponse(request, "settings.html", {"group": group, "filters": filters})


@router.post("/dashboard/{group_id}/settings")
async def update_settings(request: Request, group_id: int):
    uid = get_current_admin(request)
    if uid is None or not await has_group_access(uid, group_id):
        return RedirectResponse("/login")

    form = await request.form()
    async with async_session() as session:
        group = await session.get(Group, group_id)
        if group:
            group.welcome_message = form.get("welcome_message", group.welcome_message)
            group.rules = form.get("rules", group.rules)
            group.ai_moderation_enabled = "ai_moderation_enabled" in form
            group.purgatory_enabled = "purgatory_enabled" in form
            group.night_mode_enabled = "night_mode_enabled" in form
            try:
                group.warn_limit = max(1, int(form.get("warn_limit", group.warn_limit)))
            except ValueError:
                pass
            try:
                group.slow_mode_seconds = max(0, int(form.get("slow_mode_seconds", group.slow_mode_seconds)))
            except ValueError:
                pass
            await session.commit()

    return RedirectResponse(f"/dashboard/{group_id}/settings", status_code=303)


@router.post("/dashboard/{group_id}/filters/add")
async def add_filter(request: Request, group_id: int):
    uid = get_current_admin(request)
    if uid is None or not await has_group_access(uid, group_id):
        return RedirectResponse("/login")

    form = await request.form()
    filter_type = form.get("type", "word")
    pattern = (form.get("pattern") or "").strip()
    if pattern and filter_type in ("word", "link"):
        async with async_session() as session:
            session.add(Filter(group_id=group_id, type=filter_type, pattern=pattern))
            await session.commit()

    return RedirectResponse(f"/dashboard/{group_id}/settings", status_code=303)


@router.post("/dashboard/{group_id}/filters/{filter_id}/delete")
async def delete_filter(request: Request, group_id: int, filter_id: int):
    uid = get_current_admin(request)
    if uid is None or not await has_group_access(uid, group_id):
        return RedirectResponse("/login")

    async with async_session() as session:
        f = await session.get(Filter, filter_id)
        if f and f.group_id == group_id:
            await session.delete(f)
            await session.commit()

    return RedirectResponse(f"/dashboard/{group_id}/settings", status_code=303)


# ----------------------------------------------------------------- mod log --

@router.get("/dashboard/{group_id}/modlog")
async def modlog_page(request: Request, group_id: int):
    uid = get_current_admin(request)
    if uid is None:
        return RedirectResponse("/login")
    if not await has_group_access(uid, group_id):
        return RedirectResponse("/dashboard")

    async with async_session() as session:
        result = await session.execute(
            select(ModLog).where(ModLog.group_id == group_id).order_by(ModLog.created_at.desc()).limit(200)
        )
        logs = result.scalars().all()

    return templates.TemplateResponse(request, "modlog.html", {"logs": logs})


# ----------------------------------------------------------------- purgatory --

@router.get("/dashboard/{group_id}/purgatory")
async def purgatory_page(request: Request, group_id: int, tab: str = "pending"):
    uid = get_current_admin(request)
    if uid is None:
        return RedirectResponse("/login")
    if not await has_group_access(uid, group_id):
        return RedirectResponse("/dashboard")
    if tab not in PURGATORY_STATUSES:
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

    counts = {status: raw_counts.get(status, 0) for status in PURGATORY_STATUSES}

    return templates.TemplateResponse(
        request,
        "purgatory.html",
        {
            "entries": entries,
            "counts": counts,
            "tab": tab,
            "group_id": group_id,
            "purgatory_enabled": group.purgatory_enabled if group else True,
        },
    )


@router.post("/dashboard/{group_id}/purgatory/toggle")
async def toggle_purgatory(request: Request, group_id: int):
    uid = get_current_admin(request)
    if uid is None or not await has_group_access(uid, group_id):
        return RedirectResponse("/login")

    form = await request.form()
    always_allow = "always_allow" in form
    async with async_session() as session:
        group = await session.get(Group, group_id)
        if group:
            group.purgatory_enabled = not always_allow
            await session.commit()

    return RedirectResponse(f"/dashboard/{group_id}/purgatory", status_code=303)


@router.post("/dashboard/{group_id}/purgatory/{entry_id}/{decision}")
async def decide_purgatory(request: Request, group_id: int, entry_id: int, decision: str, tab: str = "pending"):
    uid = get_current_admin(request)
    if uid is None or not await has_group_access(uid, group_id):
        return RedirectResponse("/login")
    if decision not in ("approve", "deny", "ban"):
        return RedirectResponse(f"/dashboard/{group_id}/purgatory")

    async with async_session() as session:
        entry = await session.get(PurgatoryEntry, entry_id)
    if entry and entry.group_id == group_id:
        await resolve_purgatory_entry(tg_bot, entry, decision, decided_by=uid)

    return RedirectResponse(f"/dashboard/{group_id}/purgatory?tab={tab}", status_code=303)
