import asyncio
import json
import time

import httpx

from app.config import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Free-tier models to try in order. This list rotates on OpenRouter's end —
# check https://openrouter.ai/models?max_price=0 periodically and update it.
# "openrouter/free" is OpenRouter's own auto-router and is kept last since it
# picks whatever free model is currently available, as a final catch-all.
FALLBACK_MODELS = [
    "meta-llama/llama-3.3-70b-instruct:free",
    "openai/gpt-oss-20b:free",
    "openrouter/free",
]

MODERATION_SYSTEM_PROMPT = """You moderate messages in a Telegram group chat. \
Respond with ONLY a JSON object, no other text, no markdown fences:
{"category": "none|spam|toxicity|threat|scam_link|other", \
"severity": "none|low|medium|high", "confidence": 0.0-1.0}

"severity": "high" means immediate automatic action is warranted \
(hate speech, threats, doxxing, scam or phishing links). \
"medium" or "low" means it should be queued for a human admin to review \
instead of acted on automatically. \
"none" means the message is fine."""

NL_ACTION_SYSTEM_PROMPT = """You interpret a Telegram group admin's plain-English \
instruction about one specific user into a moderation action. Respond with \
ONLY a JSON object, no other text:
{"action": "warn|mute|kick|ban|none", "reason": "short reason"}
Choose "none" if the instruction doesn't call for a moderation action."""


class RateLimiter:
    """Sliding-window limiter so bursts of group messages don't blow through
    OpenRouter's free-tier cap (most free models allow roughly 20 requests
    per minute). Shared across every call this process makes — auto-mod and
    admin tools draw from the same budget."""

    def __init__(self, max_calls: int, period_seconds: float):
        self.max_calls = max_calls
        self.period = period_seconds
        self._calls: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self._calls = [t for t in self._calls if now - t < self.period]
            if len(self._calls) >= self.max_calls:
                wait = self.period - (now - self._calls[0])
                if wait > 0:
                    await asyncio.sleep(wait)
                now = time.monotonic()
                self._calls = [t for t in self._calls if now - t < self.period]
            self._calls.append(time.monotonic())


# Stays comfortably under the ~20 req/min ceiling most free OpenRouter models
# share. Tune this if you confirm a different limit for the models you use.
_rate_limiter = RateLimiter(max_calls=15, period_seconds=60)


async def _call(messages: list[dict], models: list[str] = FALLBACK_MODELS) -> str:
    await _rate_limiter.acquire()

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=20) as client:
        for model in models:
            try:
                resp = await client.post(
                    OPENROUTER_URL,
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                    json={"model": model, "messages": messages},
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as exc:  # noqa: BLE001 — deliberately broad, we fall back
                last_error = exc
                continue
    raise RuntimeError(f"All OpenRouter models failed: {last_error}")


async def classify_message(text: str) -> dict:
    """Runs automatically on every message that passes the cheap regex
    filters first (see bot/moderation.py) — kept for the ambiguous cases
    only, given free-model rate limits."""
    raw = await _call(
        [
            {"role": "system", "content": MODERATION_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Model didn't follow the JSON instruction — fail safe to "no
        # action". Never fail safe to auto-banning someone on a parse error.
        return {"category": "none", "severity": "none", "confidence": 0.0}


async def interpret_admin_instruction(instruction: str) -> dict:
    """Backs /bai — turns a plain-English admin instruction into a
    structured action. Callers must check admin status before calling this."""
    raw = await _call(
        [
            {"role": "system", "content": NL_ACTION_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ]
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"action": "none", "reason": "couldn't parse model output"}


async def admin_tool(prompt: str, system: str = "You are a helpful Telegram group admin assistant.") -> str:
    """For admin-triggered tools only: /bsummarize, welcome-message
    generation. Callers are responsible for checking admin status before
    calling this — see bot/handlers.py."""
    return await _call(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
    )
