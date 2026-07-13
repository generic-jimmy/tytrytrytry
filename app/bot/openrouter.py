import asyncio
import json
import time
from typing import Any

import httpx

from app.config import settings

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ----------------------------------------------------- comprehensive free model list --
# This list is polled IN ORDER on every call. If a model returns 429 (rate
# limited), 5xx, or times out, we move to the next one. The first model
# that succeeds wins — we don't run them in parallel (that would burn the
# rate limit budget faster). Models are ordered roughly by quality + speed.
#
# Update this list periodically from https://openrouter.ai/models?max_price=0
# as new free models appear and old ones get deprecated.

ALL_FREE_MODELS = [
    # OpenRouter's own auto-router — usually most reliable free option
    "openrouter/free",
    # Meta Llama family (large → small)
    "meta-llama/llama-3.3-70b-instruct:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    # OpenAI OSS
    "openai/gpt-oss-20b:free",
    "openai/gpt-oss-120b:free",
    # Google Gemini
    "google/gemini-2.0-flash-exp:free",
    "google/gemini-flash-1.5:free",
    "google/gemma-2-9b-it:free",
    # Mistral
    "mistralai/mistral-small-3.1-24b-instruct:free",
    "mistralai/mistral-nemo:free",
    "mistralai/mistral-7b-instruct:free",
    # Qwen
    "qwen/qwen3-14b:free",
    "qwen/qwen-2.5-7b-instruct:free",
    # DeepSeek
    "deepseek/deepseek-chat-v3-0324:free",
    "deepseek/deepseek-r1:free",
    "deepseek/deepseek-r1-distill-llama-70b:free",
    # Hugging Face / others
    "huggingfaceh4/zephyr-7b-beta:free",
    "teknium/OpenHermes-2.5-Mistral-7B:free",
    "nousresearch/hermes-3-llama-3.1-405b:free",
    "gryphe/mythomax-l2-13b:free",
    # Microsoft
    "microsoft/phi-3-medium-4k-instruct:free",
    "microsoft/phi-3-mini-128k-instruct:free",
    # Liquid AI
    "liquid/lfm-40b:free",
    "liquid/lfm-7b:free",
    # Nvidia
    "nvidia/llama-3.1-nemotron-70b-instruct:free",
    # Perplexity
    "perplexity/llama-3.1-sonar-large-128k-online:free",
]

# Backward-compat: the old name still works, points to the full list.
FALLBACK_MODELS = ALL_FREE_MODELS

# Models exposed in the dashboard's AI configuration picker (shorter list
# of the most popular / reliable free models).
AVAILABLE_MODELS = [
    ("openrouter/free", "OpenRouter Free Router (recommended)"),
    ("meta-llama/llama-3.3-70b-instruct:free", "Llama 3.3 70B (free)"),
    ("openai/gpt-oss-20b:free", "GPT-OSS 20B (free)"),
    ("openai/gpt-oss-120b:free", "GPT-OSS 120B (free)"),
    ("google/gemini-2.0-flash-exp:free", "Gemini 2.0 Flash (free)"),
    ("google/gemini-flash-1.5:free", "Gemini Flash 1.5 (free)"),
    ("mistralai/mistral-small-3.1-24b-instruct:free", "Mistral Small 3.1 (free)"),
    ("qwen/qwen3-14b:free", "Qwen 3 14B (free)"),
    ("deepseek/deepseek-chat-v3-0324:free", "DeepSeek Chat v3 (free)"),
    ("deepseek/deepseek-r1:free", "DeepSeek R1 (free)"),
    ("meta-llama/llama-3.1-8b-instruct:free", "Llama 3.1 8B (free, fast)"),
    ("nvidia/llama-3.1-nemotron-70b-instruct:free", "Nemotron 70B (free)"),
    ("__all_free__", "🔄 Poll ALL free models (auto-fallback)"),
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
    per minute)."""

    def __init__(self, max_calls: int, period_seconds: float):
        self.max_calls = max_calls
        self.period = period_seconds
        self._calls: list[float] = []
        self._lock = asyncio.Lock()
        self.total_calls = 0
        self.total_failures = 0
        # Per-model failure tracking so the dashboard can show which models
        # are currently broken.
        self.model_failures: dict[str, int] = {}
        self.model_successes: dict[str, int] = {}

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
            "model_failures": dict(sorted(self.model_failures.items(), key=lambda x: -x[1])[:10]),
            "model_successes": dict(sorted(self.model_successes.items(), key=lambda x: -x[1])[:10]),
        }


_rate_limiter = RateLimiter(max_calls=15, period_seconds=60)


def rate_limiter_snapshot() -> dict[str, Any]:
    return _rate_limiter.snapshot()


def _resolve_model_list(preferred: str | None) -> list[str]:
    """Returns the list of models to try, in order. If the caller specified
    a single preferred model, we try it first and then fall back through
    the full free-model list. If preferred is None or '__all_free__', we
    just use the full list."""
    if not preferred or preferred == "__all_free__":
        return ALL_FREE_MODELS
    if preferred in ALL_FREE_MODELS:
        # Try preferred first, then the rest as fallback
        return [preferred] + [m for m in ALL_FREE_MODELS if m != preferred]
    # Unknown model — try it first, then fall back
    return [preferred] + ALL_FREE_MODELS


async def _call(messages: list[dict], models: list[str] | None = None, temperature: float = 0.2) -> str:
    """Polls through the model list IN ORDER until one succeeds. The first
    successful response wins. If a model returns 429 (rate limited) we skip
    immediately to the next; if it returns 5xx we skip; if it times out
    (20s) we skip. We only fail if EVERY model fails."""
    await _rate_limiter.acquire()

    model_list = models or ALL_FREE_MODELS
    last_error: Exception | None = None
    last_failed_model: str | None = None

    async with httpx.AsyncClient(timeout=20) as client:
        for model in model_list:
            try:
                resp = await client.post(
                    OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {settings.openrouter_api_key}",
                        "HTTP-Referer": settings.base_url or "https://example.com",
                        "X-Title": "Telegram Group Bot",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                    },
                )
                if resp.status_code == 429:
                    # Rate limited on this model — try the next one
                    _rate_limiter.model_failures[model] = _rate_limiter.model_failures.get(model, 0) + 1
                    _rate_limiter.total_failures += 1
                    last_error = RuntimeError(f"{model}: 429 rate limited")
                    last_failed_model = model
                    continue
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                _rate_limiter.model_successes[model] = _rate_limiter.model_successes.get(model, 0) + 1
                return content
            except (httpx.HTTPError, httpx.TimeoutException, KeyError, IndexError) as exc:
                _rate_limiter.model_failures[model] = _rate_limiter.model_failures.get(model, 0) + 1
                _rate_limiter.total_failures += 1
                last_error = exc
                last_failed_model = model
                continue

    raise RuntimeError(
        f"All {len(model_list)} OpenRouter free models failed. "
        f"Last error on {last_failed_model}: {last_error}"
    )


async def classify_message(text: str, system_prompt: str | None = None, temperature: float = 0.2, model: str | None = None) -> dict:
    """Runs automatically on every message that passes the cheap regex
    filters first. Polls through all free OpenRouter models until one
    succeeds."""
    prompt = system_prompt or DEFAULT_MODERATION_SYSTEM_PROMPT
    models = _resolve_model_list(model)
    raw = await _call(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
        models=models,
        temperature=temperature,
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Model didn't follow the JSON instruction — fail safe to "no action"
        return {"category": "none", "severity": "none", "confidence": 0.0}


async def interpret_admin_instruction(instruction: str) -> dict:
    raw = await _call(
        [
            {"role": "system", "content": NL_ACTION_SYSTEM_PROMPT},
            {"role": "user", "content": instruction},
        ],
        models=ALL_FREE_MODELS,
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"action": "none", "reason": "couldn't parse model output"}


async def admin_tool(prompt: str, system: str = "You are a helpful Telegram group admin assistant.") -> str:
    return await _call(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        models=ALL_FREE_MODELS,
    )


async def test_prompt(user_prompt: str, system_prompt: str, model: str | None = None, temperature: float = 0.2) -> str:
    """Used by the dashboard's AI playground to send an arbitrary prompt
    against a chosen model. Polls through all free models as fallback."""
    models = _resolve_model_list(model)
    return await _call(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        models=models,
        temperature=temperature,
    )


async def ping_openrouter() -> dict[str, Any]:
    """Lightweight reachability check used by the /health endpoint.
    Makes a cheap call to verify the API key works and the service is up.
    Returns {'ok': bool, 'model_used': str, 'latency_ms': int, 'error': str|None}."""
    import time as _time
    start = _time.monotonic()
    try:
        # Use the first reliable free model
        await _call(
            [{"role": "user", "content": "ping"}],
            models=["openrouter/free", "meta-llama/llama-3.3-70b-instruct:free"],
            temperature=0.0,
        )
        latency = int((_time.monotonic() - start) * 1000)
        return {"ok": True, "latency_ms": latency, "error": None}
    except Exception as exc:
        latency = int((_time.monotonic() - start) * 1000)
        return {"ok": False, "latency_ms": latency, "error": str(exc)}
