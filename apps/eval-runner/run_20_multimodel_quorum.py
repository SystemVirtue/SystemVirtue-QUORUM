import argparse
import asyncio
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from query_all_free_models import RequestPacer, fetch_free_models, fetch_key_info, is_reasoning_model, load_dotenv, max_tokens_for_model, retry_after_seconds
from quorum_collective_benchmark import diverse_candidates, is_free_model


PREFERRED_MODEL_ORDER = [
    "z-ai/glm-4.5-air:free",
    "arcee-ai/trinity-large-thinking:free",
    "openai/gpt-oss-120b:free",
    "nvidia/nemotron-3-nano-30b-a3b:free",
    "google/gemma-4-26b-a4b-it:free",
    "google/gemma-4-31b-it:free",
]


TASKS = [
    {
        "id": "t01_exact_smoke",
        "prompt": "Reply with exactly: QUORUM20_OK",
        "expected": "QUORUM20_OK",
        "max_tokens": 64,
        "mode": "fast",
        "council_size": 3,
        "minimum_quorum": 2,
    },
    {
        "id": "t02_python_cache",
        "prompt": "In three concise bullets, explain Python LRU cache behavior and one eviction edge case.",
        "expected_terms": ["cache", "eviction", "least"],
        "max_tokens": 512,
        "mode": "fast",
        "council_size": 3,
        "minimum_quorum": 2,
    },
    {
        "id": "t03_sql_migration",
        "prompt": "List three risks when adding a NOT NULL column to a large PostgreSQL table, including rollback.",
        "expected_terms": ["not null", "lock", "rollback"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t04_auth_security",
        "prompt": "Identify security issues in an auth endpoint that logs Authorization headers and accepts unsanitized redirect URLs.",
        "expected_terms": ["authorization", "redirect", "log"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t05_typescript_types",
        "prompt": "Explain why a TypeScript API client should model nullable fields explicitly and mention one runtime validation option.",
        "expected_terms": ["null", "typescript", "validation"],
        "max_tokens": 512,
        "mode": "fast",
        "council_size": 3,
        "minimum_quorum": 2,
    },
    {
        "id": "t06_rust_borrowing",
        "prompt": "In plain English, explain a Rust borrow-checker error caused by mutating a vector while iterating it.",
        "expected_terms": ["borrow", "mutat", "iterat"],
        "max_tokens": 512,
        "mode": "fast",
        "council_size": 3,
        "minimum_quorum": 2,
    },
    {
        "id": "t07_go_context",
        "prompt": "Name three reasons Go database functions should accept context.Context.",
        "expected_terms": ["context", "timeout", "cancel"],
        "max_tokens": 512,
        "mode": "fast",
        "council_size": 3,
        "minimum_quorum": 2,
    },
    {
        "id": "t08_docker_compose",
        "prompt": "Give a short checklist for debugging a Docker Compose service that starts before Postgres is ready.",
        "expected_terms": ["health", "depends", "postgres"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t09_frontend_accessibility",
        "prompt": "List three accessibility checks for a modal dialog in a React app.",
        "expected_terms": ["focus", "aria", "escape"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t10_race_condition",
        "prompt": "Explain how a race condition can occur when two workers update the same account balance, and name one mitigation.",
        "expected_terms": ["race", "transaction", "lock"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t11_test_generation",
        "prompt": "Suggest unit tests for a function that parses ISO dates and rejects invalid timezone offsets.",
        "expected_terms": ["timezone", "invalid", "test"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t12_prompt_injection",
        "prompt": "Identify prompt-injection risks when one AI agent critiques another agent's output.",
        "expected_terms": ["instruction", "data", "sandbox"],
        "max_tokens": 512,
        "mode": "adversarial",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t13_idempotency",
        "prompt": "Explain why payment webhooks should be idempotent and mention one database technique to enforce it.",
        "expected_terms": ["idempot", "webhook", "unique"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t14_observability",
        "prompt": "List useful telemetry for diagnosing intermittent HTTP 429 responses from an upstream model API.",
        "expected_terms": ["429", "retry", "rate"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t15_json_reliability",
        "prompt": "Give three ways to improve JSON reliability when calling an LLM for structured classification.",
        "expected_terms": ["json", "schema", "retry"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t16_api_error_handling",
        "prompt": "Describe robust client handling for HTTP 400, 429, and 503 from a model provider.",
        "expected_terms": ["400", "429", "503"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t17_code_review",
        "prompt": "Review this pseudocode bug: if user.is_admin or user.id == target_id then delete_account(target_id). What risk exists?",
        "expected_terms": ["admin", "delete", "authorization"],
        "max_tokens": 512,
        "mode": "adversarial",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t18_architecture",
        "prompt": "For a self-hosted multi-agent coding tool, name three architectural reasons to keep the OpenAI-compatible API surface.",
        "expected_terms": ["openai", "compatible", "client"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t19_secret_redaction",
        "prompt": "List patterns that should be redacted before persisting LLM traces.",
        "expected_terms": ["token", "key", "secret"],
        "max_tokens": 512,
        "mode": "adversarial",
        "council_size": 4,
        "minimum_quorum": 3,
    },
    {
        "id": "t20_consensus",
        "prompt": "Explain why a model council should expose disagreements instead of hiding them in final synthesis.",
        "expected_terms": ["disagreement", "consensus", "transparen"],
        "max_tokens": 512,
        "mode": "balanced",
        "council_size": 4,
        "minimum_quorum": 3,
    },
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pctl(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[idx]


def evaluate_content(task: dict[str, Any], content: str) -> bool:
    lower = content.lower()
    if "expected" in task:
        return task["expected"] in content
    terms = task.get("expected_terms", [])
    if not terms:
        return bool(content.strip())
    matches = sum(1 for term in terms if term in lower)
    required = len(terms) if len(terms) <= 2 else max(2, len(terms) - 1)
    return matches >= required


def optimized_candidates(models: list[dict[str, Any]], only_preferred: bool = False) -> list[dict[str, Any]]:
    by_id = {model["id"]: model for model in models}
    preferred = [by_id[model_id] for model_id in PREFERRED_MODEL_ORDER if model_id in by_id]
    if only_preferred:
        return preferred
    preferred_ids = {model["id"] for model in preferred}
    remainder = [model for model in diverse_candidates(models) if model["id"] not in preferred_ids]
    return preferred + remainder


async def call_member(
    client: httpx.AsyncClient,
    key: str,
    model: dict[str, Any],
    task: dict[str, Any],
    pacer: RequestPacer,
    standard_max_tokens: int,
    reasoning_max_tokens: int,
    per_call_timeout_seconds: float,
) -> dict[str, Any]:
    if not is_free_model(model):
        raise RuntimeError(f"blocked_non_free_model:{model.get('id')}")

    model_id = model["id"]
    max_tokens = max_tokens_for_model(model, max(task["max_tokens"], standard_max_tokens), reasoning_max_tokens)
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": task["prompt"]}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://systemvirtue.local",
        "X-Title": "System Virtue QUORUM Sequential Benchmark",
    }
    started = time.perf_counter()
    retry_attempted = False
    response: httpx.Response | None = None
    data: dict[str, Any] = {}

    for attempt in range(2):
        await pacer.wait()
        try:
            response = await asyncio.wait_for(
                client.post(f"{OPENROUTER_URL}/chat/completions", headers=headers, json=payload),
                timeout=per_call_timeout_seconds,
            )
        except (asyncio.TimeoutError, httpx.TimeoutException) as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return {
                "requested_model": model_id,
                "returned_model": None,
                "status_code": None,
                "ok": False,
                "failure_reason": "timeout",
                "latency_ms": latency_ms,
                "cost": 0.0,
                "usage": {},
                "max_tokens": max_tokens,
                "reasoning_model": is_reasoning_model(model),
                "retry_after_seconds": None,
                "retry_attempted": retry_attempted,
                "content_preview": type(exc).__name__,
            }
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        wait_for = retry_after_seconds(response, data)
        if response.status_code == 429 and wait_for and attempt == 0:
            retry_attempted = True
            print(f"PROGRESS rate_limited model={model_id} retry_after={wait_for}s")
            await asyncio.sleep(wait_for)
            continue
        break

    latency_ms = int((time.perf_counter() - started) * 1000)
    assert response is not None
    content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""
    usage = data.get("usage", {})
    cost = float(usage.get("cost", usage.get("cost_details", {}).get("upstream_inference_cost", 0)) or 0)
    ok = response.status_code == 200 and cost == 0 and evaluate_content(task, content)
    failure_reason = None
    if response.status_code == 429:
        failure_reason = "rate_limit"
    elif response.status_code != 200:
        failure_reason = f"http_{response.status_code}"
    elif cost != 0:
        failure_reason = "nonzero_cost"
    elif not evaluate_content(task, content):
        failure_reason = "content_check_failed"

    return {
        "requested_model": model_id,
        "returned_model": data.get("model"),
        "status_code": response.status_code,
        "ok": ok,
        "failure_reason": failure_reason,
        "latency_ms": latency_ms,
        "cost": cost,
        "usage": usage,
        "max_tokens": max_tokens,
        "reasoning_model": is_reasoning_model(model),
        "retry_after_seconds": retry_after_seconds(response, data),
        "retry_attempted": retry_attempted,
        "content_preview": content.replace("\n", " ")[:700],
    }


async def run_one_test(
    client: httpx.AsyncClient,
    key: str,
    candidates: list[dict[str, Any]],
    task: dict[str, Any],
    test_index: int,
    pacer: RequestPacer,
    standard_max_tokens: int,
    reasoning_max_tokens: int,
    per_call_timeout_seconds: float,
    max_attempts: int,
) -> dict[str, Any]:
    total_tests = task.get("total_tests", "?")
    print(f"PROGRESS test_start {test_index}/{total_tests} task={task['id']} mode={task['mode']} target={task['council_size']} min_quorum={task['minimum_quorum']}")
    started = time.perf_counter()
    offset = (test_index - 1) % max(1, len(candidates))
    ordered = candidates[offset:] + candidates[:offset]
    member_results: list[dict[str, Any]] = []
    attempted_models: list[str] = []

    for model in ordered[:max_attempts]:
        successes = sum(1 for row in member_results if row["ok"])
        if len(member_results) >= task["council_size"] and successes >= task["minimum_quorum"]:
            break
        attempted_models.append(model["id"])
        print(f"PROGRESS member_call test={test_index}/{total_tests} model={model['id']} attempt={len(member_results) + 1}/{max_attempts}")
        row = await call_member(client, key, model, task, pacer, standard_max_tokens, reasoning_max_tokens, per_call_timeout_seconds)
        member_results.append(row)
        successes = sum(1 for item in member_results if item["ok"])
        print(
            "PROGRESS member_result "
            f"test={test_index}/{total_tests} model={model['id']} status={row['status_code']} ok={row['ok']} "
            f"latency_ms={row['latency_ms']} cost={row['cost']} successes={successes}"
        )

    wall_clock_ms = int((time.perf_counter() - started) * 1000)
    successes = [row for row in member_results if row["ok"]]
    failures = [row for row in member_results if not row["ok"]]
    quorum_met = len(successes) >= task["minimum_quorum"]
    fallback_count = max(0, len(member_results) - task["council_size"])
    best_individual_ok = any(row["ok"] for row in member_results[:task["council_size"]])
    all_initial_individuals_ok = all(row["ok"] for row in member_results[:task["council_size"]]) if len(member_results) >= task["council_size"] else False
    result = {
        "test_index": test_index,
        "task_id": task["id"],
        "mode": task["mode"],
        "target_council_size": task["council_size"],
        "minimum_quorum": task["minimum_quorum"],
        "attempted_models": attempted_models,
        "quorum_met": quorum_met,
        "successful_members": len(successes),
        "failed_members": len(failures),
        "fallback_count": fallback_count,
        "best_individual_ok": best_individual_ok,
        "all_initial_individuals_ok": all_initial_individuals_ok,
        "wall_clock_ms": wall_clock_ms,
        "marginal_cost_usd": sum(float(row.get("cost") or 0) for row in member_results),
        "member_results": member_results,
    }
    print(
        "PROGRESS test_complete "
        f"{test_index}/{total_tests} task={task['id']} quorum_met={quorum_met} successes={len(successes)} "
        f"failures={len(failures)} fallbacks={fallback_count} wall_clock_ms={wall_clock_ms} "
        f"cost={result['marginal_cost_usd']}"
    )
    return result


def summarise(results: list[dict[str, Any]]) -> dict[str, Any]:
    members = [member for result in results for member in result["member_results"]]
    ok_members = [member for member in members if member["ok"]]
    latencies = [member["latency_ms"] for member in ok_members]
    failures: dict[str, int] = {}
    retry_count = 0
    for member in members:
        if member["retry_attempted"]:
            retry_count += 1
        if not member["ok"]:
            reason = member["failure_reason"] or "unknown"
            failures[reason] = failures.get(reason, 0) + 1
    per_model: dict[str, dict[str, Any]] = {}
    for member in members:
        row = per_model.setdefault(member["requested_model"], {"attempts": 0, "successes": 0, "failures": 0, "latencies": [], "failure_reasons": {}})
        row["attempts"] += 1
        row["latencies"].append(member["latency_ms"])
        if member["ok"]:
            row["successes"] += 1
        else:
            row["failures"] += 1
            reason = member["failure_reason"] or "unknown"
            row["failure_reasons"][reason] = row["failure_reasons"].get(reason, 0) + 1
    for row in per_model.values():
        row["success_rate"] = row["successes"] / max(1, row["attempts"])
        row["median_latency_ms"] = statistics.median(row["latencies"])
        row["p95_latency_ms"] = pctl(row["latencies"], 0.95)
        del row["latencies"]
    return {
        "tests": len(results),
        "quorum_successes": sum(1 for result in results if result["quorum_met"]),
        "quorum_success_rate": sum(1 for result in results if result["quorum_met"]) / max(1, len(results)),
        "best_individual_success_rate": sum(1 for result in results if result["best_individual_ok"]) / max(1, len(results)),
        "all_initial_individuals_success_rate": sum(1 for result in results if result["all_initial_individuals_ok"]) / max(1, len(results)),
        "member_attempts": len(members),
        "member_success_rate": len(ok_members) / max(1, len(members)),
        "failure_reasons": failures,
        "retry_attempts": retry_count,
        "total_fallbacks": sum(result["fallback_count"] for result in results),
        "total_reported_cost_usd": sum(float(result.get("marginal_cost_usd") or 0) for result in results),
        "successful_member_latency_ms": {
            "min": min(latencies) if latencies else None,
            "median": statistics.median(latencies) if latencies else None,
            "p95": pctl(latencies, 0.95),
            "max": max(latencies) if latencies else None,
        },
        "test_wall_clock_ms": {
            "median": statistics.median([result["wall_clock_ms"] for result in results]),
            "p95": pctl([result["wall_clock_ms"] for result in results], 0.95),
            "max": max(result["wall_clock_ms"] for result in results),
        },
        "per_model": dict(sorted(per_model.items(), key=lambda item: (-item[1]["success_rate"], item[1]["median_latency_ms"], item[0]))),
    }


def write_markdown(report: dict[str, Any], path: Path) -> None:
    summary = report["summary"]
    lines = [
        f"# {summary['tests']}-Test Sequential QUORUM Free-Tier Benchmark",
        "",
        f"Created: {report['created_at']}",
        "",
        "## Guardrails",
        "",
        "- Only live OpenRouter models with `prompt=0`, `completion=0`, `:free`, and context length >= 8192 were eligible.",
        "- Calls were sequential: one test at a time, one model call at a time inside each test.",
        "- HTTP 429 used `Retry-After` when supplied, then retried once.",
        f"- Standard models used `{report['policy']['standard_max_tokens']}` max tokens; reasoning/thinking models used `{report['policy']['reasoning_max_tokens']}` max tokens.",
        f"- Individual member calls used `{report['policy']['per_call_timeout_seconds']}` second stall protection so one bad provider cannot block the whole run.",
        "- Any nonzero reported cost fails the member result.",
        "",
        "## Summary",
        "",
        f"- Tests: `{summary['tests']}`",
        f"- QUORUM success rate: `{summary['quorum_success_rate']:.2%}` (`{summary['quorum_successes']}/{summary['tests']}`)",
        f"- Best individual observed success rate: `{summary['best_individual_success_rate']:.2%}`",
        f"- All initial council members success rate: `{summary['all_initial_individuals_success_rate']:.2%}`",
        f"- Member success rate: `{summary['member_success_rate']:.2%}` (`{summary['member_attempts']}` attempts)",
        f"- Retry attempts: `{summary['retry_attempts']}`",
        f"- Fallback substitutions: `{summary['total_fallbacks']}`",
        f"- Total reported cost: `${summary['total_reported_cost_usd']:.2f}`",
        f"- Successful member latency median/p95/max: `{summary['successful_member_latency_ms']['median']}` / `{summary['successful_member_latency_ms']['p95']}` / `{summary['successful_member_latency_ms']['max']}` ms",
        f"- Test wall-clock median/p95/max: `{summary['test_wall_clock_ms']['median']}` / `{summary['test_wall_clock_ms']['p95']}` / `{summary['test_wall_clock_ms']['max']}` ms",
        f"- Failure reasons: `{json.dumps(summary['failure_reasons'], sort_keys=True)}`",
        "",
        "## Per-Test Results",
        "",
        "| # | Task | Mode | Quorum | Successes | Failures | Fallbacks | Wall ms | Cost |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for result in report["results"]:
        lines.append(
            f"| {result['test_index']} | `{result['task_id']}` | `{result['mode']}` | `{result['quorum_met']}` | "
            f"{result['successful_members']} | {result['failed_members']} | {result['fallback_count']} | "
            f"{result['wall_clock_ms']} | `${result['marginal_cost_usd']:.2f}` |"
        )
    lines.extend(["", "## Per-Model Reliability", "", "| Model | Attempts | Successes | Success Rate | Median ms | P95 ms | Failures |", "|---|---:|---:|---:|---:|---:|---|"])
    for model_id, row in summary["per_model"].items():
        lines.append(
            f"| `{model_id}` | {row['attempts']} | {row['successes']} | `{row['success_rate']:.2%}` | "
            f"{row['median_latency_ms']} | {row['p95_latency_ms']} | `{json.dumps(row['failure_reasons'], sort_keys=True)}` |"
        )
    lines.extend(["", "## Member Details", ""])
    for result in report["results"]:
        lines.extend([
            f"### {result['test_index']}. {result['task_id']}",
            "",
            "| Model | OK | Status | Latency ms | Max Tokens | Reasoning | Retry | Failure | Preview |",
            "|---|---:|---:|---:|---:|---:|---:|---|---|",
        ])
        for member in result["member_results"]:
            preview = member["content_preview"].replace("|", "\\|")
            lines.append(
                f"| `{member['requested_model']}` | `{member['ok']}` | `{member['status_code']}` | `{member['latency_ms']}` | "
                f"`{member['max_tokens']}` | `{member['reasoning_model']}` | `{member['retry_attempted']}` | "
                f"`{member['failure_reason'] or ''}` | {preview} |"
            )
        lines.append("")
    path.write_text("\n".join(lines))


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run sequential free-only multi-model QUORUM tests")
    parser.add_argument("--tests", type=int, default=20)
    parser.add_argument("--only-preferred-six", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--request-spacing-seconds", type=float, default=3.1)
    parser.add_argument("--standard-max-tokens", type=int, default=768)
    parser.add_argument("--reasoning-max-tokens", type=int, default=4096)
    parser.add_argument("--per-call-timeout-seconds", type=float, default=90)
    parser.add_argument("--max-attempts", type=int, default=8)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env")
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise SystemExit("OPENROUTER_API_KEY is missing")
    if os.environ.get("ALLOW_PAID_MODELS", "false").lower() != "false":
        raise SystemExit("Refusing to run unless ALLOW_PAID_MODELS=false")

    run_id = datetime.now(timezone.utc).strftime(f"quorum{args.tests}_%Y%m%dT%H%M%SZ")
    out_dir = root / "benchmarks" / "runs" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / "raw_results.jsonl"
    report_json_path = out_dir / "report.json"
    report_md_path = out_dir / "report.md"

    print(f"PROGRESS run_start run_id={run_id}")
    async with httpx.AsyncClient(timeout=None) as client:
        key_info = await fetch_key_info(client, key)
        free_models = await fetch_free_models(client, key)
        candidates = optimized_candidates(free_models, args.only_preferred_six)
        if args.only_preferred_six and len(candidates) < 6:
            raise SystemExit(f"Preferred-six run requires all six preferred models; found {len(candidates)}")
        print("PROGRESS candidate_order " + ",".join(model["id"] for model in candidates[:10]))
        pacer = RequestPacer(args.request_spacing_seconds)
        results = []
        selected_tasks = [{**TASKS[i % len(TASKS)], "total_tests": args.tests} for i in range(args.tests)]
        for index, task in enumerate(selected_tasks, start=1):
            result = await run_one_test(
                client=client,
                key=key,
                candidates=candidates,
                task=task,
                test_index=index,
                pacer=pacer,
                standard_max_tokens=args.standard_max_tokens,
                reasoning_max_tokens=args.reasoning_max_tokens,
                per_call_timeout_seconds=args.per_call_timeout_seconds,
                max_attempts=args.max_attempts,
            )
            results.append(result)
            with raw_path.open("a") as handle:
                handle.write(json.dumps(result) + "\n")
            partial = summarise(results)
            print(
                "PROGRESS aggregate "
                f"completed={index}/{args.tests} quorum_success_rate={partial['quorum_success_rate']:.2%} "
                f"member_success_rate={partial['member_success_rate']:.2%} retries={partial['retry_attempts']} "
                f"fallbacks={partial['total_fallbacks']} cost={partial['total_reported_cost_usd']:.2f}"
            )

    report = {
        "created_at": utc_now(),
        "run_id": run_id,
        "key_info": key_info,
        "free_pool_count": len(free_models),
        "candidate_order": [model["id"] for model in candidates],
        "policy": {
            "tests": args.tests,
            "only_preferred_six": args.only_preferred_six,
            "sequential_tests": True,
            "sequential_member_calls": True,
            "request_spacing_seconds": args.request_spacing_seconds,
            "standard_max_tokens": args.standard_max_tokens,
            "reasoning_max_tokens": args.reasoning_max_tokens,
            "per_call_timeout_seconds": args.per_call_timeout_seconds,
            "max_attempts": args.max_attempts,
            "rate_limit_retry": "once_after_retry_after",
            "allow_paid_models": False,
        },
        "results": results,
    }
    report["summary"] = summarise(results)
    report_json_path.write_text(json.dumps(report, indent=2))
    write_markdown(report, report_md_path)
    print(f"PROGRESS run_complete json={report_json_path} markdown={report_md_path}")
    print("SUMMARY " + json.dumps(report["summary"], sort_keys=True))
    return 0 if report["summary"]["total_reported_cost_usd"] == 0 else 1


if __name__ == "__main__":
    OPENROUTER_URL = "https://openrouter.ai/api/v1"
    raise SystemExit(asyncio.run(main()))
