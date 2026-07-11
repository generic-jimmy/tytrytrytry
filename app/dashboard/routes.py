from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.auth import SESSION_COOKIE, create_session_cookie, read_session_cookie, verify_telegram_login
from app.dashboard.api import router as api_router
from app.config import settings
from app.db import async_session
from app.models import Admin, Group

router = APIRouter()
router.include_router(api_router)

templates = Jinja2Templates(directory="app/dashboard/templates")


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
    display_name = data.get("first_name") or data.get("username") or ""
    async with async_session() as session:
        result = await session.execute(select(Admin).where(Admin.telegram_user_id == telegram_user_id))
        admin = result.scalar_one_or_none()
        if admin is None:
            return RedirectResponse("/login?error=not_admin")
        if display_name and admin.display_name != display_name:
            admin.display_name = display_name
            await session.commit()

    response = RedirectResponse("/app")
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


# ------------------------------------------------------- SPA shell route --
# The entire upgraded UI lives in a single index.html loaded at /app —
# the JavaScript router picks the view based on the URL hash.

@router.get("/app")
async def spa_shell(request: Request):
    uid = get_current_admin(request)
    if uid is None:
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "index.html", {"bot_username": settings.telegram_bot_username})


@router.get("/app/{rest:path}")
async def spa_shell_deep(request: Request, rest: str = ""):
    uid = get_current_admin(request)
    if uid is None:
        return RedirectResponse("/login")
    return templates.TemplateResponse(request, "index.html", {"bot_username": settings.telegram_bot_username})


# ---------------------------------------------------------------- legacy --
# Keep the original server-rendered pages around as a fallback. They use the
# old templates under templates/legacy/ and the same data layer. Useful if
# anyone has the old URLs bookmarked.

@router.get("/dashboard")
async def dashboard_legacy(request: Request):
    uid = get_current_admin(request)
    if uid is None:
        return RedirectResponse("/login")

    async with async_session() as session:
        result = await session.execute(
            select(Group).join(Admin, Admin.group_id == Group.id).where(Admin.telegram_user_id == uid)
        )
        groups = result.scalars().all()

    return templates.TemplateResponse(request, "dashboard.html", {"groups": groups})
