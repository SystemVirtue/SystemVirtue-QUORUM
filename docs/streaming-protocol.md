# Streaming Protocol

SSE emits OpenAI-compatible chunks. QUORUM events are represented as tool-call deltas so clients that ignore tool calls continue to receive the final assistant answer.

Event taxonomy:

```text
quorum.session.created
quorum.council.proposed
quorum.council.approved
quorum.phase.started
quorum.member.token
quorum.member.completed
quorum.member.dropped
quorum.phase.completed
quorum.consensus.computed
quorum.final.synthesised
quorum.escalation.recommended
quorum.error
```

Phase 3 WebSocket uses `/ws/quorum/{session_id}` for the same events plus rich UI payloads.
