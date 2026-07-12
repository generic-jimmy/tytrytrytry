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
    return {"status": "ok"}


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
