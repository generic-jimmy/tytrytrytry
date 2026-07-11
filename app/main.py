from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from app.bot import bot, dp
from app.bot.handlers import start_scheduler, stop_scheduler
from app.config import settings
from app.dashboard.routes import router as dashboard_router
from app.db import init_models


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_models()
    webhook_url = f"{settings.base_url}/webhook/{settings.webhook_secret}"
    await bot.set_webhook(webhook_url, drop_pending_updates=True)
    start_scheduler(bot)
    try:
        yield
    finally:
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
    return {"status": "bot running", "dashboard": "/login"}


@app.post("/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if secret != settings.webhook_secret:
        return Response(status_code=404)
    update = Update.model_validate(await request.json())
    await dp.feed_webhook_update(bot, update)
    return Response(status_code=200)
