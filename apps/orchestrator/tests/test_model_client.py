import pytest

from app.pipeline import model_client
from app.pipeline.model_client import (
    ModelCallError,
    default_max_tokens_for_model,
    enforce_free_model,
    is_placeholder_key,
    retry_after_seconds,
    validate_openrouter_free_model,
)


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


def test_reasoning_models_get_larger_default_token_budget():
    assert default_max_tokens_for_model("arcee-ai/trinity-large-thinking:free") == 4096
    assert default_max_tokens_for_model("openai/gpt-oss-120b:free") is None


def test_retry_after_parses_error_metadata_headers():
    class Response:
        headers = {"Retry-After": "9"}

    assert retry_after_seconds(Response(), {}) == 9
    assert retry_after_seconds(None, {
        "error": {
            "metadata": {
                "retry_after_seconds_raw": 8.5,
            }
        }
    }) == 8.5


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "data": [
                {"id": "ok/model:free", "pricing": {"prompt": "0", "completion": "0"}},
                {"id": "paid/model", "pricing": {"prompt": "0.1", "completion": "0.1"}},
            ]
        }


class FakeClient:
    async def get(self, *args, **kwargs):
        return FakeResponse()


@pytest.mark.asyncio
async def test_live_free_pool_validation_blocks_models_not_reported_free(monkeypatch):
    monkeypatch.setattr(model_client.settings, "allow_paid_models", False)
    monkeypatch.setattr(model_client.settings, "openrouter_api_key", "sk-or-v1-real-looking-key")
    monkeypatch.setattr(model_client, "_free_model_cache", None)
    monkeypatch.setattr(model_client, "_free_model_cache_checked_at", 0)
    await validate_openrouter_free_model("ok/model:free", FakeClient())
    with pytest.raises(ModelCallError):
        await validate_openrouter_free_model("paid/model", FakeClient())
