# API

Required endpoints implemented by the orchestrator:

```text
GET  /v1/models
POST /v1/chat/completions
GET  /quorum/models/free
POST /quorum/session
GET  /quorum/session/{id}
POST /quorum/session/{id}/approve
GET  /quorum/session/{id}/events
POST /quorum/session/{id}/cancel
GET  /quorum/presets
POST /quorum/presets
GET  /health
GET  /ready
GET  /ws/quorum/{id}
```

Request extension body:

```json
{
  "SystemVirtue": {
    "require_approval": false,
    "preferred_models": [],
    "banned_models": [],
    "show_trace": "standard",
    "allow_paid": false,
    "consensus_mode": "hub_synthesis"
  }
}
```

Headers mirror supported fields, including `X-SystemVirtue-Mode` and `X-SystemVirtue-Consensus-Mode`.
