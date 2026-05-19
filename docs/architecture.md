# Architecture

System Virtue QUORUM is CLI-first. The first production surface is an OpenAI-compatible FastAPI orchestrator behind LiteLLM. The core workflow is visible in code and trace output:

```text
Prompt classification
→ dynamic free-model discovery
→ transparent council proposal
→ user approval / override
→ parallel generation
→ anonymized critique
→ revision
→ consensus extraction
→ final synthesis
→ trace + disagreements + provenance
```

The orchestrator owns classification, selection, fan-out, critique, revision, consensus, synthesis, streaming, and persistence. Redis is reserved for transient session state, Redis Streams/PubSub events, rate limit buckets, execution queue, model registry cache, and timeout coordination. PostgreSQL stores users, encrypted provider keys, model health, sessions, runs, claims, presets, eval scores, and audit logs.

The self-hosted product is the full product minus hosted convenience features.
