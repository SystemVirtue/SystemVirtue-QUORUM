import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def latency_score(p50_latency_ms: int) -> float:
    return 1 - min(1, p50_latency_ms / 15000)


def health_score(row: dict[str, Any]) -> float:
    p50 = int(row["success_latency_ms"]["median"] or row["latency_ms"]["median"] or 15000)
    availability = float(row["success_rate"])
    recent_success = float(row["success_rate"])
    malformed = malformed_rate(row)
    context_score = 1.0 if int(row.get("context_length") or 0) >= 8192 else 0.3
    return round(
        0.30 * availability
        + 0.25 * recent_success
        + 0.20 * latency_score(p50)
        + 0.15 * (1 - malformed)
        + 0.10 * context_score,
        4,
    )


def malformed_rate(row: dict[str, Any]) -> float:
    attempts = max(1, int(row["attempts"]))
    anomalies = row.get("anomaly_counts", {})
    malformed = int(anomalies.get("empty_output", 0)) + int(anomalies.get("instruction_following_failed", 0))
    return min(1.0, malformed / attempts)


def timeout_score(row: dict[str, Any]) -> float:
    attempts = max(1, int(row["attempts"]))
    hard_timeouts = int(row.get("anomaly_counts", {}).get("hard_timeout", 0))
    return round(1 - min(1.0, hard_timeouts / attempts), 4)


def export_model(model_id: str, row: dict[str, Any]) -> dict[str, Any]:
    p50 = int(row["success_latency_ms"]["median"] or row["latency_ms"]["median"] or 15000)
    p95 = int(row["success_latency_ms"]["p95"] or row["latency_ms"]["p95"] or max(p50, 20000))
    malformed = malformed_rate(row)
    return {
        "health_score": health_score(row),
        "telemetry": {
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "availability_24h": round(float(row["success_rate"]), 4),
            "recent_success_rate": round(float(row["success_rate"]), 4),
            "rate_limit_hits_1h": int(row.get("anomaly_counts", {}).get("rate_limited", 0)),
            "json_parse_success_24h": round(1 - malformed, 4),
            "timeout_score": timeout_score(row),
            "malformed_json_rate_24h": round(malformed, 4),
        },
        "source": {
            "attempts": row["attempts"],
            "successes": row["successes"],
            "http_availability_rate": row["availability_rate"],
            "status_counts": row["status_counts"],
            "anomaly_counts": row["anomaly_counts"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export census aggregate data into an orchestrator model-health snapshot")
    parser.add_argument("aggregate_json", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    output = args.output or root / "seed" / "free_model_census_health.json"
    aggregate = json.loads(args.aggregate_json.read_text())
    models = {
        model_id: export_model(model_id, row)
        for model_id, row in aggregate.get("models", {}).items()
    }
    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_aggregate": str(args.aggregate_json),
        "model_count": len(models),
        "models": models,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    print(f"RESULT exported_census_health models={len(models)} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
