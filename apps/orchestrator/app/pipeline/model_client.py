import asyncio
import time
import httpx
from app.core.config import settings


async def call_model(model: str, messages: list[dict], timeout: float = 30.0) -> tuple[str, int]:
    started = time.perf_counter()
    if not settings.openrouter_api_key or settings.openrouter_api_key.startswith("sk-or-"):
        await asyncio.sleep(0.05)
        prompt = messages[-1]["content"] if messages else ""
        return (
            f"[mock:{model}] Candidate answer for: {prompt[:180]}\n\n"
            "Key points:\n"
            "- Preserve QUORUM-FREE and OpenAI compatibility.\n"
            "- Use deterministic fallbacks for malformed JSON or weak consensus.\n"
            "- Keep trace, disagreement, provenance, and $0 marginal cost visible.",
            int((time.perf_counter() - started) * 1000),
        )

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://systemvirtue.local",
        "X-Title": "System Virtue QUORUM",
    }
    payload = {"model": model, "messages": messages, "temperature": 0.2}
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(f"{settings.openrouter_base_url}/chat/completions", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    content = data["choices"][0]["message"]["content"]
    return content, int((time.perf_counter() - started) * 1000)
