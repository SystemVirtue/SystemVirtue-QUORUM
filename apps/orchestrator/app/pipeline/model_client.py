import asyncio
import time
import httpx
from app.core.config import settings

FREE_MODEL_CACHE_TTL_SECONDS = 600
_free_model_cache: set[str] | None = None
_free_model_cache_checked_at = 0.0


class ModelCallError(Exception):
    def __init__(self, reason: str, status_code: int | None = None, latency_ms: int = 0, cost: float = 0.0) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code
        self.latency_ms = latency_ms
        self.cost = cost


def is_placeholder_key(key: str | None) -> bool:
    return not key or key in {"sk-or-your-key-here", ""}


def enforce_free_model(model: str) -> None:
    if settings.allow_paid_models:
        return
    if model == "openrouter/free":
        return
    if not model.endswith(":free"):
        raise ModelCallError(f"blocked_non_free_model:{model}")


async def validate_openrouter_free_model(model: str, client: httpx.AsyncClient) -> None:
    global _free_model_cache, _free_model_cache_checked_at
    if settings.allow_paid_models or model == "openrouter/free":
        return
    now = time.monotonic()
    if _free_model_cache is None or now - _free_model_cache_checked_at > FREE_MODEL_CACHE_TTL_SECONDS:
        response = await client.get(
            f"{settings.openrouter_base_url}/models",
            headers={"Authorization": f"Bearer {settings.openrouter_api_key}"},
        )
        if response.status_code != 200:
            raise ModelCallError("free_model_pricing_validation_failed", response.status_code)
        data = response.json().get("data", [])
        _free_model_cache = {
            item["id"]
            for item in data
            if float(item.get("pricing", {}).get("prompt", 1)) == 0
            and float(item.get("pricing", {}).get("completion", 1)) == 0
            and str(item.get("id", "")).endswith(":free")
        }
        _free_model_cache_checked_at = now
    if model not in _free_model_cache:
        raise ModelCallError(f"blocked_model_not_in_live_free_pool:{model}")


async def call_model(model: str, messages: list[dict], timeout: float = 30.0, max_tokens: int | None = None) -> tuple[str, int, float, dict]:
    started = time.perf_counter()
    enforce_free_model(model)
    if is_placeholder_key(settings.openrouter_api_key):
        await asyncio.sleep(0.05)
        prompt = messages[-1]["content"] if messages else ""
        return (
            f"[mock:{model}] Candidate answer for: {prompt[:180]}\n\n"
            "Key points:\n"
            "- Preserve QUORUM-FREE and OpenAI compatibility.\n"
            "- Use deterministic fallbacks for malformed JSON or weak consensus.\n"
            "- Keep trace, disagreement, provenance, and $0 marginal cost visible.",
            int((time.perf_counter() - started) * 1000),
            0.0,
            {"mock": True},
        )

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://systemvirtue.local",
        "X-Title": "System Virtue QUORUM",
    }
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    async with httpx.AsyncClient(timeout=timeout) as client:
        await validate_openrouter_free_model(model, client)
        response = await client.post(f"{settings.openrouter_base_url}/chat/completions", json=payload, headers=headers)
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        usage = data.get("usage", {})
        cost = float(usage.get("cost", usage.get("cost_details", {}).get("upstream_inference_cost", 0)) or 0)
        if response.status_code == 429:
            raise ModelCallError("rate_limit", response.status_code, latency_ms, cost)
        if response.status_code >= 500:
            raise ModelCallError("provider_error", response.status_code, latency_ms, cost)
        if response.status_code != 200:
            raise ModelCallError(f"http_{response.status_code}", response.status_code, latency_ms, cost)
        if not settings.allow_paid_models and cost != 0:
            raise ModelCallError("nonzero_cost_reported", response.status_code, latency_ms, cost)
        content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
        if not content.strip():
            raise ModelCallError("empty_output", response.status_code, latency_ms, cost)
    return content, latency_ms, cost, usage
