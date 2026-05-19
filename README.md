# System Virtue QUORUM

System Virtue QUORUM is an open-source-first, OpenAI-compatible multi-agent coding platform. QUORUM-FREE is the primary/default experience: multiple OpenRouter free-tier models form a structured engineering council through parallel generation, anonymised critique, revision, consensus, and synthesis.

Honest product claim:

> "Better consistency, issue coverage, and transparency than one frontier model — for most coding, debugging, refactoring, and architecture tasks — at $0 marginal cost."

## Quick Start

```bash
cp .env.example .env
# add OPENROUTER_API_KEY, or leave the placeholder for local mock mode
docker compose up --build
```

Open:

- Web shell: http://localhost:3000
- OpenAI-compatible endpoint: `http://localhost:4000/v1`
- Orchestrator docs: http://localhost:8080/docs

Default model alias:

```text
SystemVirtue/quorum-free-balanced
```

## CLI Prototype

Phase 0 is runnable directly:

```bash
cd apps/orchestrator
pip install -e ".[test]"
python cli.py --mode balanced "Implement an LRU cache in Python with tests"
```

With no real OpenRouter key, the CLI uses deterministic mock model calls so the orchestration loop, metadata, and tests remain runnable.

## Modes

- `SystemVirtue/quorum-free-fast`
- `SystemVirtue/quorum-free-balanced`
- `SystemVirtue/quorum-free-deep`
- `SystemVirtue/quorum-free-adversarial`
- `SystemVirtue/quorum-free-auditor`
- `SystemVirtue/single-free-best`
- `SystemVirtue/frontier-escalate`

Paid escalation is disabled by default. QUORUM-FREE always reports `marginal_cost_usd: 0.00`.

## Current Build Status

This repository contains the Phase 0/early Phase 1 implementation scaffold:

- Docker Compose contract with postgres, redis, orchestrator, worker, litellm, and webui
- FastAPI OpenAI-compatible `/v1/chat/completions`
- Dynamic OpenRouter free-model registry with seed fallback
- Deterministic classifier fallback
- Family-diverse council selection
- Critique prompt templates
- Parallel generation, critique/revision scaffolds, deterministic consensus, auditor mode
- SSE tool-call event chunks
- PostgreSQL schema plus compatibility views
- Eval harness scaffold and 20 seed prompts

No benchmark results are claimed until the harness is run.
