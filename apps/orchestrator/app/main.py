from fastapi import FastAPI, WebSocket
from app.api.v1.routes import router, registry

app = FastAPI(title="System Virtue QUORUM Orchestrator", version="0.1.0")
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    await registry.refresh()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    await registry.list_free()
    return {"status": "ready", "postgres": "configured", "redis": "configured", "openrouter": "configured_or_mock"}


@app.websocket("/ws/quorum/{session_id}")
async def ws_quorum(websocket: WebSocket, session_id: str):
    await websocket.accept()
    await websocket.send_json({"event": "quorum.session.created", "session_id": session_id, "mode": "balanced"})
    await websocket.close()
