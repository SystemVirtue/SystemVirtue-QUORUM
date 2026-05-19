from app.hub.classifier import deterministic_classify
from app.hub.selection import UserPrefs, select_council
from app.registry.openrouter import FreeModelRegistry


def test_selection_is_family_diverse():
    registry = FreeModelRegistry()
    pool = registry.seed_pool()
    profile = deterministic_classify("Implement a function in Python")
    council = select_council(profile, pool, "balanced", UserPrefs())
    families = [m.model.family for m in council]
    assert len(council) == 4
    assert len(set(families)) >= 3
