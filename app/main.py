import logging
from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from app.bot import bot, dp
from app.bot.handlers import start_scheduler, stop_scheduler
from app.config import settings
from app.dashboard.routes import router as dashboard_router
from app.db import init_models

logger = logging.getLogger("telegram_bot")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- DB schema: create missing tables + add missing columns to
    # pre-existing tables. Safe to run on every boot.
    logger.info("Starting init_models() — creating tables + running migrations…")
    try:
        await init_models()
        logger.info("init_models() completed successfully")
    except Exception:
        logger.exception("init_models() FAILED — schema may be incomplete")
        raise

    # --- Telegram webhook registration. This is the #1 cause of "bot
    # doesn't respond" issues — if BASE_URL is wrong or the cert is
    # invalid, Telegram silently stops sending updates and there are
    # zero server logs. Log the result explicitly so it's visible.
    webhook_url = f"{settings.base_url}/webhook/{settings.webhook_secret}"
    logger.info("Registering Telegram webhook → %s", webhook_url)
    try:
        result = await bot.set_webhook(webhook_url, drop_pending_updates=True)
        if result:
            logger.info("✓ Webhook registered successfully with Telegram")
        else:
            logger.warning("⚠ set_webhook returned False — Telegram may not have accepted it")
        # Verify by reading back what Telegram thinks the webhook is.
        info = await bot.get_webhook_info()
        logger.info(
            "Telegram webhook status: url=%s, pending_updates=%d, last_error=%s",
            info.url,
            info.pending_update_count,
            info.last_error_message or "none",
        )
    except Exception:
        logger.exception("FAILED to set Telegram webhook — bot will NOT receive updates!")
        raise

    start_scheduler(bot)
    logger.info("Bot fully started. Dashboard at /app, health at /health, debug at /debug")
    try:
        yield
    finally:
        logger.info("Shutting down — deleting webhook, closing sessions…")
        stop_scheduler()
        await bot.delete_webhook()
        await bot.session.close()


app = FastAPI(lifespan=lifespan)
app.include_router(dashboard_router)
app.mount("/static", StaticFiles(directory="app/dashboard/static"), name="static")


@app.get("/health")
async def health():
    """Expanded health check — verifies every external dependency the bot
    relies on. Used by uptime monitors (UptimeRobot, BetterStack, etc.)
    and the dashboard's System Health view.

    Returns 503 if any critical dependency is down, 200 if all healthy."""
    import time as _time
    from app.db import engine
    from sqlalchemy import text as sa_text

    checks = {}
    overall_ok = True

    # --- Database
    db_start = _time.monotonic()
    try:
        async with engine.connect() as conn:
            await conn.execute(sa_text("SELECT 1"))
        checks["database"] = {
            "ok": True,
            "latency_ms": int((_time.monotonic() - db_start) * 1000),
        }
    except Exception as e:
        checks["database"] = {"ok": False, "error": str(e)}
        overall_ok = False

    # --- Telegram API (bot.get_me — cheap call)
    tg_start = _time.monotonic()
    try:
        me = await bot.get_me()
        checks["telegram_api"] = {
            "ok": True,
            "latency_ms": int((_time.monotonic() - tg_start) * 1000),
            "bot_username": me.username,
        }
    except Exception as e:
        checks["telegram_api"] = {"ok": False, "error": str(e)}
        overall_ok = False

    # --- OpenRouter API (lightweight ping)
    try:
        from app.bot.openrouter import ping_openrouter
        or_result = await ping_openrouter()
        checks["openrouter"] = or_result
        if not or_result.get("ok"):
            overall_ok = False
    except Exception as e:
        checks["openrouter"] = {"ok": False, "error": str(e)}
        # Don't mark overall as down for OpenRouter — moderation still
        # works on regex filters, just no AI classification.
        checks["openrouter"]["degraded_only"] = True

    # --- Scheduled task liveness
    try:
        from app.bot.handlers import _scheduler_task
        scheduler_alive = _scheduler_task is not None and not _scheduler_task.done()
        checks["scheduler"] = {"ok": scheduler_alive, "task_alive": scheduler_alive}
        if not scheduler_alive:
            overall_ok = False
    except Exception as e:
        checks["scheduler"] = {"ok": False, "error": str(e)}
        overall_ok = False

    # --- Webhook registration status (cached from boot)
    try:
        info = await bot.get_webhook_info()
        checks["webhook"] = {
            "ok": bool(info.url),
            "url": info.url,
            "pending_updates": info.pending_update_count,
            "last_error": info.last_error_message,
        }
        if not info.url or info.last_error_message:
            # Don't fail overall health just for webhook warnings —
            # surface them but stay 200 so the monitor doesn't flap.
            checks["webhook"]["warning"] = True
    except Exception as e:
        checks["webhook"] = {"ok": False, "error": str(e)}

    # --- System metrics
    from app.bot.moderation import system_health
    checks["system"] = system_health()

    # --- WebSocket subscriber count
    try:
        from app.events import subscriber_count
        checks["websockets"] = {"active_subscribers": subscriber_count(0)}  # 0 = sum all? actually per-group
    except Exception:
        pass

    status_code = 200 if overall_ok else 503
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ok" if overall_ok else "degraded",
            "checks": checks,
            "timestamp": _time.time(),
        },
    )


@app.get("/")
async def root():
    return {"status": "bot running", "dashboard": "/login", "debug": "/debug"}


@app.post("/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if secret != settings.webhook_secret:
        # Don't log at INFO level — Telegram probes webhooks periodically
        # and this would be noisy. Log at DEBUG instead.
        logger.debug("Webhook called with wrong secret — ignoring")
        return Response(status_code=404)
    try:
        payload = await request.json()
        update = Update.model_validate(payload)
        await dp.feed_webhook_update(bot, update)
    except Exception:
        # This is the critical log — if the webhook IS being hit but
        # commands aren't working, the error will be here.
        logger.exception("Webhook handler error — update processing failed")
        return Response(status_code=200)  # return 200 so Telegram doesn't retry endlessly
    return Response(status_code=200)
