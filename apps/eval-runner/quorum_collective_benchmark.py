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
REPUTABLE_NAMESPACES = (
    "meta-llama/", "qwen/", "deepseek/", "mistralai/",
    "google/", "nvidia/", "microsoft/", "anthropic/",
    "openai/", "x-ai/", "cohere/", "01-ai/",
    "nous-research/", "openrouter/",
)

TASKS = [
    {
        "id": "exact_smoke",
        "prompt": "Smoke test only. Reply with exactly: QUORUM_FREE_OK",
        "expected": "QUORUM_FREE_OK",
        "max_tokens": 20,
        "mode": "fast",
        "council_size": 3,
        "minimum_quorum": 2,
    },
    {
        "id": "python_lru_summary",
        "prompt": "In two concise bullet points, explain what a Python LRU cache does and name one edge case to test.",
        "expected_terms": ["cache", "least", "edge"],
        "max_tokens": 90,
        "mode": "fast",
        "council_size": 3,
        "minimum_quorum": 2,
    },
    {
        "id": "security_review_summary",
        "prompt": "In three concise bullets, identify security risks in an auth endpoint that logs Authorization headers and accepts unsanitized redirect URLs.",
        "expected_terms": ["authorization", "redirect", "log"],
        "max_tokens": 120,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
]


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


def provider_rank(model_id: str) -> tuple[int, str]:
    order = {
        "deepseek/": 0,
        "qwen/": 1,
        "google/": 2,
        "nvidia/": 3,
        "meta-llama/": 4,
        "mistralai/": 5,
        "openai/": 6,
        "openrouter/": 7,
    }
    return min((rank for prefix, rank in order.items() if model_id.startswith(prefix)), default=30), model_id


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
    print("ACTION fetch OpenRouter /models and filter prompt=0 completion=0 :free context>=8192")
    response = await client.get(f"{OPENROUTER_URL}/models", headers={"Authorization": f"Bearer {key}"})
    response.raise_for_status()
    models = response.json()["data"]
    free = [
        model for model in models
        if is_free_model(model) and any(model["id"].startswith(prefix) for prefix in REPUTABLE_NAMESPACES)
    ]
    free.sort(key=lambda model: provider_rank(model["id"]))
    print(f"RESULT free_reputable_pool={len(free)}")
    return free


def evaluate_content(task: dict[str, Any], content: str) -> bool:
    lower = content.lower()
    if "expected" in task:
        return task["expected"] in content
    return all(term in lower for term in task.get("expected_terms", []))


async def call_model(client: httpx.AsyncClient, key: str, model: dict[str, Any] | str, task: dict[str, Any]) -> dict[str, Any]:
    model_id = model["id"] if isinstance(model, dict) else model
    if isinstance(model, dict) and not is_free_model(model):
        raise RuntimeError(f"Blocked non-free model before call: {model_id}")
    if not isinstance(model, dict) and model_id != "openrouter/free":
        raise RuntimeError(f"Blocked non-free router before call: {model_id}")

    print(f"ACTION call model={model_id} task={task['id']} price_prompt=0 price_completion=0")
    started = time.perf_counter()
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": task["prompt"]}],
        "max_tokens": task["max_tokens"],
        "temperature": 0,
    }
    try:
        response = await client.post(
            f"{OPENROUTER_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://systemvirtue.local",
                "X-Title": "System Virtue QUORUM Free Benchmark",
            },
            json=payload,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
        usage = data.get("usage", {})
        cost = usage.get("cost", usage.get("cost_details", {}).get("upstream_inference_cost", 0))
        ok = response.status_code == 200 and evaluate_content(task, content) and float(cost or 0) == 0
        failure_reason = None
        if response.status_code == 429:
            failure_reason = "rate_limit"
        elif response.status_code != 200:
            failure_reason = f"http_{response.status_code}"
        elif float(cost or 0) != 0:
            failure_reason = "nonzero_cost"
        elif not evaluate_content(task, content):
            failure_reason = "content_check_failed"
        print(f"RESULT model={model_id} task={task['id']} status={response.status_code} ok={ok} latency_ms={elapsed_ms} cost={cost} reason={failure_reason or 'none'}")
        return {
            "requested_model": model_id,
            "returned_model": data.get("model"),
            "task_id": task["id"],
            "ok": ok,
            "status_code": response.status_code,
            "failure_reason": failure_reason,
            "latency_ms": elapsed_ms,
            "content_preview": content.replace("\n", " ")[:500],
            "cost": cost,
            "usage": usage,
        }
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        print(f"RESULT model={model_id} task={task['id']} ok=False latency_ms={elapsed_ms} reason={type(exc).__name__}")
        return {
            "requested_model": model_id,
            "returned_model": None,
            "task_id": task["id"],
            "ok": False,
            "status_code": None,
            "failure_reason": type(exc).__name__,
            "latency_ms": elapsed_ms,
            "content_preview": "",
            "cost": 0,
            "usage": {},
        }


async def run_collective(client: httpx.AsyncClient, key: str, candidates: list[dict[str, Any]], task: dict[str, Any], max_attempts: int) -> dict[str, Any]:
    print(f"ACTION collective task={task['id']} mode={task['mode']} target={task['council_size']} min_quorum={task['minimum_quorum']} max_attempts={max_attempts}")
    attempted: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    started = time.perf_counter()
    for model in candidates[:max_attempts]:
        attempted.append(model)
        result = await call_model(client, key, model, task)
        results.append(result)
        successes = sum(1 for item in results if item["ok"])
        if successes >= task["council_size"]:
            break
        if len(results) >= task["council_size"] and successes >= task["minimum_quorum"]:
            break
    wall_clock_ms = int((time.perf_counter() - started) * 1000)
    successes = [item for item in results if item["ok"]]
    failures = [item for item in results if not item["ok"]]
    fallback_count = max(0, len(results) - task["council_size"])
    quorum_met = len(successes) >= task["minimum_quorum"]
    print(f"RESULT collective task={task['id']} quorum_met={quorum_met} successes={len(successes)} failures={len(failures)} fallback_count={fallback_count} wall_clock_ms={wall_clock_ms}")
    return {
        "task_id": task["id"],
        "mode": task["mode"],
        "target_council_size": task["council_size"],
        "minimum_quorum": task["minimum_quorum"],
        "attempted_models": [model["id"] for model in attempted],
        "quorum_met": quorum_met,
        "successful_members": len(successes),
        "failed_members": len(failures),
        "fallback_count": fallback_count,
        "wall_clock_ms": wall_clock_ms,
        "member_results": results,
        "marginal_cost_usd": sum(float(item.get("cost") or 0) for item in results),
    }


async def run_baselines(client: httpx.AsyncClient, key: str, candidates: list[dict[str, Any]], task: dict[str, Any]) -> dict[str, Any]:
    print(f"ACTION baselines task={task['id']} individual_free_models=3 openrouter_free_router=1")
    individual = [await call_model(client, key, model, task) for model in candidates[:3]]
    router = await call_model(client, key, "openrouter/free", task)
    best_individual_ok = any(item["ok"] for item in individual)
    print(f"RESULT baselines task={task['id']} best_individual_ok={best_individual_ok} openrouter_free_ok={router['ok']}")
    return {
        "task_id": task["id"],
        "individual_free_top3": individual,
        "best_individual_ok": best_individual_ok,
        "openrouter_free": router,
        "reported_cost_usd": sum(float(item.get("cost") or 0) for item in individual) + float(router.get("cost") or 0),
    }


def pctl(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[idx]


def summarise(report: dict[str, Any]) -> dict[str, Any]:
    member_results = [item for collective in report["collective_results"] for item in collective["member_results"]]
    baseline_results = [
        item
        for baseline in report.get("baseline_results", [])
        for item in baseline["individual_free_top3"] + [baseline["openrouter_free"]]
    ]
    latencies = [item["latency_ms"] for item in member_results if item["ok"]]
    failures: dict[str, int] = {}
    for item in member_results:
        if not item["ok"]:
            reason = item["failure_reason"] or "unknown"
            failures[reason] = failures.get(reason, 0) + 1
    return {
        "tasks": len(report["collective_results"]),
        "quorum_success_rate": sum(1 for item in report["collective_results"] if item["quorum_met"]) / max(1, len(report["collective_results"])),
        "member_success_rate": sum(1 for item in member_results if item["ok"]) / max(1, len(member_results)),
        "successful_member_latency_ms": {
            "min": min(latencies) if latencies else None,
            "median": statistics.median(latencies) if latencies else None,
            "p95": pctl(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
        "failure_reasons": failures,
        "total_reported_cost_usd": sum(float(item.get("cost") or 0) for item in member_results),
        "baseline_reported_cost_usd": sum(float(item.get("cost") or 0) for item in baseline_results),
        "openrouter_free_success_rate": sum(1 for item in report.get("baseline_results", []) if item["openrouter_free"]["ok"]) / max(1, len(report.get("baseline_results", []))),
        "best_individual_top3_success_rate": sum(1 for item in report.get("baseline_results", []) if item["best_individual_ok"]) / max(1, len(report.get("baseline_results", []))),
        "total_fallbacks": sum(item["fallback_count"] for item in report["collective_results"]),
    }


def write_markdown(report: dict[str, Any], summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# QUORUM Free-Tier Collective Benchmark Report",
        "",
        f"Created: {report['created_at']}",
        "",
        "## Guardrails",
        "",
        "- `ALLOW_PAID_MODELS=false` was required.",
        "- Every candidate was fetched from OpenRouter `/models` and required `prompt=0`, `completion=0`, `:free`, and context length >= 8192.",
        "- The runner blocked non-free candidates before every call.",
        "- Reported total model cost was required to remain `$0.00`.",
        "",
        "## Summary",
        "",
        f"- Free reputable pool discovered: `{report['free_pool_count']}`",
        f"- Tasks: `{summary['tasks']}`",
        f"- Quorum success rate: `{summary['quorum_success_rate']:.2%}`",
        f"- Member success rate: `{summary['member_success_rate']:.2%}`",
        f"- Total fallbacks/substitutions: `{summary['total_fallbacks']}`",
        f"- Total reported cost: `${summary['total_reported_cost_usd']:.2f}`",
        f"- Baseline reported cost: `${summary['baseline_reported_cost_usd']:.2f}`",
        f"- Best individual top-3 success rate: `{summary['best_individual_top3_success_rate']:.2%}`",
        f"- `openrouter/free` success rate: `{summary['openrouter_free_success_rate']:.2%}`",
        f"- Successful latency median: `{summary['successful_member_latency_ms']['median']}` ms",
        f"- Successful latency p95: `{summary['successful_member_latency_ms']['p95']}` ms",
        f"- Failure reasons: `{json.dumps(summary['failure_reasons'], sort_keys=True)}`",
        "",
        "## Baseline Results",
        "",
    ]
    for baseline in report.get("baseline_results", []):
        lines.extend([
            f"### {baseline['task_id']}",
            "",
            f"- Best top-3 individual free model succeeded: `{baseline['best_individual_ok']}`",
            f"- `openrouter/free` succeeded: `{baseline['openrouter_free']['ok']}`",
            f"- Reported baseline cost: `${baseline['reported_cost_usd']:.2f}`",
            "",
        ])
    lines.extend([
        "## Collective Results",
        "",
    ])
    for collective in report["collective_results"]:
        lines.extend([
            f"### {collective['task_id']}",
            "",
            f"- Mode: `{collective['mode']}`",
            f"- Target council size: `{collective['target_council_size']}`",
            f"- Minimum quorum: `{collective['minimum_quorum']}`",
            f"- Quorum met: `{collective['quorum_met']}`",
            f"- Successful members: `{collective['successful_members']}`",
            f"- Failed members: `{collective['failed_members']}`",
            f"- Fallback count: `{collective['fallback_count']}`",
            f"- Wall clock: `{collective['wall_clock_ms']}` ms",
            f"- Reported cost: `${collective['marginal_cost_usd']:.2f}`",
            "",
            "| Model | Status | OK | Latency ms | Cost | Failure | Preview |",
            "|---|---:|---:|---:|---:|---|---|",
        ])
        for member in collective["member_results"]:
            preview = member["content_preview"].replace("|", "\\|")
            lines.append(
                f"| `{member['requested_model']}` | `{member['status_code']}` | `{member['ok']}` | "
                f"`{member['latency_ms']}` | `{member['cost']}` | `{member['failure_reason'] or ''}` | {preview} |"
            )
        lines.append("")
    path.write_text("\n".join(lines))


async def main() -> int:
    parser = argparse.ArgumentParser(description="Free-only QUORUM collective benchmark")
    parser.add_argument("--max-attempts", type=int, default=8)
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

    async with httpx.AsyncClient(timeout=45) as client:
        free_models = await fetch_free_models(client, key)
        candidates = diverse_candidates(free_models)
        print("ACTION candidate_order " + ", ".join(model["id"] for model in candidates[:args.max_attempts]))
        collective_results = [
            await run_collective(client, key, candidates, task, args.max_attempts)
            for task in TASKS
        ]
        baseline_results = [
            await run_baselines(client, key, candidates, task)
            for task in TASKS
        ]

    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "benchmark": "quorum_collective_free_tier",
        "free_pool_count": len(free_models),
        "candidate_order": [model["id"] for model in candidates[:args.max_attempts]],
        "collective_results": collective_results,
        "baseline_results": baseline_results,
    }
    summary = summarise(report)
    report["summary"] = summary

    out_dir = root / "benchmarks" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = out_dir / f"quorum_collective_free_{stamp}.json"
    md_path = out_dir / f"quorum_collective_free_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2))
    write_markdown(report, summary, md_path)
    print("ACTION write detailed reports")
    print(f"RESULT json_report={json_path}")
    print(f"RESULT markdown_report={md_path}")
    print("SUMMARY " + json.dumps(summary, sort_keys=True))
    return 0 if summary["total_reported_cost_usd"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
