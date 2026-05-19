# Self-Hosting

```bash
cp .env.example .env
# Add OPENROUTER_API_KEY for live free-model calls.
docker compose up --build
```

Services:

- `postgres`: PostgreSQL 16 with initial schema
- `redis`: Redis 7
- `orchestrator`: FastAPI QUORUM brain on `localhost:8080`
- `worker`: Redis Streams worker scaffold
- `litellm`: OpenAI-compatible proxy on `localhost:4000`
- `webui`: Phase 1 web shell on `localhost:3000`

Paid models are disabled by default through `ALLOW_PAID_MODELS=false`.
