from fastapi.testclient import TestClient
from app.main import app


def test_models_endpoint():
    with TestClient(app) as client:
        response = client.get("/v1/models")
    assert response.status_code == 200
    assert any(m["id"] == "SystemVirtue/quorum-free-balanced" for m in response.json()["data"])


def test_chat_completion_mock():
    with TestClient(app) as client:
        response = client.post("/v1/chat/completions", json={
            "model": "SystemVirtue/quorum-free-balanced",
            "messages": [{"role": "user", "content": "Implement an LRU cache in Python"}],
            "stream": False,
        })
    assert response.status_code == 200
    data = response.json()
    assert data["quorum_metadata"]["marginal_cost_usd"] == 0.0
    assert "System Virtue QUORUM metadata" in data["choices"][0]["message"]["content"]
