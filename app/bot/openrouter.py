import asyncio
import json
import time
from typing import Any

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

# Models exposed in the dashboard's AI configuration picker.
AVAILABLE_MODELS = [
    ("meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B (free)"),
    ("openai/gpt-oss-20b:free", "GPT-OSS 20B (free)"),
    ("openrouter/free", "OpenRouter Free Router"),
    ("google/gemini-2.0-flash-exp:free", "Gemini 2.0 Flash (free)"),
    ("mistralai/mistral-small-3.1-24b-instruct:free", "Mistral Small 3.1 (free)"),
    ("qwen/qwen3-14b:free", "Qwen 3 14B (free)"),
    ("deepseek/deepseek-chat-v3-0324:free", "DeepSeek Chat v3 (free)"),
    ("meta-llama/llama-3.1-8b-instruct:free", "Llama 3.1 8B (free)"),
]

DEFAULT_MODERATION_SYSTEM_PROMPT = """You moderate messages in a Telegram group chat. \
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
        # Light stats so the dashboard can show "AI calls in the last minute".
        self.total_calls = 0
        self.total_failures = 0

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
            self.total_calls += 1

    def snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        recent = sum(1 for t in self._calls if now - t < self.period)
        return {
            "calls_last_period": recent,
            "max_per_period": self.max_calls,
            "period_seconds": self.period,
            "total_calls": self.total_calls,
            "total_failures": self.total_failures,
        }


# Stays comfortably under the ~20 req/min ceiling most free OpenRouter models
# share. Tune this if you confirm a different limit for the models you use.
_rate_limiter = RateLimiter(max_calls=15, period_seconds=60)


def rate_limiter_snapshot() -> dict[str, Any]:
    return _rate_limiter.snapshot()


async def _call(messages: list[dict], models: list[str] = FALLBACK_MODELS, temperature: float = 0.2) -> str:
    await _rate_limiter.acquire()

    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=20) as client:
        for model in models:
            try:
                resp = await client.post(
                    OPENROUTER_URL,
                    headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
                    json={"model": model, "messages": messages, "temperature": temperature},
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as exc:  # noqa: BLE001 — deliberately broad, we fall back
                last_error = exc
                _rate_limiter.total_failures += 1
                continue
    raise RuntimeError(f"All OpenRouter models failed: {last_error}")


async def classify_message(text: str, system_prompt: str | None = None, temperature: float = 0.2) -> dict:
    """Runs automatically on every message that passes the cheap regex
    filters first (see bot/moderation.py) — kept for the ambiguous cases
    only, given free-model rate limits."""
    prompt = system_prompt or DEFAULT_MODERATION_SYSTEM_PROMPT
    raw = await _call(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        temperature=temperature,
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


async def test_prompt(user_prompt: str, system_prompt: str, model: str | None = None, temperature: float = 0.2) -> str:
    """Used by the dashboard's AI playground to send an arbitrary prompt
    against a chosen model and return the raw text. Falls back through the
    default model list if the chosen model fails."""
    models = [model] if model else FALLBACK_MODELS
    if model and model not in FALLBACK_MODELS:
        # If the chosen model isn't in the free list, still try it first
        # but fall back to the free list afterwards.
        models = [model] + FALLBACK_MODELS
    return await _call(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        models=models,
        temperature=temperature,
    )
