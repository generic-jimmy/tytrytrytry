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
    try:
        async with async_session() as session:
            result = await session.execute(select(Admin).where(Admin.telegram_user_id == telegram_user_id))
            admin = result.scalar_one_or_none()
            if admin is None:
                return RedirectResponse("/login?error=not_admin")
            # display_name is a new column added by the lightweight migration
            # in db.py — guard against it still being missing on a freshly
            # upgraded deployment that hasn't run init_models() yet.
            if display_name and getattr(admin, "display_name", "") != display_name:
                admin.display_name = display_name
                await session.commit()
    except Exception as exc:
        # Surface schema/DB errors with a useful message instead of a raw 500.
        # The most common cause is a stale DB schema — the lightweight
        # migration in db.py runs on boot and should fix this, but if the
        # container restarted mid-flight, route the user to a clear error.
        import logging
        logging.exception("DB error during telegram auth callback")
        return RedirectResponse(f"/login?error=db&msg={str(exc)[:200]}")

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


# --------------------------------------------------------------- debug --
# Diagnostic endpoints for troubleshooting "bot doesn't respond" issues.
# All require admin session (same as the rest of the dashboard). The HTML
# page at /debug renders everything in one readable view; the JSON endpoints
# under /api/debug/* are for programmatic access or curl.

async def _require_admin_or_redirect(request: Request) -> int | None:
    uid = get_current_admin(request)
    return uid


@router.get("/debug")
async def debug_page(request: Request):
    uid = await _require_admin_or_redirect(request)
    if uid is None:
        return RedirectResponse("/login?error=1&next=/debug")
    return templates.TemplateResponse(request, "debug.html", {})


@router.get("/api/debug/webhook")
async def debug_webhook(request: Request):
    """Returns what Telegram thinks the webhook is, plus the local config.
    The key field is last_error_message — if Telegram has been failing to
    deliver updates, that's where it tells you why."""
    uid = await _require_admin_or_redirect(request)
    if uid is None:
        return RedirectResponse("/login", status_code=302)
    from app.bot import bot as tg_bot
    try:
        info = await tg_bot.get_webhook_info()
        return {
            "configured_url": f"{settings.base_url}/webhook/{settings.webhook_secret}",
            "telegram_webhook": {
                "url": info.url,
                "has_custom_certificate": info.has_custom_certificate,
                "pending_update_count": info.pending_update_count,
                "last_error_date": info.last_error_date,
                "last_error_message": info.last_error_message,
                "max_connections": info.max_connections,
                "allowed_updates": info.allowed_updates,
            },
            "base_url_env": settings.base_url,
            "webhook_secret_env": settings.webhook_secret[:8] + "…" if settings.webhook_secret else "MISSING",
            "match": info.url == f"{settings.base_url}/webhook/{settings.webhook_secret}",
        }
    except Exception as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}


@router.post("/api/debug/refresh-webhook")
async def debug_refresh_webhook(request: Request):
    """Manually re-registers the webhook with Telegram using the current
    BASE_URL. Useful if BASE_URL was wrong on boot or the domain changed
    after deploy."""
    uid = await _require_admin_or_redirect(request)
    if uid is None:
        return RedirectResponse("/login", status_code=302)
    from app.bot import bot as tg_bot
    import logging
    log = logging.getLogger("telegram_bot")
    webhook_url = f"{settings.base_url}/webhook/{settings.webhook_secret}"
    log.info("Manual webhook refresh → %s", webhook_url)
    try:
        await tg_bot.set_webhook(webhook_url, drop_pending_updates=False)
        info = await tg_bot.get_webhook_info()
        return {
            "ok": True,
            "registered_url": webhook_url,
            "telegram_confirms_url": info.url,
            "match": info.url == webhook_url,
            "pending_updates": info.pending_update_count,
        }
    except Exception as exc:
        log.exception("Manual webhook refresh failed")
        return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}


@router.get("/api/debug/bot-info")
async def debug_bot_info(request: Request):
    """Calls bot.get_me() — verifies the token is valid and the bot exists.
    If this fails, the token is wrong or revoked."""
    uid = await _require_admin_or_redirect(request)
    if uid is None:
        return RedirectResponse("/login", status_code=302)
    from app.bot import bot as tg_bot
    try:
        me = await tg_bot.get_me()
        return {
            "ok": True,
            "bot": {
                "id": me.id,
                "username": me.username,
                "first_name": me.first_name,
                "can_join_groups": me.can_join_groups,
                "can_read_all_group_messages": me.can_read_all_group_messages,
                "supports_inline_queries": me.supports_inline_queries,
            },
            "note": (
                "can_read_all_group_messages must be True for the bot to see "
                "non-command messages in groups. If False, disable privacy "
                "mode via @BotFather /setprivacy."
            ),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_type": type(exc).__name__}


@router.post("/api/debug/test-message")
async def debug_test_message(request: Request, group_id: int = 0):
    """Sends a test message to a group the admin has access to, to verify
    the bot can post. Query param: ?group_id=123. If omitted, picks the
    first group the admin manages."""
    uid = await _require_admin_or_redirect(request)
    if uid is None:
        return RedirectResponse("/login", status_code=302)
    from app.bot import bot as tg_bot
    from app.db import async_session
    target_gid = group_id
    if target_gid == 0:
        async with async_session() as session:
            result = await session.execute(
                select(Admin).where(Admin.telegram_user_id == uid)
            )
            admin = result.scalars().first()
            if admin is None:
                return {"ok": False, "error": "You have no groups to test with."}
            target_gid = admin.group_id
    try:
        await tg_bot.send_message(target_gid, "🤖 Test message from the debug panel — the bot can post to this group.")
        return {"ok": True, "sent_to": target_gid}
    except Exception as exc:
        return {"ok": False, "error": str(exc), "error_type": type(exc).__name__, "group_id": target_gid}
