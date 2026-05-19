import asyncio
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


OPENROUTER_URL = "https://openrouter.ai/api/v1"
REPUTABLE_NAMESPACES = (
    "meta-llama/", "qwen/", "deepseek/", "mistralai/",
    "google/", "nvidia/", "microsoft/", "anthropic/",
    "openai/", "x-ai/", "cohere/", "01-ai/",
    "nous-research/", "openrouter/",
)
SMOKE_PROMPT = "Smoke test only. Reply with exactly: QUORUM_FREE_OK"
EXPECTED = "QUORUM_FREE_OK"


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def is_free_model(model: dict[str, Any]) -> bool:
    pricing = model.get("pricing", {})
    return (
        float(pricing.get("prompt", 1)) == 0
        and float(pricing.get("completion", 1)) == 0
        and int(model.get("context_length", 0)) >= 8192
        and str(model.get("id", "")).endswith(":free")
    )


def preferred_score(model_id: str) -> tuple[int, str]:
    order = {
        "deepseek/": 0,
        "qwen/": 1,
        "google/": 2,
        "nvidia/": 3,
        "meta-llama/": 4,
        "mistralai/": 5,
        "openrouter/": 6,
    }
    rank = min((score for prefix, score in order.items() if model_id.startswith(prefix)), default=20)
    return rank, model_id


def family_key(model_id: str) -> str:
    provider, _, rest = model_id.partition("/")
    family = rest.split(":")[0].split("-")[0] if rest else provider
    return f"{provider}/{family}"


def diverse_candidates(models: list[dict[str, Any]]) -> list[dict[str, Any]]:
    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    for model in models:
        key = family_key(model["id"])
        if key in used:
            continue
        chosen.append(model)
        used.add(key)
    for model in models:
        if model not in chosen:
            chosen.append(model)
    return chosen


async def fetch_free_models(client: httpx.AsyncClient, key: str) -> list[dict[str, Any]]:
    response = await client.get(f"{OPENROUTER_URL}/models", headers={"Authorization": f"Bearer {key}"})
    response.raise_for_status()
    models = response.json()["data"]
    return sorted(
        [m for m in models if is_free_model(m) and any(m["id"].startswith(p) for p in REPUTABLE_NAMESPACES)],
        key=lambda m: preferred_score(m["id"]),
    )


async def call_free_model(client: httpx.AsyncClient, key: str, model: dict[str, Any]) -> dict[str, Any]:
    if not is_free_model(model):
        raise RuntimeError(f"Blocked non-free model before call: {model.get('id')}")

    started = time.perf_counter()
    payload = {
        "model": model["id"],
        "messages": [{"role": "user", "content": SMOKE_PROMPT}],
        "max_tokens": 20,
        "temperature": 0,
    }
    response = await client.post(
        f"{OPENROUTER_URL}/chat/completions",
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://systemvirtue.local",
            "X-Title": "System Virtue QUORUM Free Smoke",
        },
        json=payload,
    )
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
    usage = data.get("usage", {})
    cost = usage.get("cost", usage.get("cost_details", {}).get("upstream_inference_cost", 0))
    return {
        "requested_model": model["id"],
        "returned_model": data.get("model"),
        "ok": response.status_code == 200 and EXPECTED in content and float(cost or 0) == 0,
        "status_code": response.status_code,
        "latency_ms": elapsed_ms,
        "content": content,
        "cost": cost,
        "usage": usage,
    }


async def main() -> int:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key or key == "sk-or-your-key-here":
        print("OPENROUTER_API_KEY is missing", file=sys.stderr)
        return 2
    if os.environ.get("ALLOW_PAID_MODELS", "false").lower() != "false":
        print("Refusing to run: ALLOW_PAID_MODELS must be false for free smoke benchmark", file=sys.stderr)
        return 2

    async with httpx.AsyncClient(timeout=45) as client:
        free_models = await fetch_free_models(client, key)
        candidates = diverse_candidates(free_models)
        if len(candidates) < 2:
            print("Not enough reputable free models discovered", file=sys.stderr)
            return 3
        selected = []
        results = []
        for model in candidates[:8]:
            selected.append(model)
            result = await call_free_model(client, key, model)
            results.append(result)
            if sum(1 for item in results if item["ok"]) >= 3:
                break
            if len(results) >= 5 and sum(1 for item in results if item["ok"]) >= 2:
                break

    quorum_ok = sum(1 for result in results if result["ok"]) >= 2
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": "free_smoke",
        "free_pool_count": len(free_models),
        "attempted_models": [m["id"] for m in selected],
        "individual_results": results,
        "quorum_free_fast": {
            "minimum_viable_quorum": "2 of 3",
            "minimum_viable_quorum_met": quorum_ok,
            "successful_members": sum(1 for result in results if result["ok"]),
            "marginal_cost_usd": 0.0,
            "wall_clock_ms": max(result["latency_ms"] for result in results),
        },
    }
    out_dir = root / "benchmarks" / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"free_smoke_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    out_file.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"wrote={out_file}")
    return 0 if quorum_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
