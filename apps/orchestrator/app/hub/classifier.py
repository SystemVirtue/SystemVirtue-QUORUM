import json
import re
from .roles import ROLE_POOLS, STATIC_WEIGHTS_TABLE
from app.core.schemas import ClassificationProfile


def deterministic_classify(prompt: str) -> ClassificationProfile:
    lower = prompt.lower()
    lang = "none"
    if re.search(r"\bdef \w+\(|\bimport \w+|\bclass \w+:", prompt):
        lang = "python"
    elif re.search(r"\bfunction \w+\(|\bconst \w+ =|\binterface \w+", prompt):
        lang = "typescript"
    elif re.search(r"\bfn \w+\(|\bpub fn |\bimpl ", prompt):
        lang = "rust"
    elif re.search(r"\bfunc \w+\(|\bpackage \w+", prompt):
        lang = "go"
    elif re.search(r"SELECT |INSERT |CREATE TABLE", prompt, re.I):
        lang = "sql"

    if any(k in lower for k in ("error", "traceback", "fails", "broken", "bug")):
        task, mode = "debugging", "balanced"
    elif any(k in lower for k in ("design", "architect", "structure", "plan")):
        task, mode = "architecture", "deep"
    elif any(k in lower for k in ("security", "auth", "vulnerab", "injection", "csrf")):
        task, mode = "security_review", "adversarial"
    elif re.search(r"\b(tests?|specs?|coverage)\b", lower):
        task, mode = "test_generation", "balanced"
    elif re.search(r"\b(refactor|cleanup|migrate)\b", lower):
        task, mode = "refactor", "deep"
    elif any(k in lower for k in ("review", "audit", "find issues")):
        task, mode = "code_review", "auditor"
    elif lang != "none" or any(k in lower for k in ("function", "implement", "code")):
        task, mode = "code_generation", "balanced"
    else:
        task, mode = "general_qa", "fast"

    weights = STATIC_WEIGHTS_TABLE[task]
    compatibility = {
        "task_type_legacy": {
            "database_migration": "database",
            "frontend_ui": "frontend",
            "test_generation": "testing",
            "general_qa": "general",
        }.get(task, task),
        "required_capabilities": {
            "coding": weights["code"],
            "reasoning": weights["reasoning"],
            "critique": weights["critique"],
            "long_context": weights["long_context"],
            "security": 0.8 if task == "security_review" else 0.2,
        },
    }
    return ClassificationProfile(
        task_type=task,
        primary_language=lang,
        weights=weights,
        estimated_difficulty=5,
        min_context_tokens=4000,
        risk_level="high" if task == "security_review" else "medium",
        recommended_mode=mode,
        recommended_roles=ROLE_POOLS[task],
        rationale=f"deterministic fallback: matched task={task}",
        compatibility=compatibility,
    )


def parse_classification(raw: str) -> ClassificationProfile | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    try:
        return ClassificationProfile.model_validate(data)
    except Exception:
        return None
