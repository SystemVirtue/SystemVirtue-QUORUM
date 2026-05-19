import pytest

from app.pipeline import model_client
from app.pipeline.model_client import ModelCallError, enforce_free_model, is_placeholder_key


def test_placeholder_key_does_not_match_real_openrouter_prefix():
    assert is_placeholder_key("sk-or-your-key-here")
    assert not is_placeholder_key("sk-or-v1-real-looking-key")


def test_free_only_gate_blocks_paid_models(monkeypatch):
    monkeypatch.setattr(model_client.settings, "allow_paid_models", False)
    enforce_free_model("deepseek/deepseek-v4-flash:free")
    with pytest.raises(ModelCallError):
        enforce_free_model("anthropic/claude-sonnet-4.5")


def test_free_only_gate_allows_openrouter_free_router(monkeypatch):
    monkeypatch.setattr(model_client.settings, "allow_paid_models", False)
    enforce_free_model("openrouter/free")
