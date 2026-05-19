from app.hub.classifier import deterministic_classify
from app.hub.selection import UserPrefs, select_council
from app.registry.openrouter import FreeModelRegistry
import pytest


def test_selection_is_family_diverse():
    registry = FreeModelRegistry()
    pool = registry.seed_pool()
    profile = deterministic_classify("Implement a function in Python")
    council = select_council(profile, pool, "balanced", UserPrefs())
    families = [m.model.family for m in council]
    assert len(council) == 4
    assert len(set(families)) >= 3


@pytest.mark.asyncio
async def test_registry_overlays_census_health_snapshot():
    registry = FreeModelRegistry()
    registry._health_snapshot = {
        "models": {
            "example/provider:free": {
                "generated_at": "2026-05-19T00:00:00+00:00",
                "health_score": 0.42,
                "telemetry": {
                    "p50_latency_ms": 1234,
                    "p95_latency_ms": 5678,
                    "availability_24h": 0.25,
                    "recent_success_rate": 0.25,
                    "rate_limit_hits_1h": 7,
                    "json_parse_success_24h": 0.75,
                    "timeout_score": 0.9,
                    "malformed_json_rate_24h": 0.25,
                },
            }
        }
    }
    model = await registry._enrich({
        "id": "example/provider:free",
        "context_length": 8192,
        "pricing": {"prompt": "0", "completion": "0"},
    })
    assert model.health_score == 0.42
    assert model.telemetry.p50_latency_ms == 1234
    assert model.last_verified == "2026-05-19T00:00:00+00:00"
