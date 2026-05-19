from dataclasses import dataclass, field
from app.core.schemas import ClassificationProfile, CouncilMember, FreeModel
from app.hub.prompts import critique_template_for_class
from app.hub.roles import ROLE_CAPABILITY_MAP


LABELS = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta"]


@dataclass
class UserPrefs:
    preferred: list[str] = field(default_factory=list)
    banned: list[str] = field(default_factory=list)


def select_council(profile: ClassificationProfile, free_pool: list[FreeModel], mode: str, user_prefs: UserPrefs) -> list[CouncilMember]:
    sizes = {"fast": 3, "balanced": 4, "deep": 6, "adversarial": 6, "auditor": 4}
    size = sizes[mode]
    roles = list(profile.recommended_roles)
    while len(roles) < size:
        roles.append("critic" if mode == "adversarial" and len(roles) >= 3 else "synthesizer")
    roles = roles[:size]

    candidates = [
        m for m in free_pool
        if m.health_score >= 0.5
        and m.context_length >= profile.min_context_tokens
        and m.id not in user_prefs.banned
    ]
    if not candidates:
        candidates = [m for m in free_pool if m.id not in user_prefs.banned]

    council: list[CouncilMember] = []
    used_families: set[str] = set()
    for idx, role in enumerate(roles):
        pool = [m for m in candidates if m.family not in used_families] or candidates
        scored = sorted(((score_for_role(m, role, profile), m) for m in pool), key=lambda item: item[0], reverse=True)
        if not scored:
            break
        best = scored[0][1]
        council.append(CouncilMember(
            label=LABELS[idx],
            role=role,
            model=best,
            critique_template=critique_template_for_class(best.capabilities.model_class),
        ))
        used_families.add(best.family)
    return council


def score_for_role(m: FreeModel, role: str, profile: ClassificationProfile) -> float:
    cs = m.capabilities.coding_strength
    lang = profile.primary_language
    code_fit = cs.get(lang, cs["general"]) if profile.weights["code"] > 0.3 else 5.0
    cap_dot = 0.0
    for key, weight in profile.weights.items():
        value = getattr(m.capabilities, key, 5.0)
        if isinstance(value, dict):
            value = value.get(lang, value.get("general", 5.0))
        cap_dot += value * weight
    role_capability = ROLE_CAPABILITY_MAP.get(role, "reasoning")
    role_value = getattr(m.capabilities, role_capability, 5.0)
    if isinstance(role_value, dict):
        role_value = role_value.get(lang, role_value.get("general", 5.0))
    return (
        0.40 * code_fit
        + 0.25 * cap_dot
        + 0.15 * role_value
        + 0.10 * m.health_score * 10
        + 0.10 * m.capabilities.json_reliability
    )
