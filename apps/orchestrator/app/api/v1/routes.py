import time
import uuid
from fastapi import APIRouter, Header, Response
from fastapi.responses import StreamingResponse
from app.core.schemas import ChatCompletionRequest
from app.pipeline.quorum import event_stream, mode_from_model, prompt_from_messages, run_quorum
from app.registry.openrouter import FreeModelRegistry
from app.streaming.events import sse

router = APIRouter()
registry = FreeModelRegistry()
SESSIONS: dict[str, dict] = {}


ALIASES = [
    "SystemVirtue/quorum-free-fast",
    "SystemVirtue/quorum-free-balanced",
    "SystemVirtue/quorum-free-deep",
    "SystemVirtue/quorum-free-adversarial",
    "SystemVirtue/quorum-free-auditor",
    "SystemVirtue/single-free-best",
    "SystemVirtue/frontier-escalate",
]


@router.get("/v1/models")
async def models():
    free = await registry.list_free()
    return {
        "object": "list",
        "data": [{"id": alias, "object": "model", "owned_by": "SystemVirtue"} for alias in ALIASES]
        + [{"id": m.id, "object": "model", "owned_by": "openrouter-free"} for m in free],
    }


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest, response: Response, x_systemvirtue_mode: str | None = Header(None), x_systemvirtue_consensus_mode: str | None = Header(None)):
    prompt = prompt_from_messages(request.messages)
    mode = x_systemvirtue_mode or mode_from_model(request.model)
    if x_systemvirtue_consensus_mode:
        request.SystemVirtue.consensus_mode = x_systemvirtue_consensus_mode
    if request.stream:
        return StreamingResponse(sse(event_stream(prompt, mode, request.SystemVirtue, registry)), media_type="text/event-stream")

    result = await run_quorum(prompt, mode, request.SystemVirtue, registry)
    response.headers["X-SystemVirtue-Mode"] = result.metadata["mode"]
    response.headers["X-SystemVirtue-Consensus-Score"] = str(result.metadata["consensus_score"])
    response.headers["X-SystemVirtue-Marginal-Cost-USD"] = "0.00"
    content = fold_metadata(result.final_answer, result.metadata)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": request.model,
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "quorum_metadata": result.metadata,
    }


@router.get("/quorum/models/free")
async def free_models():
    return {"data": [m.model_dump() for m in await registry.list_free()]}


@router.post("/quorum/session")
async def create_session(request: ChatCompletionRequest):
    sid = str(uuid.uuid4())
    prompt = prompt_from_messages(request.messages)
    profile_mode = mode_from_model(request.model)
    SESSIONS[sid] = {"id": sid, "status": "pending", "mode": profile_mode, "prompt": prompt, "request": request}
    return {"session_id": sid, "status": "pending", "mode": profile_mode}


@router.get("/quorum/session/{session_id}")
async def get_session(session_id: str):
    return SESSIONS.get(session_id, {"id": session_id, "status": "not_found"})


@router.post("/quorum/session/{session_id}/approve")
async def approve_session(session_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        return {"id": session_id, "status": "not_found"}
    session["status"] = "approved"
    return session


@router.post("/quorum/session/{session_id}/cancel")
async def cancel_session(session_id: str):
    session = SESSIONS.get(session_id, {"id": session_id})
    session["status"] = "cancelled"
    SESSIONS[session_id] = session
    return session


@router.get("/quorum/session/{session_id}/events")
async def session_events(session_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        async def missing():
            yield {"error": "session not found"}
        return StreamingResponse(sse(missing()), media_type="text/event-stream")
    return StreamingResponse(sse(event_stream(session["prompt"], session["mode"], session["request"].SystemVirtue, registry)), media_type="text/event-stream")


@router.get("/quorum/presets")
async def get_presets():
    return {"data": [
        {"name": "Free Coding Council", "mode": "balanced"},
        {"name": "Free DevOps Council", "mode": "balanced"},
        {"name": "Free Security Review", "mode": "adversarial"},
        {"name": "Free Long-Context", "mode": "deep"},
        {"name": "Fast Cheap Debugger", "mode": "fast"},
        {"name": "Architecture Deep Review", "mode": "deep"},
        {"name": "Auditor (no synthesis)", "mode": "auditor"},
    ]}


@router.post("/quorum/presets")
async def save_preset(payload: dict):
    return {"status": "saved", "preset": payload}


def fold_metadata(answer: str, metadata: dict) -> str:
    rows = [
        "<details><summary>System Virtue QUORUM metadata</summary>",
        "",
        f"Mode: {metadata['mode']}",
        f"Consensus score: {metadata['consensus_score']}",
        f"Model cost: ${metadata['marginal_cost_usd']:.2f} — OpenRouter free models",
        f"Stages: {', '.join(metadata['stages_completed'])}",
        "",
        "</details>",
    ]
    return answer + "\n\n" + "\n".join(rows)
