from app.hub.classifier import deterministic_classify


def test_deterministic_classifier_security_mode():
    profile = deterministic_classify("Review this auth middleware for csrf and injection vulnerabilities")
    assert profile.task_type == "security_review"
    assert profile.recommended_mode == "adversarial"
    assert profile.risk_level == "high"


def test_deterministic_classifier_python():
    profile = deterministic_classify("def add(a, b): return a + b\nWrite tests")
    assert profile.primary_language == "python"
    assert profile.task_type == "test_generation"
