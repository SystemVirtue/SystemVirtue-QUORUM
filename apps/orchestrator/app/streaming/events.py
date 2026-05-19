import json
from typing import Any, AsyncIterator


def openai_tool_event(event_name: str, payload: dict[str, Any], idx: int) -> dict[str, Any]:
    return {
        "id": f"chatcmpl-quorum-{idx}",
        "object": "chat.completion.chunk",
        "choices": [{
            "index": 0,
            "delta": {
                "role": "tool",
                "tool_calls": [{
                    "id": f"q_evt_{idx}",
                    "type": "function",
                    "function": {"name": event_name, "arguments": json.dumps(payload)},
                }],
            },
        }],
    }


def assistant_chunk(token: str, idx: int) -> dict[str, Any]:
    return {"id": f"chatcmpl-quorum-{idx}", "object": "chat.completion.chunk", "choices": [{"index": 0, "delta": {"role": "assistant", "content": token}}]}


async def sse(iterable: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    async for item in iterable:
        yield f"data: {json.dumps(item)}\n\n"
    yield "data: [DONE]\n\n"
