from app.security.redaction import redact


def test_redacts_common_secrets():
    text = "OPENAI_API_KEY=sk-abc123456789999\nAuthorization: Bearer token.secret.value"
    out = redact(text)
    assert "sk-abc" not in out
    assert "Bearer token" not in out
    assert "[REDACTED]" in out
