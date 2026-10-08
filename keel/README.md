# keel (provisional name)

> **Name is a placeholder** (OPEN_QUESTIONS #1, unsettled). Do not harden into domains or published identifiers.

Intent & decision ledger — Slice 1: server skeleton + `register_session`, `get_context`, `record_decision`.

## Dev

```
docker compose up -d db          # Postgres 16 + pgvector on host port 5433
pip install -e ".[dev]"          # (or: uv pip install -e ".[dev]")
cp .env.example .env
python -m keel.scripts.seed
python -m keel.server            # MCP streamable HTTP on :8000 (route /mcp)
```

## Test

```
docker compose up -d db          # must be running; creates keel + keel_test
export KEEL_TEST_DATABASE_URL=postgresql://keel:keel@localhost:5433/keel_test
pytest
```
