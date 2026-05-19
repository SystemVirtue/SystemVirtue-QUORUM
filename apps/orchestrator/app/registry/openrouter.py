import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import httpx
from app.core.config import settings
from app.core.schemas import FreeModel, ModelCapabilities, ModelTelemetry


class FreeModelRegistry:
    FULL_REFRESH_TTL = 21_600
    HEALTH_CHECK_TTL = 900
    CACHE_TTL = 600
    REPUTABLE_NAMESPACES = (
        "meta-llama/", "qwen/", "deepseek/", "mistralai/",
        "google/", "nvidia/", "microsoft/", "anthropic/",
        "openai/", "x-ai/", "cohere/", "01-ai/",
        "nous-research/", "openrouter/",
    )

    def __init__(self) -> None:
        self._cache: list[FreeModel] | None = None

    async def refresh(self) -> list[FreeModel]:
        if not settings.openrouter_api_key or settings.openrouter_api_key == "sk-or-your-key-here":
            self._cache = self.seed_pool()
            return self._cache

        headers = {"Authorization": f"Bearer {settings.openrouter_api_key}"}
        async with httpx.AsyncClient(timeout=20) as client:
            data = (await client.get(f"{settings.openrouter_base_url}/models", headers=headers)).json()["data"]
        free = [
            m for m in data
            if float(m.get("pricing", {}).get("prompt", 1)) == 0
            and float(m.get("pricing", {}).get("completion", 1)) == 0
            and int(m.get("context_length", 0)) >= 8192
            and str(m.get("id", "")).endswith(":free")
            and any(m["id"].startswith(p) for p in self.REPUTABLE_NAMESPACES)
        ]
        self._cache = [await self._enrich(m) for m in free]
        return self._cache

    async def list_free(self) -> list[FreeModel]:
        if self._cache is None:
            return await self.refresh()
        return self._cache

    async def _enrich(self, raw: dict[str, Any]) -> FreeModel:
        model_id = raw["id"]
        family = model_id.split(":")[0].split("/")[-1].replace("-instruct", "")
        seed = self._seed_for(model_id)
        telemetry = ModelTelemetry()
        health = compute_health(telemetry, int(raw.get("context_length", 0)), 8192)
        return FreeModel(
            id=model_id,
            family=family,
            context_length=int(raw.get("context_length", 8192)),
            supports_json_mode=True,
            supports_tools=False,
            capabilities=seed,
            telemetry=telemetry,
            health_score=health,
            last_verified=datetime.now(timezone.utc).isoformat(),
        )

    def _seed_for(self, model_id: str) -> ModelCapabilities:
        path = Path(__file__).resolve().parents[4] / "seed" / "seed_capability_scores.json"
        if path.exists():
            data = json.loads(path.read_text())
            for prefix, caps in data.items():
                if model_id.startswith(prefix):
                    return ModelCapabilities.model_validate(caps)
        model_class = "coder" if any(k in model_id for k in ("coder", "deepseek", "qwen")) else "generalist"
        return ModelCapabilities(
            coding_strength={"python": 7.0, "typescript": 7.0, "javascript": 7.0, "rust": 6.0, "go": 6.5, "sql": 6.5, "general": 6.8},
            reasoning=7.0, math=6.0, long_context=6.5, tool_use=5.5, critique=6.5,
            synthesis=6.5, json_reliability=7.0, model_class=model_class,
            generic={"coding": 6.8, "reasoning": 7.0, "critique": 6.5, "synthesis": 6.5, "json_reliability": 7.0, "long_context": 6.5},
        )

    def seed_pool(self) -> list[FreeModel]:
        ids = [
            "deepseek/deepseek-chat-v3:free",
            "qwen/qwen-2.5-coder-32b:free",
            "meta-llama/llama-3.3-70b-instruct:free",
            "google/gemini-2.0-flash-exp:free",
            "mistralai/mistral-7b-instruct:free",
            "openrouter/auto:free",
        ]
        return [
            FreeModel(id=i, family=i.split("/")[1].split(":")[0].replace("-instruct", ""), context_length=32768,
                      supports_json_mode=True, capabilities=self._seed_for(i),
                      health_score=compute_health(ModelTelemetry(), 32768, 8192),
                      last_verified=datetime.now(timezone.utc).isoformat())
            for i in ids
        ]


def compute_health(telemetry: ModelTelemetry, context_length: int, min_required: int) -> float:
    latency_score = 1 - min(1, telemetry.p50_latency_ms / 15000)
    output_stability = 1 - telemetry.malformed_json_rate_24h
    context_score = 1.0 if context_length >= min_required else 0.3
    return round(
        0.30 * telemetry.availability_24h
        + 0.25 * telemetry.recent_success_rate
        + 0.20 * latency_score
        + 0.15 * output_stability
        + 0.10 * context_score,
        4,
    )
