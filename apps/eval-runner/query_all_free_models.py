import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


OPENROUTER_URL = "https://openrouter.ai/api/v1"
PROMPT = "Free-tier census probe. Reply with exactly: SV_FREE_OK"
EXPECTED = "SV_FREE_OK"
REASONING_MARKERS = ("thinking", "reasoning", "reasoner", "r1", "o1", "o3", "glm-4.5")


class RequestPacer:
    def __init__(self, spacing_seconds: float) -> None:
        self.spacing_seconds = max(0.0, spacing_seconds)
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        if self.spacing_seconds <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            if now < self._next_at:
                await asyncio.sleep(self._next_at - now)
            self._next_at = time.monotonic() + self.spacing_seconds


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
        and str(model.get("id", "")).endswith(":free")
    )


def provider(model_id: str) -> str:
    return model_id.split("/", 1)[0] if "/" in model_id else "unknown"


def is_reasoning_model(model: dict[str, Any]) -> bool:
    model_id = str(model.get("id", "")).lower()
    name = str(model.get("name", "")).lower()
    description = str(model.get("description", "")).lower()
    return any(marker in value for marker in REASONING_MARKERS for value in (model_id, name, description))


def provider_max_tokens(model: dict[str, Any]) -> int | None:
    top_provider = model.get("top_provider") or {}
    value = top_provider.get("max_completion_tokens") or top_provider.get("max_output_tokens")
    try:
        provider_limit = int(value) if value else None
    except (TypeError, ValueError):
        return None
    try:
        context_safe_limit = int(model.get("context_length", 0)) - 1024
    except (TypeError, ValueError):
        context_safe_limit = 0
    if context_safe_limit > 0:
        provider_limit = min(provider_limit, context_safe_limit) if provider_limit else context_safe_limit
    return provider_limit


def max_tokens_for_model(model: dict[str, Any], standard_max_tokens: int, reasoning_max_tokens: int) -> int:
    provider_limit = provider_max_tokens(model)
    if is_reasoning_model(model):
        if provider_limit:
            return provider_limit if reasoning_max_tokens <= 0 else min(reasoning_max_tokens, provider_limit)
        return reasoning_max_tokens if reasoning_max_tokens > 0 else 4096
    return min(standard_max_tokens, provider_limit) if provider_limit else standard_max_tokens


def retry_after_seconds(response: httpx.Response | None, data: dict[str, Any] | None = None) -> float | None:
    values: list[Any] = []
    if response is not None:
        values.append(response.headers.get("Retry-After"))
    metadata = ((data or {}).get("error") or {}).get("metadata") if isinstance(data, dict) else None
    if isinstance(metadata, dict):
        values.extend([
            metadata.get("retry_after_seconds"),
            metadata.get("retry_after_seconds_raw"),
            (metadata.get("headers") or {}).get("Retry-After") if isinstance(metadata.get("headers"), dict) else None,
        ])
    for value in values:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            return parsed
    return None


def anomaly_flags(model_id: str, status_code: int | None, content: str, cost: float, latency_ms: int, returned_model: str | None) -> list[str]:
    flags: list[str] = []
    if status_code == 429:
        flags.append("rate_limited")
    elif status_code and status_code >= 500:
        flags.append("provider_error")
    elif status_code and status_code != 200:
        flags.append(f"http_{status_code}")
    if cost != 0:
        flags.append("nonzero_cost")
    if returned_model and not returned_model.endswith(":free"):
        flags.append("returned_nonfree_model_id")
    if returned_model and returned_model != model_id:
        flags.append("returned_model_alias_or_variant")
    if status_code == 200 and not content.strip():
        flags.append("empty_output")
    if status_code == 200 and EXPECTED not in content:
        flags.append("instruction_following_failed")
    if status_code == 200 and len(content) > len(EXPECTED) + 20:
        flags.append("verbose_or_noisy_output")
    if latency_ms >= 20_000:
        flags.append("slow_ge_20s")
    if latency_ms >= 45_000:
        flags.append("timeout_tail_ge_45s")
    return flags


async def fetch_free_models(client: httpx.AsyncClient, key: str) -> list[dict[str, Any]]:
    print("ACTION fetch OpenRouter /models")
    response = await client.get(f"{OPENROUTER_URL}/models", headers={"Authorization": f"Bearer {key}"})
    response.raise_for_status()
    models = response.json()["data"]
    free = [model for model in models if is_free_model(model)]
    free.sort(key=lambda model: model["id"])
    print(f"RESULT explicit_free_model_count={len(free)}")
    return free


async def fetch_key_info(client: httpx.AsyncClient, key: str) -> dict[str, Any]:
    response = await client.get(f"{OPENROUTER_URL}/key", headers={"Authorization": f"Bearer {key}"})
    if response.status_code != 200:
        return {"status_code": response.status_code, "available": False}
    payload = response.json()
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return {"status_code": response.status_code, "available": True}
    allowed_keys = {
        "label", "limit", "usage", "is_free_tier", "rate_limit", "free_model_requests",
        "remaining", "requests", "interval", "daily_limit", "daily_usage",
    }
    return {
        "status_code": response.status_code,
        "available": True,
        "data": {name: value for name, value in data.items() if name in allowed_keys},
    }


async def probe_model(
    client: httpx.AsyncClient,
    key: str,
    model: dict[str, Any],
    sem: asyncio.Semaphore,
    timeout: float,
    pacer: RequestPacer | None = None,
    standard_max_tokens: int = 512,
    reasoning_max_tokens: int = 4096,
    retry_on_rate_limit: bool = False,
) -> dict[str, Any]:
    model_id = model["id"]
    if not is_free_model(model):
        raise RuntimeError(f"Blocked non-free model: {model_id}")
    async with sem:
        max_tokens = max_tokens_for_model(model, standard_max_tokens, reasoning_max_tokens)
        print(f"ACTION probe model={model_id} provider={provider(model_id)} context={model.get('context_length')} max_tokens={max_tokens} reasoning={is_reasoning_model(model)} price_prompt=0 price_completion=0")
        started = time.perf_counter()
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": PROMPT}],
            "max_tokens": max_tokens,
            "temperature": 0,
        }
        try:
            if pacer:
                await pacer.wait()
            response = await asyncio.wait_for(
                client.post(
                    f"{OPENROUTER_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://systemvirtue.local",
                        "X-Title": "System Virtue Free Model Census",
                    },
                    json=payload,
                    timeout=timeout,
                ),
                timeout=timeout + 1,
            )
            latency_ms = int((time.perf_counter() - started) * 1000)
            try:
                data = response.json()
            except Exception:
                data = {"raw": response.text}
            content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
            usage = data.get("usage", {})
            cost = float(usage.get("cost", usage.get("cost_details", {}).get("upstream_inference_cost", 0)) or 0)
            returned_model = data.get("model")
            flags = anomaly_flags(model_id, response.status_code, content, cost, latency_ms, returned_model)
            retry_after = retry_after_seconds(response, data)
            retry_attempted = False
            if response.status_code == 429 and retry_on_rate_limit and retry_after:
                retry_attempted = True
                await asyncio.sleep(retry_after)
                if pacer:
                    await pacer.wait()
                retry_started = time.perf_counter()
                response = await asyncio.wait_for(
                    client.post(
                        f"{OPENROUTER_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://systemvirtue.local",
                            "X-Title": "System Virtue Free Model Census",
                        },
                        json=payload,
                        timeout=timeout,
                    ),
                    timeout=timeout + 1,
                )
                latency_ms = int((time.perf_counter() - retry_started) * 1000)
                try:
                    data = response.json()
                except Exception:
                    data = {"raw": response.text}
                content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
                usage = data.get("usage", {})
                cost = float(usage.get("cost", usage.get("cost_details", {}).get("upstream_inference_cost", 0)) or 0)
                returned_model = data.get("model")
                flags = anomaly_flags(model_id, response.status_code, content, cost, latency_ms, returned_model)
                retry_after = retry_after_seconds(response, data)
            ok = response.status_code == 200 and EXPECTED in content and cost == 0
            print(f"RESULT probe model={model_id} status={response.status_code} ok={ok} latency_ms={latency_ms} cost={cost} anomalies={','.join(flags) or 'none'}")
            return {
                "id": model_id,
                "provider": provider(model_id),
                "name": model.get("name"),
                "context_length": model.get("context_length"),
                "status_code": response.status_code,
                "ok": ok,
                "latency_ms": latency_ms,
                "returned_model": returned_model,
                "content_preview": content.replace("\n", " ")[:500],
                "usage": usage,
                "cost": cost,
                "anomalies": flags,
                "max_tokens": max_tokens,
                "reasoning_model": is_reasoning_model(model),
                "retry_after_seconds": retry_after,
                "retry_attempted": retry_attempted,
            }
        except (asyncio.TimeoutError, httpx.TimeoutException, httpx.NetworkError) as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            flags = ["hard_timeout" if isinstance(exc, asyncio.TimeoutError) else type(exc).__name__]
            print(f"RESULT probe model={model_id} status=None ok=False latency_ms={latency_ms} cost=0 anomalies={','.join(flags)}")
            return {
                "id": model_id,
                "provider": provider(model_id),
                "name": model.get("name"),
                "context_length": model.get("context_length"),
                "status_code": None,
                "ok": False,
                "latency_ms": latency_ms,
                "returned_model": None,
                "content_preview": "",
                "usage": {},
                "cost": 0,
                "anomalies": flags,
                "max_tokens": max_tokens_for_model(model, standard_max_tokens, reasoning_max_tokens),
                "reasoning_model": is_reasoning_model(model),
                "retry_after_seconds": None,
                "retry_attempted": False,
            }


def pctl(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[idx]


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    successes = [row for row in results if row["ok"]]
    latencies = [row["latency_ms"] for row in successes]
    anomalies: dict[str, int] = {}
    providers: dict[str, dict[str, Any]] = {}
    for row in results:
        provider_row = providers.setdefault(row["provider"], {"attempts": 0, "successes": 0, "latencies_ms": [], "anomalies": {}})
        provider_row["attempts"] += 1
        if row["ok"]:
            provider_row["successes"] += 1
            provider_row["latencies_ms"].append(row["latency_ms"])
        for flag in row["anomalies"]:
            anomalies[flag] = anomalies.get(flag, 0) + 1
            provider_row["anomalies"][flag] = provider_row["anomalies"].get(flag, 0) + 1
    for row in providers.values():
        row["success_rate"] = row["successes"] / max(1, row["attempts"])
        row["median_success_latency_ms"] = statistics.median(row["latencies_ms"]) if row["latencies_ms"] else None
        del row["latencies_ms"]
    fastest = sorted(successes, key=lambda row: row["latency_ms"])[:10]
    slowest = sorted(successes, key=lambda row: row["latency_ms"], reverse=True)[:10]
    return {
        "models_tested": len(results),
        "successes": len(successes),
        "success_rate": len(successes) / max(1, len(results)),
        "total_reported_cost_usd": sum(float(row["cost"] or 0) for row in results),
        "success_latency_ms": {
            "min": min(latencies) if latencies else None,
            "median": statistics.median(latencies) if latencies else None,
            "p90": pctl(latencies, 0.90),
            "p95": pctl(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
        "anomalies": dict(sorted(anomalies.items(), key=lambda item: (-item[1], item[0]))),
        "providers": dict(sorted(providers.items())),
        "fastest_successes": [{"id": row["id"], "latency_ms": row["latency_ms"], "provider": row["provider"]} for row in fastest],
        "slowest_successes": [{"id": row["id"], "latency_ms": row["latency_ms"], "provider": row["provider"]} for row in slowest],
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    lines = [
        "# OpenRouter Explicit Free Model Census",
        "",
        f"Created: {report['created_at']}",
        "",
        "## Guardrails",
        "",
        "- Queried only models where OpenRouter `/models` reported `prompt=0`, `completion=0`, and model id ended with `:free`.",
        "- Each call used a free-only exact-response probe. Reasoning/thinking models receive a larger token budget so hidden reasoning tokens do not consume the entire completion.",
        "- Any nonzero reported cost is flagged as an anomaly.",
        "",
        "## Summary",
        "",
        f"- Models tested: `{summary['models_tested']}`",
        f"- Successes: `{summary['successes']}`",
        f"- Success rate: `{summary['success_rate']:.2%}`",
        f"- Total reported cost: `${summary['total_reported_cost_usd']:.2f}`",
        f"- Success latency min: `{summary['success_latency_ms']['min']}` ms",
        f"- Success latency median: `{summary['success_latency_ms']['median']}` ms",
        f"- Success latency p90: `{summary['success_latency_ms']['p90']}` ms",
        f"- Success latency p95: `{summary['success_latency_ms']['p95']}` ms",
        f"- Success latency max: `{summary['success_latency_ms']['max']}` ms",
        f"- Anomalies: `{json.dumps(summary['anomalies'], sort_keys=True)}`",
        "",
        "## Fastest Successful Models",
        "",
        "| Model | Provider | Latency ms |",
        "|---|---|---:|",
    ]
    for row in summary["fastest_successes"]:
        lines.append(f"| `{row['id']}` | `{row['provider']}` | `{row['latency_ms']}` |")
    lines.extend(["", "## Slowest Successful Models", "", "| Model | Provider | Latency ms |", "|---|---|---:|"])
    for row in summary["slowest_successes"]:
        lines.append(f"| `{row['id']}` | `{row['provider']}` | `{row['latency_ms']}` |")
    lines.extend(["", "## Provider Summary", "", "| Provider | Attempts | Successes | Success Rate | Median Success Latency ms | Anomalies |", "|---|---:|---:|---:|---:|---|"])
    for provider_id, row in summary["providers"].items():
        lines.append(
            f"| `{provider_id}` | `{row['attempts']}` | `{row['successes']}` | "
            f"`{row['success_rate']:.2%}` | `{row['median_success_latency_ms']}` | "
            f"`{json.dumps(row['anomalies'], sort_keys=True)}` |"
        )
    lines.extend(["", "## Model Results", "", "| Model | Status | OK | Latency ms | Cost | Anomalies | Preview |", "|---|---:|---:|---:|---:|---|---|"])
    for row in report["results"]:
        preview = row["content_preview"].replace("|", "\\|")
        lines.append(
            f"| `{row['id']}` | `{row['status_code']}` | `{row['ok']}` | `{row['latency_ms']}` | "
            f"`{row['cost']}` | `{','.join(row['anomalies']) or ''}` | {preview} |"
        )
    path.write_text("\n".join(lines))


async def main() -> int:
    parser = argparse.ArgumentParser(description="Query every explicit OpenRouter :free model")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--request-spacing-seconds", type=float, default=3.1, help="Client-side pacing. 3.1s stays below OpenRouter's documented 20 RPM free-model limit.")
    parser.add_argument("--standard-max-tokens", type=int, default=512)
    parser.add_argument("--reasoning-max-tokens", type=int, default=0, help="Reasoning model budget. 0 uses the provider's advertised max completion cap when available, else 4096.")
    parser.add_argument("--retry-on-rate-limit", action="store_true", help="Retry once after OpenRouter's Retry-After delay when supplied.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key or key == "sk-or-your-key-here":
        print("OPENROUTER_API_KEY is missing", file=sys.stderr)
        return 2
    if os.environ.get("ALLOW_PAID_MODELS", "false").lower() != "false":
        print("Refusing to run: ALLOW_PAID_MODELS must be false", file=sys.stderr)
        return 2

    async with httpx.AsyncClient(timeout=args.timeout) as client:
        key_info = await fetch_key_info(client, key)
        free_models = await fetch_free_models(client, key)
        sem = asyncio.Semaphore(args.concurrency)
        pacer = RequestPacer(args.request_spacing_seconds)
        results = await asyncio.gather(*(
            probe_model(
                client, key, model, sem, args.timeout, pacer,
                args.standard_max_tokens, args.reasoning_max_tokens,
                args.retry_on_rate_limit,
            )
            for model in free_models
        ))

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": "openrouter_explicit_free_model_census",
        "probe": PROMPT,
        "concurrency": args.concurrency,
        "timeout_seconds": args.timeout,
        "request_spacing_seconds": args.request_spacing_seconds,
        "standard_max_tokens": args.standard_max_tokens,
        "reasoning_max_tokens": args.reasoning_max_tokens,
        "retry_on_rate_limit": args.retry_on_rate_limit,
        "openrouter_key_info": key_info,
        "results": sorted(results, key=lambda row: row["id"]),
    }
    report["summary"] = summarise(report["results"])

    out_dir = root / "benchmarks" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"openrouter_free_model_census_{stamp}.json"
    md_path = out_dir / f"openrouter_free_model_census_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2))
    write_markdown(report, md_path)
    print("ACTION write detailed reports")
    print(f"RESULT json_report={json_path}")
    print(f"RESULT markdown_report={md_path}")
    print("SUMMARY " + json.dumps(report["summary"], sort_keys=True))
    return 0 if report["summary"]["total_reported_cost_usd"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
