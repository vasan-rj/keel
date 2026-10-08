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

## Manual two-session smoke test (Slice 1)

1. `docker compose up -d db`
2. `pip install -e ".[dev]" && python -m keel.scripts.seed`
3. `python -m keel.server`  (listens on :8000, MCP at /mcp)
4. Session A (token `dev-token`, `X-Keel-Session: A`): register_session → record_decision
   `{statement: "orders API uses cursor pagination", rationale: "...", scope_tags: ["api:orders"]}`.
5. Session B (token `teammate-token`, `X-Keel-Session: B`): register_session → get_context
   `{scope_tags: ["api:orders"]}` returns A's decision. Cross-session fetch confirmed.
