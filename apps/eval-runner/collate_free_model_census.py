import argparse
import json
import statistics
from pathlib import Path
from typing import Any


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def pctl(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[idx]


def latency_stats(values: list[int]) -> dict[str, Any]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "mean": sum(values) / len(values) if values else None,
        "median": statistics.median(values) if values else None,
        "p90": pctl(values, 0.90),
        "p95": pctl(values, 0.95),
        "max": max(values) if values else None,
    }


def iqr_bounds(values: list[int]) -> tuple[float | None, float | None]:
    if len(values) < 4:
        return None, None
    ordered = sorted(values)
    q1 = statistics.quantiles(ordered, n=4, method="inclusive")[0]
    q3 = statistics.quantiles(ordered, n=4, method="inclusive")[2]
    iqr = q3 - q1
    return q1 - 1.5 * iqr, q3 + 1.5 * iqr


def trimmed_mean(values: list[int], trim_ratio: float = 0.1) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    trim = int(len(ordered) * trim_ratio)
    trimmed = ordered[trim:len(ordered) - trim] if len(ordered) - trim > trim else ordered
    return sum(trimmed) / len(trimmed)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def aggregate_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_model: dict[str, dict[str, Any]] = {}
    by_provider: dict[str, dict[str, Any]] = {}
    anomaly_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    total_cost = 0.0

    for record in records:
        model_id = record["id"]
        provider = record["provider"]
        model_row = by_model.setdefault(model_id, {
            "provider": provider,
            "name": record.get("name"),
            "context_length": record.get("context_length"),
            "attempts": 0,
            "successes": 0,
            "cost": 0.0,
            "status_counts": {},
            "anomaly_counts": {},
            "latencies_ms": [],
            "success_latencies_ms": [],
            "iterations_seen": set(),
            "returned_models": {},
        })
        provider_row = by_provider.setdefault(provider, {
            "attempts": 0,
            "successes": 0,
            "cost": 0.0,
            "anomaly_counts": {},
            "success_latencies_ms": [],
        })

        model_row["attempts"] += 1
        provider_row["attempts"] += 1
        model_row["iterations_seen"].add(record["iteration"])
        model_row["latencies_ms"].append(record["latency_ms"])
        cost = float(record.get("cost") or 0)
        total_cost += cost
        model_row["cost"] += cost
        provider_row["cost"] += cost

        status = str(record.get("status_code"))
        status_counts[status] = status_counts.get(status, 0) + 1
        model_row["status_counts"][status] = model_row["status_counts"].get(status, 0) + 1

        returned = record.get("returned_model")
        if returned:
            model_row["returned_models"][returned] = model_row["returned_models"].get(returned, 0) + 1

        if record["ok"]:
            model_row["successes"] += 1
            provider_row["successes"] += 1
            model_row["success_latencies_ms"].append(record["latency_ms"])
            provider_row["success_latencies_ms"].append(record["latency_ms"])

        for anomaly in record.get("anomalies", []):
            anomaly_counts[anomaly] = anomaly_counts.get(anomaly, 0) + 1
            model_row["anomaly_counts"][anomaly] = model_row["anomaly_counts"].get(anomaly, 0) + 1
            provider_row["anomaly_counts"][anomaly] = provider_row["anomaly_counts"].get(anomaly, 0) + 1

    all_success_latencies = [record["latency_ms"] for record in records if record["ok"]]
    lower, upper = iqr_bounds(all_success_latencies)
    global_outliers = [
        {"iteration": r["iteration"], "id": r["id"], "latency_ms": r["latency_ms"], "source_run_id": r.get("source_run_id")}
        for r in records
        if r["ok"] and lower is not None and upper is not None and (r["latency_ms"] < lower or r["latency_ms"] > upper)
    ]

    model_summary: dict[str, Any] = {}
    for model_id, row in by_model.items():
        success_latencies = row["success_latencies_ms"]
        model_lower, model_upper = iqr_bounds(success_latencies)
        outliers = [
            value for value in success_latencies
            if model_lower is not None and model_upper is not None and (value < model_lower or value > model_upper)
        ]
        model_summary[model_id] = {
            "provider": row["provider"],
            "name": row["name"],
            "context_length": row["context_length"],
            "attempts": row["attempts"],
            "successes": row["successes"],
            "success_rate": row["successes"] / max(1, row["attempts"]),
            "availability_rate": row["status_counts"].get("200", 0) / max(1, row["attempts"]),
            "cost": row["cost"],
            "status_counts": dict(sorted(row["status_counts"].items())),
            "anomaly_counts": dict(sorted(row["anomaly_counts"].items())),
            "returned_models": dict(sorted(row["returned_models"].items())),
            "iterations_seen": sorted(row["iterations_seen"]),
            "latency_ms": latency_stats(row["latencies_ms"]),
            "success_latency_ms": latency_stats(success_latencies),
            "success_latency_trimmed_mean_ms": trimmed_mean(success_latencies),
            "success_latency_outlier_bounds_ms": {"lower": model_lower, "upper": model_upper},
            "success_latency_outliers_ms": outliers,
        }

    provider_summary: dict[str, Any] = {}
    for provider, row in by_provider.items():
        provider_summary[provider] = {
            "attempts": row["attempts"],
            "successes": row["successes"],
            "success_rate": row["successes"] / max(1, row["attempts"]),
            "cost": row["cost"],
            "anomaly_counts": dict(sorted(row["anomaly_counts"].items())),
            "success_latency_ms": latency_stats(row["success_latencies_ms"]),
        }

    completed_iterations = sorted({record["iteration"] for record in records})
    return {
        "generated_at": utc_now(),
        "completed_iterations": completed_iterations,
        "iteration_count": len(completed_iterations),
        "calls": len(records),
        "successes": sum(1 for record in records if record["ok"]),
        "success_rate": sum(1 for record in records if record["ok"]) / max(1, len(records)),
        "total_reported_cost_usd": total_cost,
        "status_counts": dict(sorted(status_counts.items())),
        "anomaly_counts": dict(sorted(anomaly_counts.items(), key=lambda item: (-item[1], item[0]))),
        "success_latency_ms": latency_stats(all_success_latencies),
        "success_latency_trimmed_mean_ms": trimmed_mean(all_success_latencies),
        "success_latency_outlier_bounds_ms": {"lower": lower, "upper": upper},
        "success_latency_outliers": global_outliers,
        "models": dict(sorted(model_summary.items())),
        "providers": dict(sorted(provider_summary.items())),
        "top_models_by_success_rate": sorted(
            model_summary.items(),
            key=lambda item: (-item[1]["success_rate"], item[1]["success_latency_ms"]["median"] if item[1]["success_latency_ms"]["median"] is not None else 10**9, item[0]),
        )[:15],
        "top_models_by_trimmed_latency": sorted(
            [(model, row) for model, row in model_summary.items() if row["success_latency_trimmed_mean_ms"] is not None],
            key=lambda item: (item[1]["success_latency_trimmed_mean_ms"], -item[1]["success_rate"]),
        )[:15],
        "most_rate_limited_models": sorted(
            model_summary.items(),
            key=lambda item: (-item[1]["anomaly_counts"].get("rate_limited", 0), item[0]),
        )[:15],
    }


def write_aggregate_markdown(aggregate: dict[str, Any], path: Path) -> None:
    lines = [
        "# Scheduled OpenRouter Free Model Census Aggregate",
        "",
        f"Generated: {aggregate['generated_at']}",
        "",
        "## Summary",
        "",
        f"- Completed iterations: `{aggregate['iteration_count']}`",
        f"- Source-aware sampled cycles: `{aggregate.get('source_iteration_count', aggregate['iteration_count'])}`",
        f"- Calls logged: `{aggregate['calls']}`",
        f"- Successes: `{aggregate['successes']}`",
        f"- Success rate: `{aggregate['success_rate']:.2%}`",
        f"- Total reported cost: `${aggregate['total_reported_cost_usd']:.2f}`",
        f"- Status counts: `{json.dumps(aggregate['status_counts'], sort_keys=True)}`",
        f"- Anomaly counts: `{json.dumps(aggregate['anomaly_counts'], sort_keys=True)}`",
        f"- Success latency median: `{aggregate['success_latency_ms']['median']}` ms",
        f"- Success latency p95: `{aggregate['success_latency_ms']['p95']}` ms",
        f"- Success latency trimmed mean: `{aggregate['success_latency_trimmed_mean_ms']}` ms",
        f"- Success latency outliers: `{len(aggregate['success_latency_outliers'])}`",
        "",
        "## Top Models By Success Rate",
        "",
        "| Model | Attempts | Successes | Success Rate | Median Success Latency ms | Trimmed Mean ms | Anomalies |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for model_id, row in aggregate["top_models_by_success_rate"]:
        lines.append(
            f"| `{model_id}` | `{row['attempts']}` | `{row['successes']}` | `{row['success_rate']:.2%}` | "
            f"`{row['success_latency_ms']['median']}` | `{row['success_latency_trimmed_mean_ms']}` | "
            f"`{json.dumps(row['anomaly_counts'], sort_keys=True)}` |"
        )
    lines.extend(["", "## Fastest Reliable Models", "", "| Model | Attempts | Successes | Success Rate | Trimmed Mean ms | Median ms |", "|---|---:|---:|---:|---:|---:|"])
    for model_id, row in aggregate["top_models_by_trimmed_latency"]:
        lines.append(
            f"| `{model_id}` | `{row['attempts']}` | `{row['successes']}` | `{row['success_rate']:.2%}` | "
            f"`{row['success_latency_trimmed_mean_ms']}` | `{row['success_latency_ms']['median']}` |"
        )
    lines.extend(["", "## Most Rate Limited", "", "| Model | Attempts | Rate Limits | Success Rate |", "|---|---:|---:|---:|"])
    for model_id, row in aggregate["most_rate_limited_models"]:
        lines.append(f"| `{model_id}` | `{row['attempts']}` | `{row['anomaly_counts'].get('rate_limited', 0)}` | `{row['success_rate']:.2%}` |")
    path.write_text("\n".join(lines))


def load_records(series_dirs: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for series_dir in series_dirs:
        raw_path = series_dir / "raw_calls.jsonl"
        if not raw_path.exists():
            raise FileNotFoundError(f"Missing raw census file: {raw_path}")
        for record in read_jsonl(raw_path):
            records.append({**record, "source_run_id": series_dir.name})
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Collate one or more OpenRouter free model census series into one aggregate report")
    parser.add_argument("series_dirs", nargs="+", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--run-id", default=f"collated_free_census_{utc_now().replace(':', '').replace('-', '')}")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    output_dir = args.output_dir or root / "benchmarks" / "series" / args.run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    records = load_records(args.series_dirs)
    aggregate = aggregate_records(records)
    aggregate["source_run_ids"] = [path.name for path in args.series_dirs]
    aggregate["source_iteration_count"] = len({(record.get("source_run_id"), record.get("iteration")) for record in records})
    aggregate["collated_at"] = utc_now()

    aggregate_json_path = output_dir / "aggregate.json"
    aggregate_md_path = output_dir / "aggregate.md"
    raw_path = output_dir / "raw_calls.jsonl"

    raw_path.write_text("\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n")
    aggregate_json_path.write_text(json.dumps(aggregate, indent=2))
    write_aggregate_markdown(aggregate, aggregate_md_path)

    print(f"RESULT collated_census source_runs={len(args.series_dirs)} calls={len(records)} output={aggregate_md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
