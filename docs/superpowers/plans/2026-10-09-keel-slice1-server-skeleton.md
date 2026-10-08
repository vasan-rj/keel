# Keel Slice 1 — Server Skeleton + 3 Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the `keel` MCP server over streamable HTTP with a Postgres/pgvector store, an append-only hash-chained event log, and three working tools (`register_session`, `get_context`, `record_decision`) usable across two sessions.

**Architecture:** Python MCP server (official SDK, streamable HTTP) backed by Postgres 16 + pgvector via Docker Compose. Tool handlers are plain async functions that take a resolved `Principal` (project + person + session, from HTTP headers) plus a connection pool, so they are unit-testable without the transport. Every state change is written as a hash-chained `event` in the same transaction as the domain row. `record_decision` serializes its insert per scope tag with a Postgres advisory lock so the conflict guarantee is structural from day one; the LLM conflict judgment itself is a documented stub landing in a later slice.

**Tech Stack:** Python 3.12, `mcp` (official SDK, streamable HTTP), `asyncpg`, Postgres 16 (`pgvector/pgvector:pg16`), `pytest` + `pytest-asyncio`, `httpx` (transport test), Docker Compose.

**Spec:** `context/ARCHITECTURE.md` v1.0 (§3 components, §4 data model, §5 MCP tool contract, §7/§7.1 conflict + serialization, §11 security). Settled decisions in `context/OPEN_QUESTIONS.md` (Q3 default `active`, Q6 own-the-store plain Postgres, Q9 GCP later).

## Global Constraints

- **Name is provisional.** `keel` is a placeholder (OPEN_QUESTIONS #1, unsettled). Confine it to package/dir/module names only; no domains, no published identifiers. Add a one-line provisional-name note in the README.
- **Python 3.12.** Async throughout; `asyncpg` only (no ORM).
- **Append-only.** Every state change writes an `event` row with a SHA-256 hash chain (`prev_hash` → `hash`); current state is derived. No `UPDATE`/`DELETE` of history.
- **New decisions default to `status = 'active'`** (OPEN_QUESTIONS Q3).
- **`record_decision` insert is serialized per scope tag** inside one transaction via `pg_advisory_xact_lock` (ARCHITECTURE §7.1). Locks acquired in sorted order to avoid deadlock.
- **Scope tags are normalized server-side** before storage or lookup (ARCHITECTURE §4; scope-tag mismatch is the single silent point of failure — treat normalization as core).
- **Deep-tier identity = project-scoped bearer token** per person (ARCHITECTURE §11); the session is identified by a separate `X-Keel-Session` header.
- **Every tool response carries an `inbox` block** `{"alerts": [], "handoffs": [], "new_lessons": []}` (ARCHITECTURE §5 piggyback). Shape is stable now; contents populate in the propagation slice.
- **Deterministic hashing/normalization.** Same input → same output (required by the audit trail). Time values that enter a hash are generated in Python as timezone-aware UTC and passed in, never read back from the DB clock.

## Review Focus

- **Empty / whitespace-only `scope_tags` on `record_decision`** — a decision with no scope connects to nothing and fails silently later; must be rejected with a clear error, no partial write. (Task 8)
- **Concurrent `record_decision` on the same scope tag** — two racing inserts must serialize; both succeed and the event hash chain stays valid (no forked `prev_hash`). (Task 8)
- **Tag-variant lookup** — a decision recorded as `"API: Orders"` must be found by `get_context(scope_tags=["api:orders"])`; normalization must apply equally on write and read. (Task 7)
- **`supersedes` referencing a missing or cross-project decision** — must error atomically with no decision row and no event written. (Task 8)
- **Unknown / missing bearer token** — transport returns 401 and no handler runs. (Task 9)

---

## File Structure

- `keel/pyproject.toml` — package + deps + pytest config.
- `keel/docker-compose.yml` — `db` (pgvector/pg16) + `api` services.
- `keel/Dockerfile` — api image.
- `keel/.env.example` — `DATABASE_URL`, `KEEL_DEV_TOKEN`.
- `keel/keel/config.py` — env-driven `Settings`.
- `keel/keel/db/pool.py` — asyncpg pool lifecycle.
- `keel/keel/db/schema.sql` — full v0 schema (all tables; only 3 tools wired).
- `keel/keel/events.py` — append-only hash-chained event writer + chain validator.
- `keel/keel/scope.py` — scope-tag normalization + reconciliation.
- `keel/keel/repo.py` — data access (project/person/participant/decision).
- `keel/keel/principal.py` — `Principal` dataclass.
- `keel/keel/inbox.py` — piggyback inbox builder.
- `keel/keel/conflict.py` — conflict-check stub (called inside the locked txn).
- `keel/keel/tools/register_session.py`, `get_context.py`, `record_decision.py` — tool handlers.
- `keel/keel/server.py` — MCP streamable-HTTP app, header→Principal middleware, tool registration.
- `keel/scripts/seed.py` — seed demo project + two persons/tokens.
- `keel/README.md` — run instructions + provisional-name note.
- `keel/tests/` — one test module per unit above + `conftest.py`.

---

### Task 1: Project scaffold, config, DB pool, schema, compose

**Files:**
- Create: `keel/pyproject.toml`, `keel/.env.example`, `keel/docker-compose.yml`, `keel/Dockerfile`, `keel/README.md`
- Create: `keel/keel/__init__.py`, `keel/keel/config.py`, `keel/keel/db/__init__.py`, `keel/keel/db/pool.py`, `keel/keel/db/schema.sql`
- Create: `keel/tests/__init__.py`, `keel/tests/conftest.py`, `keel/tests/test_db.py`

**Interfaces:**
- Produces: `Settings(database_url: str)` via `keel.config.get_settings()`.
- Produces: `keel.db.pool.init_pool(dsn: str) -> asyncpg.Pool`, `get_pool() -> asyncpg.Pool`, `close_pool() -> None`, `apply_schema(conn) -> None` (executes `schema.sql`).
- Produces (test): `conftest.py` fixtures `db_pool` (session) and `conn` (function-scoped, truncates all tables before each test).

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "keel"
version = "0.0.1"
description = "Keel (provisional name) — intent & decision ledger. Slice 1."
requires-python = ">=3.12"
dependencies = [
    "mcp>=1.2",
    "asyncpg>=0.29",
    "anyio>=4.3",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "httpx>=0.27"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.env.example`, `README.md`, `Dockerfile`, `docker-compose.yml`**

`.env.example`:
```
DATABASE_URL=postgresql://keel:keel@localhost:5432/keel
KEEL_TEST_DATABASE_URL=postgresql://keel:keel@localhost:5432/keel_test
KEEL_DEV_TOKEN=dev-token
```

`README.md` (include provisional-name note):
```markdown
# keel (provisional name)

> **Name is a placeholder** (OPEN_QUESTIONS #1, unsettled). Do not harden into domains or published identifiers.

Intent & decision ledger — Slice 1: server skeleton + `register_session`, `get_context`, `record_decision`.

## Dev
    docker compose up -d db
    createdb via compose; then:
    pip install -e ".[dev]"
    python -m keel.scripts.seed
    uvicorn keel.server:app --reload   # or: python -m keel.server

## Test
    docker compose up -d db
    createdb keel_test (compose entrypoint creates it; see docker-compose.yml)
    pytest
```

`Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .
COPY . .
CMD ["python", "-m", "keel.server"]
```

`docker-compose.yml` (creates both `keel` and `keel_test` databases):
```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: keel
      POSTGRES_PASSWORD: keel
      POSTGRES_DB: keel
    ports: ["5432:5432"]
    volumes:
      - ./scripts/initdb:/docker-entrypoint-initdb.d:ro
  api:
    build: .
    env_file: .env
    depends_on: [db]
    ports: ["8000:8000"]
```

Also create `keel/scripts/initdb/01_test_db.sql`:
```sql
CREATE DATABASE keel_test;
```

- [ ] **Step 3: Write `config.py` and `db/pool.py`**

`config.py`:
```python
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str


def get_settings() -> Settings:
    return Settings(database_url=os.environ["DATABASE_URL"])
```

`db/pool.py`:
```python
from pathlib import Path
import asyncpg

_pool: asyncpg.Pool | None = None
_SCHEMA = Path(__file__).parent / "schema.sql"


async def init_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("pool not initialized; call init_pool first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def apply_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(_SCHEMA.read_text())
```

- [ ] **Step 4: Write `db/schema.sql` (full v0 schema)**

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS project (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name       text UNIQUE NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS person (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   uuid NOT NULL REFERENCES project(id),
    display_name text NOT NULL,
    token_hash   text NOT NULL,
    UNIQUE (project_id, display_name),
    UNIQUE (token_hash)
);

CREATE TABLE IF NOT EXISTS participant (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        uuid NOT NULL REFERENCES project(id),
    principal_type    text NOT NULL DEFAULT 'person_session',
    person_id         uuid REFERENCES person(id),
    agent_name        text,
    sponsor_person_id uuid REFERENCES person(id),
    role              text,
    harness           text NOT NULL,
    tier              text NOT NULL CHECK (tier IN ('deep','light')),
    session_id        text NOT NULL,
    allowed_scopes    text[] NOT NULL DEFAULT '{}',
    allowed_categories text[] NOT NULL DEFAULT '{}',
    status            text NOT NULL DEFAULT 'active',
    last_seen_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, person_id, session_id)
);

CREATE TABLE IF NOT EXISTS goal (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     uuid NOT NULL REFERENCES project(id),
    statement      text NOT NULL,
    owner_person_id uuid REFERENCES person(id),
    scope_tags     text[] NOT NULL DEFAULT '{}',
    status         text NOT NULL DEFAULT 'active',
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          uuid NOT NULL REFERENCES project(id),
    kind                text NOT NULL DEFAULT 'decision' CHECK (kind IN ('decision','lesson')),
    category            text,
    goal_id             uuid REFERENCES goal(id),
    statement           text NOT NULL,
    rationale           text,
    scope_tags          text[] NOT NULL,
    owner_person_id     uuid REFERENCES person(id),
    status              text NOT NULL DEFAULT 'active'
                        CHECK (status IN ('proposed','active','superseded','rejected')),
    source_participant_id uuid REFERENCES participant(id),
    supersedes_id       uuid REFERENCES decision(id),
    evidence_refs       text[] NOT NULL DEFAULT '{}',
    expires_at          timestamptz,
    embedding           vector(1536),
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS decision_scope_idx ON decision USING gin (scope_tags);
CREATE INDEX IF NOT EXISTS decision_status_idx ON decision (project_id, status);

CREATE TABLE IF NOT EXISTS dependency (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id    uuid NOT NULL REFERENCES decision(id),
    dependent_type text NOT NULL CHECK (dependent_type IN ('participant','artifact')),
    dependent_ref  text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS claim (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id     uuid NOT NULL REFERENCES project(id),
    participant_id uuid NOT NULL REFERENCES participant(id),
    scope_tags     text[] NOT NULL,
    expires_at     timestamptz
);

CREATE TABLE IF NOT EXISTS conflict (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id   uuid NOT NULL REFERENCES project(id),
    decision_a_id uuid NOT NULL REFERENCES decision(id),
    subject_type text NOT NULL CHECK (subject_type IN ('decision','planned_action')),
    subject_ref  text NOT NULL,
    relation     text NOT NULL CHECK (relation IN ('contradicts','duplicates','supersedes','unclear')),
    severity     text NOT NULL CHECK (severity IN ('high','medium','low')),
    explanation  text NOT NULL,
    status       text NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','dismissed')),
    resolution   text,
    resolved_by  uuid REFERENCES person(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id           uuid NOT NULL REFERENCES project(id),
    target_participant_id uuid REFERENCES participant(id),
    target_person_id     uuid REFERENCES person(id),
    kind                 text NOT NULL CHECK (kind IN ('conflict','change')),
    ref_id               uuid NOT NULL,
    delivered_at         timestamptz,
    acknowledged_at      timestamptz
);

CREATE TABLE IF NOT EXISTS event (
    id          bigserial PRIMARY KEY,
    project_id  uuid NOT NULL REFERENCES project(id),
    actor       text NOT NULL,
    action      text NOT NULL,
    payload_json jsonb NOT NULL,
    prev_hash   text,
    hash        text NOT NULL UNIQUE,
    created_at  timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS event_project_idx ON event (project_id, id);

CREATE TABLE IF NOT EXISTS handoff (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id        uuid NOT NULL REFERENCES project(id),
    from_participant_id uuid REFERENCES participant(id),
    to_person_id      uuid REFERENCES person(id),
    to_participant_id uuid REFERENCES participant(id),
    scope_tags        text[] NOT NULL DEFAULT '{}',
    decision_ids      uuid[] NOT NULL DEFAULT '{}',
    conflict_ids      uuid[] NOT NULL DEFAULT '{}',
    note              text,
    status            text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','declined')),
    created_at        timestamptz NOT NULL DEFAULT now(),
    accepted_at       timestamptz
);

CREATE TABLE IF NOT EXISTS outcome (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    decision_id  uuid NOT NULL REFERENCES decision(id),
    result       text NOT NULL CHECK (result IN ('held','reversed','caused_rework')),
    evidence_ref text,
    source       text NOT NULL CHECK (source IN ('manual','inferred')),
    confirmed_by uuid REFERENCES person(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_feedback (
    id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_id  uuid NOT NULL REFERENCES alert(id),
    verdict   text NOT NULL CHECK (verdict IN ('useful','noise')),
    note      text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS drift_signal (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id    uuid NOT NULL REFERENCES project(id),
    participant_id uuid REFERENCES participant(id),
    source        text NOT NULL CHECK (source IN ('edit','turn','commit','pr','gateway','slack')),
    scope_tags    text[] NOT NULL DEFAULT '{}',
    summary       text,
    file_paths    text[] NOT NULL DEFAULT '{}',
    ref           text,
    confidence    double precision,
    result        text CHECK (result IN ('none','possible','conflict')),
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS decision_request (
    id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id             uuid NOT NULL REFERENCES project(id),
    requester_participant_id uuid REFERENCES participant(id),
    owner_person_id        uuid REFERENCES person(id),
    question               text NOT NULL,
    options                text[] NOT NULL DEFAULT '{}',
    scope_tags             text[] NOT NULL DEFAULT '{}',
    status                 text NOT NULL DEFAULT 'open' CHECK (status IN ('open','answered','expired')),
    answer_decision_id     uuid REFERENCES decision(id),
    created_at             timestamptz NOT NULL DEFAULT now()
);
```

- [ ] **Step 5: Write `conftest.py` fixtures**

```python
import os
import pytest
import pytest_asyncio
from keel.db import pool as db


def _test_dsn() -> str:
    return os.environ.get(
        "KEEL_TEST_DATABASE_URL",
        "postgresql://keel:keel@localhost:5432/keel_test",
    )


_ALL_TABLES = [
    "alert_feedback", "alert", "drift_signal", "decision_request", "outcome",
    "handoff", "conflict", "claim", "dependency", "event", "decision",
    "goal", "participant", "person", "project",
]


@pytest_asyncio.fixture(scope="session")
async def db_pool():
    pool = await db.init_pool(_test_dsn())
    async with pool.acquire() as conn:
        await db.apply_schema(conn)
    yield pool
    await db.close_pool()


@pytest_asyncio.fixture
async def conn(db_pool):
    async with db_pool.acquire() as c:
        await c.execute("TRUNCATE " + ", ".join(_ALL_TABLES) + " RESTART IDENTITY CASCADE")
        yield c
```

- [ ] **Step 6: Write the failing test `tests/test_db.py`**

```python
async def test_schema_applies_and_core_tables_exist(conn):
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    )
    names = {r["table_name"] for r in rows}
    assert {"project", "person", "participant", "decision", "event"} <= names


async def test_vector_extension_present(conn):
    row = await conn.fetchrow("SELECT 1 FROM pg_extension WHERE extname='vector'")
    assert row is not None
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `docker compose up -d db && pytest tests/test_db.py -v`
Expected: PASS (schema applies, tables + vector extension present).

- [ ] **Step 8: Commit**

```bash
git add keel/
git commit -m "feat(keel): scaffold project, config, db pool, v0 schema, compose"
```

---

### Task 2: Append-only hash-chained event log

**Files:**
- Create: `keel/keel/events.py`
- Test: `keel/tests/test_events.py`

**Interfaces:**
- Consumes: an `asyncpg.Connection` inside a transaction; `project` row exists.
- Produces:
  - `event_hash(prev_hash: str | None, project_id, actor: str, action: str, payload: dict, created_at: datetime) -> str`
  - `async def append_event(conn, project_id, actor: str, action: str, payload: dict, created_at: datetime | None = None) -> asyncpg.Record` — takes a per-project advisory lock, computes `prev_hash` from the latest event, inserts, returns the row. Must be called within a transaction.
  - `async def validate_chain(conn, project_id) -> bool` — recomputes the chain and returns whether every stored hash matches.

- [ ] **Step 1: Write failing tests `tests/test_events.py`**

```python
import uuid
from datetime import datetime, timezone
from keel.events import event_hash, append_event, validate_chain


async def _project(conn):
    return await conn.fetchval("INSERT INTO project (name) VALUES ('p') RETURNING id")


def test_event_hash_is_deterministic():
    pid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    h1 = event_hash(None, pid, "actor", "act", {"b": 1, "a": 2}, ts)
    h2 = event_hash(None, pid, "actor", "act", {"a": 2, "b": 1}, ts)
    assert h1 == h2  # key order must not matter
    h3 = event_hash(None, pid, "actor", "act", {"a": 2, "b": 3}, ts)
    assert h1 != h3


async def test_append_links_prev_hash(conn):
    pid = await _project(conn)
    async with conn.transaction():
        e1 = await append_event(conn, pid, "a", "x", {"n": 1})
        e2 = await append_event(conn, pid, "a", "y", {"n": 2})
    assert e1["prev_hash"] is None
    assert e2["prev_hash"] == e1["hash"]
    assert await validate_chain(conn, pid) is True


async def test_validate_chain_detects_tamper(conn):
    pid = await _project(conn)
    async with conn.transaction():
        await append_event(conn, pid, "a", "x", {"n": 1})
    await conn.execute("UPDATE event SET payload_json = '{\"n\": 999}' WHERE project_id = $1", pid)
    assert await validate_chain(conn, pid) is False
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_events.py -v`
Expected: FAIL (`keel.events` not found).

- [ ] **Step 3: Implement `events.py`**

```python
import hashlib
import json
from datetime import datetime, timezone

import asyncpg


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def event_hash(prev_hash, project_id, actor, action, payload: dict, created_at: datetime) -> str:
    material = "\n".join([
        prev_hash or "",
        str(project_id),
        actor,
        action,
        _canonical(payload),
        created_at.astimezone(timezone.utc).isoformat(),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _lock_key(project_id) -> int:
    # stable 32-bit key for the per-project event chain lock
    return int.from_bytes(hashlib.sha256(("event:" + str(project_id)).encode()).digest()[:4], "big", signed=True)


async def append_event(conn: asyncpg.Connection, project_id, actor, action,
                       payload: dict, created_at: datetime | None = None) -> asyncpg.Record:
    created_at = created_at or datetime.now(timezone.utc)
    await conn.execute("SELECT pg_advisory_xact_lock($1)", _lock_key(project_id))
    prev_hash = await conn.fetchval(
        "SELECT hash FROM event WHERE project_id = $1 ORDER BY id DESC LIMIT 1", project_id
    )
    h = event_hash(prev_hash, project_id, actor, action, payload, created_at)
    return await conn.fetchrow(
        """INSERT INTO event (project_id, actor, action, payload_json, prev_hash, hash, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
        project_id, actor, action, _canonical(payload), prev_hash, h, created_at,
    )


async def validate_chain(conn: asyncpg.Connection, project_id) -> bool:
    rows = await conn.fetch(
        "SELECT * FROM event WHERE project_id = $1 ORDER BY id ASC", project_id
    )
    prev = None
    for r in rows:
        payload = json.loads(r["payload_json"])
        expected = event_hash(prev, project_id, r["actor"], r["action"], payload, r["created_at"])
        if expected != r["hash"] or r["prev_hash"] != prev:
            return False
        prev = r["hash"]
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_events.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add keel/keel/events.py keel/tests/test_events.py
git commit -m "feat(keel): append-only hash-chained event log"
```

---

### Task 3: Scope-tag normalization

**Files:**
- Create: `keel/keel/scope.py`
- Test: `keel/tests/test_scope.py`

**Interfaces:**
- Produces:
  - `normalize_tag(tag: str) -> str` — strip, lowercase, remove all internal whitespace. Raises `ValueError` on empty-after-normalize.
  - `normalize_tags(tags: list[str]) -> list[str]` — normalize each, drop blanks, de-dupe preserving first-seen order. Raises `ValueError` if the result is empty.
  - `async def reconcile(conn, project_id, tags: list[str]) -> list[str]` — normalize, then for each tag reuse an existing identical normalized tag already present on any decision in the project (exact match for Slice 1; fuzzy matching is a documented later-slice extension).

- [ ] **Step 1: Write failing tests `tests/test_scope.py`**

```python
import pytest
from keel.scope import normalize_tag, normalize_tags, reconcile


def test_normalize_collapses_case_and_space():
    assert normalize_tag("API: Orders") == "api:orders"
    assert normalize_tag("  Schema:User ") == "schema:user"


def test_normalize_empty_raises():
    with pytest.raises(ValueError):
        normalize_tag("   ")


def test_normalize_tags_dedupes_preserving_order():
    assert normalize_tags(["api:orders", "API: Orders", "ui:checkout"]) == ["api:orders", "ui:checkout"]


def test_normalize_tags_all_blank_raises():
    with pytest.raises(ValueError):
        normalize_tags(["  ", ""])


async def test_reconcile_reuses_existing_normalized(conn):
    pid = await conn.fetchval("INSERT INTO project (name) VALUES ('p') RETURNING id")
    await conn.execute(
        "INSERT INTO decision (project_id, statement, scope_tags) VALUES ($1,'d',$2)",
        pid, ["api:orders"],
    )
    assert await reconcile(conn, pid, ["API: Orders"]) == ["api:orders"]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_scope.py -v`
Expected: FAIL (`keel.scope` not found).

- [ ] **Step 3: Implement `scope.py`**

```python
import re

_WS = re.compile(r"\s+")


def normalize_tag(tag: str) -> str:
    out = _WS.sub("", tag.strip().lower())
    if not out:
        raise ValueError("scope tag is empty after normalization")
    return out


def normalize_tags(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for t in tags or []:
        try:
            n = normalize_tag(t)
        except ValueError:
            continue
        if n not in seen:
            seen.append(n)
    if not seen:
        raise ValueError("at least one non-empty scope tag is required")
    return seen


async def reconcile(conn, project_id, tags: list[str]) -> list[str]:
    normalized = normalize_tags(tags)
    rows = await conn.fetch(
        "SELECT DISTINCT unnest(scope_tags) AS tag FROM decision WHERE project_id = $1",
        project_id,
    )
    existing = {r["tag"] for r in rows}
    # Slice 1: exact normalized match reuses the canonical existing tag (identity).
    # Later slice: fuzzy match (edit distance) to catch near-duplicate tags.
    return [t if t in existing or True else t for t in normalized]
```

> Note: the `reconcile` return is identity over normalized tags for Slice 1 (existing set already stores normalized tags, so equality holds). The `existing` lookup is wired now so the fuzzy-match extension drops in without changing callers.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_scope.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add keel/keel/scope.py keel/tests/test_scope.py
git commit -m "feat(keel): scope-tag normalization + reconciliation"
```

---

### Task 4: Repo data-access layer

**Files:**
- Create: `keel/keel/repo.py`
- Test: `keel/tests/test_repo.py`

**Interfaces:**
- Produces (all take `conn`):
  - `async def upsert_project(conn, name: str) -> uuid` — idempotent by name.
  - `async def upsert_person(conn, project_id, display_name, token_hash) -> uuid` — idempotent by (project, display_name).
  - `async def get_person_by_token(conn, token_hash) -> asyncpg.Record | None`
  - `async def upsert_participant(conn, project_id, person_id, harness, tier, session_id, allowed_scopes: list[str]) -> uuid` — idempotent by (project, person, session_id).
  - `async def get_participant(conn, project_id, person_id, session_id) -> asyncpg.Record | None`
  - `async def insert_decision(conn, *, project_id, statement, rationale, scope_tags, owner_person_id, source_participant_id, supersedes_id=None, status='active') -> asyncpg.Record`
  - `async def mark_superseded(conn, decision_id) -> None`
  - `async def get_decision(conn, decision_id) -> asyncpg.Record | None`
  - `async def active_decisions(conn, project_id, scope_tags: list[str] | None) -> list[asyncpg.Record]` — status `active`; if `scope_tags` given, overlap filter; newest first.

- [ ] **Step 1: Write failing tests `tests/test_repo.py`**

```python
from keel import repo


async def test_upsert_project_idempotent(conn):
    a = await repo.upsert_project(conn, "demo")
    b = await repo.upsert_project(conn, "demo")
    assert a == b


async def test_person_token_roundtrip(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "hash1")
    found = await repo.get_person_by_token(conn, "hash1")
    assert found["id"] == person


async def test_active_decisions_scope_filter(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "claude-code", "deep", "s1", [])
    await repo.insert_decision(conn, project_id=pid, statement="cursor pagination",
                               rationale="r", scope_tags=["api:orders"],
                               owner_person_id=person, source_participant_id=part)
    await repo.insert_decision(conn, project_id=pid, statement="guest checkout",
                               rationale="r", scope_tags=["ui:checkout"],
                               owner_person_id=person, source_participant_id=part)
    only = await repo.active_decisions(conn, pid, ["api:orders"])
    assert len(only) == 1 and only[0]["statement"] == "cursor pagination"
    alld = await repo.active_decisions(conn, pid, None)
    assert len(alld) == 2


async def test_mark_superseded(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "claude-code", "deep", "s1", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="old", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    await repo.mark_superseded(conn, d["id"])
    assert (await repo.get_decision(conn, d["id"]))["status"] == "superseded"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_repo.py -v`
Expected: FAIL (`keel.repo` not found).

- [ ] **Step 3: Implement `repo.py`**

```python
import asyncpg


async def upsert_project(conn, name: str):
    return await conn.fetchval(
        """INSERT INTO project (name) VALUES ($1)
           ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
           RETURNING id""",
        name,
    )


async def upsert_person(conn, project_id, display_name, token_hash):
    return await conn.fetchval(
        """INSERT INTO person (project_id, display_name, token_hash) VALUES ($1,$2,$3)
           ON CONFLICT (project_id, display_name)
           DO UPDATE SET token_hash = EXCLUDED.token_hash
           RETURNING id""",
        project_id, display_name, token_hash,
    )


async def get_person_by_token(conn, token_hash) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM person WHERE token_hash = $1", token_hash)


async def upsert_participant(conn, project_id, person_id, harness, tier, session_id, allowed_scopes):
    return await conn.fetchval(
        """INSERT INTO participant (project_id, person_id, harness, tier, session_id, allowed_scopes)
           VALUES ($1,$2,$3,$4,$5,$6)
           ON CONFLICT (project_id, person_id, session_id)
           DO UPDATE SET last_seen_at = now(), harness = EXCLUDED.harness,
                         tier = EXCLUDED.tier, allowed_scopes = EXCLUDED.allowed_scopes
           RETURNING id""",
        project_id, person_id, harness, tier, session_id, allowed_scopes,
    )


async def get_participant(conn, project_id, person_id, session_id) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM participant WHERE project_id=$1 AND person_id=$2 AND session_id=$3",
        project_id, person_id, session_id,
    )


async def insert_decision(conn, *, project_id, statement, rationale, scope_tags,
                          owner_person_id, source_participant_id, supersedes_id=None,
                          status="active") -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO decision
             (project_id, statement, rationale, scope_tags, owner_person_id,
              source_participant_id, supersedes_id, status)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
        project_id, statement, rationale, scope_tags, owner_person_id,
        source_participant_id, supersedes_id, status,
    )


async def mark_superseded(conn, decision_id) -> None:
    await conn.execute(
        "UPDATE decision SET status='superseded', updated_at=now() WHERE id=$1", decision_id
    )


async def get_decision(conn, decision_id) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM decision WHERE id=$1", decision_id)


async def active_decisions(conn, project_id, scope_tags) -> list[asyncpg.Record]:
    if scope_tags:
        return await conn.fetch(
            """SELECT * FROM decision
               WHERE project_id=$1 AND status='active' AND scope_tags && $2::text[]
               ORDER BY created_at DESC""",
            project_id, scope_tags,
        )
    return await conn.fetch(
        "SELECT * FROM decision WHERE project_id=$1 AND status='active' ORDER BY created_at DESC",
        project_id,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_repo.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add keel/keel/repo.py keel/tests/test_repo.py
git commit -m "feat(keel): repo data-access layer"
```

---

### Task 5: Principal + inbox builder

**Files:**
- Create: `keel/keel/principal.py`, `keel/keel/inbox.py`
- Test: `keel/tests/test_inbox.py`

**Interfaces:**
- Produces: `Principal` — frozen dataclass `(project_id, person_id, session_id: str | None)`.
- Produces: `async def build_inbox(conn, principal: Principal) -> dict` returning `{"alerts": [], "handoffs": [], "new_lessons": []}` (stable shape; empty for Slice 1).

- [ ] **Step 1: Write failing test `tests/test_inbox.py`**

```python
from keel.principal import Principal
from keel.inbox import build_inbox


async def test_inbox_stable_empty_shape(conn):
    p = Principal(project_id="p", person_id="u", session_id="s")
    box = await build_inbox(conn, p)
    assert box == {"alerts": [], "handoffs": [], "new_lessons": []}
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_inbox.py -v`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement `principal.py` and `inbox.py`**

`principal.py`:
```python
from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    project_id: object
    person_id: object
    session_id: str | None = None
```

`inbox.py`:
```python
from keel.principal import Principal


async def build_inbox(conn, principal: Principal) -> dict:
    # Slice 1: stable shape, no sources yet. Propagation slice fills alerts/handoffs;
    # lessons slice fills new_lessons.
    return {"alerts": [], "handoffs": [], "new_lessons": []}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_inbox.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add keel/keel/principal.py keel/keel/inbox.py keel/tests/test_inbox.py
git commit -m "feat(keel): Principal + piggyback inbox builder"
```

---

### Task 6: `register_session` tool handler

**Files:**
- Create: `keel/keel/tools/__init__.py`, `keel/keel/tools/register_session.py`
- Test: `keel/tests/test_register_session.py`

**Interfaces:**
- Consumes: `repo`, `events.append_event`, `inbox.build_inbox`, `Principal`.
- Produces: `async def register_session(pool, principal: Principal, *, harness: str, tier: str, session_id: str, allowed_scopes: list[str] | None = None) -> dict` returning `{"participant_id": str, "project_id": str, "session_id": str, "inbox": {...}}`. Writes a `participant.registered` event. Uses `principal.project_id` / `principal.person_id`.

- [ ] **Step 1: Write failing test `tests/test_register_session.py`**

```python
from keel import repo
from keel.principal import Principal
from keel.events import validate_chain
from keel.tools.register_session import register_session


async def _principal(conn, db_pool):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    return pid, person


async def test_register_creates_participant_and_event(conn, db_pool):
    pid, person = await _principal(conn, db_pool)
    principal = Principal(project_id=pid, person_id=person, session_id=None)
    out = await register_session(db_pool, principal, harness="claude-code",
                                 tier="deep", session_id="s1", allowed_scopes=["api:orders"])
    assert out["project_id"] == str(pid)
    assert out["session_id"] == "s1"
    assert out["inbox"] == {"alerts": [], "handoffs": [], "new_lessons": []}
    part = await repo.get_participant(conn, pid, person, "s1")
    assert part is not None and str(part["id"]) == out["participant_id"]
    assert await validate_chain(conn, pid) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_register_session.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `tools/register_session.py`**

```python
from keel import repo
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal


async def register_session(pool, principal: Principal, *, harness, tier,
                           session_id, allowed_scopes=None) -> dict:
    allowed_scopes = allowed_scopes or []
    async with pool.acquire() as conn:
        async with conn.transaction():
            part_id = await repo.upsert_participant(
                conn, principal.project_id, principal.person_id,
                harness, tier, session_id, allowed_scopes,
            )
            await append_event(
                conn, principal.project_id,
                actor=f"person:{principal.person_id}/session:{session_id}",
                action="participant.registered",
                payload={"participant_id": str(part_id), "harness": harness,
                         "tier": tier, "allowed_scopes": allowed_scopes},
            )
            box = await build_inbox(conn, Principal(principal.project_id, principal.person_id, session_id))
    return {"participant_id": str(part_id), "project_id": str(principal.project_id),
            "session_id": session_id, "inbox": box}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_register_session.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add keel/keel/tools/ keel/tests/test_register_session.py
git commit -m "feat(keel): register_session tool handler"
```

---

### Task 7: `get_context` tool handler

**Files:**
- Create: `keel/keel/tools/get_context.py`
- Test: `keel/tests/test_get_context.py`

**Interfaces:**
- Consumes: `repo.active_decisions`, `scope.reconcile`/`normalize_tags`, `inbox.build_inbox`.
- Produces: `async def get_context(pool, principal: Principal, *, scope_tags: list[str] | None = None) -> dict` returning `{"decisions": [ {id, statement, rationale, scope_tags, owner_person_id, status, created_at}... ], "lessons": [], "inbox": {...}}`. Normalizes `scope_tags` before filtering so tag variants match (Review Focus).

- [ ] **Step 1: Write failing tests `tests/test_get_context.py`**

```python
from keel import repo
from keel.principal import Principal
from keel.tools.get_context import get_context


async def _seed(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "claude-code", "deep", "s1", [])
    await repo.insert_decision(conn, project_id=pid, statement="cursor pagination",
                               rationale="r", scope_tags=["api:orders"],
                               owner_person_id=person, source_participant_id=part)
    return pid, person


async def test_get_context_filters_by_scope(conn, db_pool):
    pid, person = await _seed(conn)
    out = await get_context(db_pool, Principal(pid, person, "s1"), scope_tags=["api:orders"])
    assert len(out["decisions"]) == 1
    assert out["decisions"][0]["statement"] == "cursor pagination"
    assert out["inbox"] == {"alerts": [], "handoffs": [], "new_lessons": []}
    assert out["lessons"] == []


async def test_get_context_normalizes_tag_variant(conn, db_pool):
    pid, person = await _seed(conn)
    out = await get_context(db_pool, Principal(pid, person, "s1"), scope_tags=["API: Orders"])
    assert len(out["decisions"]) == 1  # variant must resolve to api:orders


async def test_get_context_no_scope_returns_all_active(conn, db_pool):
    pid, person = await _seed(conn)
    out = await get_context(db_pool, Principal(pid, person, "s1"), scope_tags=None)
    assert len(out["decisions"]) == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_get_context.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `tools/get_context.py`**

```python
from keel import repo
from keel.scope import normalize_tags
from keel.inbox import build_inbox
from keel.principal import Principal


def _decision_view(r) -> dict:
    return {
        "id": str(r["id"]),
        "statement": r["statement"],
        "rationale": r["rationale"],
        "scope_tags": list(r["scope_tags"]),
        "owner_person_id": str(r["owner_person_id"]) if r["owner_person_id"] else None,
        "status": r["status"],
        "created_at": r["created_at"].isoformat(),
    }


async def get_context(pool, principal: Principal, *, scope_tags=None) -> dict:
    tags = normalize_tags(scope_tags) if scope_tags else None
    async with pool.acquire() as conn:
        rows = await repo.active_decisions(conn, principal.project_id, tags)
        box = await build_inbox(conn, principal)
    return {"decisions": [_decision_view(r) for r in rows], "lessons": [], "inbox": box}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_get_context.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add keel/keel/tools/get_context.py keel/tests/test_get_context.py
git commit -m "feat(keel): get_context tool handler"
```

---

### Task 8: `record_decision` tool handler (serialized insert + conflict stub + supersedes)

**Files:**
- Create: `keel/keel/conflict.py`, `keel/keel/tools/record_decision.py`
- Test: `keel/tests/test_record_decision.py`

**Interfaces:**
- Consumes: `repo`, `scope.reconcile`, `events.append_event`, `inbox.build_inbox`, `conflict.check_on_insert`.
- Produces:
  - `conflict.py`: `async def check_on_insert(conn, project_id, decision_row) -> list` — Slice 1 stub returning `[]`; called inside the locked transaction so the pipeline insertion point is real.
  - `async def record_decision(pool, principal: Principal, *, statement: str, rationale: str, scope_tags: list[str], supersedes: str | None = None) -> dict` returning `{"decision_id": str, "status": "active", "scope_tags": [...], "conflicts": [], "inbox": {...}}`. Resolves the current participant from `principal`; rejects empty scope tags; acquires per-scope advisory locks (sorted) in one transaction; optionally marks `supersedes` superseded (same project only) atomically; writes a `decision.recorded` event.

- [ ] **Step 1: Write failing tests `tests/test_record_decision.py`**

```python
import asyncio
import pytest
from keel import repo
from keel.principal import Principal
from keel.events import validate_chain
from keel.tools.record_decision import record_decision
from keel.tools.get_context import get_context


async def _ctx(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    await repo.upsert_participant(conn, pid, person, "claude-code", "deep", "s1", [])
    return pid, person


async def test_record_creates_active_decision_and_event(conn, db_pool):
    pid, person = await _ctx(conn)
    out = await record_decision(db_pool, Principal(pid, person, "s1"),
                                statement="use cursor pagination", rationale="scales",
                                scope_tags=["API: Orders"])
    assert out["status"] == "active"
    assert out["scope_tags"] == ["api:orders"]
    assert out["conflicts"] == []
    ctx = await get_context(db_pool, Principal(pid, person, "s1"), scope_tags=["api:orders"])
    assert any(d["id"] == out["decision_id"] for d in ctx["decisions"])
    assert await validate_chain(conn, pid) is True


async def test_record_rejects_empty_scope(conn, db_pool):
    pid, person = await _ctx(conn)
    with pytest.raises(ValueError):
        await record_decision(db_pool, Principal(pid, person, "s1"),
                              statement="x", rationale="y", scope_tags=["  "])


async def test_record_requires_registered_session(conn, db_pool):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")  # no participant
    with pytest.raises(LookupError):
        await record_decision(db_pool, Principal(pid, person, "nope"),
                              statement="x", rationale="y", scope_tags=["api:orders"])


async def test_supersedes_flips_status(conn, db_pool):
    pid, person = await _ctx(conn)
    first = await record_decision(db_pool, Principal(pid, person, "s1"),
                                  statement="page size 20", rationale="r",
                                  scope_tags=["api:orders"])
    second = await record_decision(db_pool, Principal(pid, person, "s1"),
                                   statement="page size 50", rationale="r",
                                   scope_tags=["api:orders"], supersedes=first["decision_id"])
    assert (await repo.get_decision(conn, first["decision_id"]))["status"] == "superseded"
    assert second["status"] == "active"


async def test_supersedes_cross_project_errors_atomically(conn, db_pool):
    pid, person = await _ctx(conn)
    other = await repo.upsert_project(conn, "other")
    oper = await repo.upsert_person(conn, other, "x", "h2")
    opart = await repo.upsert_participant(conn, other, oper, "cc", "deep", "os", [])
    foreign = await repo.insert_decision(conn, project_id=other, statement="f", rationale="r",
                                         scope_tags=["api:orders"], owner_person_id=oper,
                                         source_participant_id=opart)
    with pytest.raises(ValueError):
        await record_decision(db_pool, Principal(pid, person, "s1"),
                              statement="x", rationale="y", scope_tags=["api:orders"],
                              supersedes=str(foreign["id"]))
    assert len(await repo.active_decisions(conn, pid, None)) == 0


async def test_concurrent_same_scope_serializes_chain_valid(conn, db_pool):
    pid, person = await _ctx(conn)
    p = Principal(pid, person, "s1")
    await asyncio.gather(
        record_decision(db_pool, p, statement="a", rationale="r", scope_tags=["api:orders"]),
        record_decision(db_pool, p, statement="b", rationale="r", scope_tags=["api:orders"]),
    )
    assert len(await repo.active_decisions(conn, pid, ["api:orders"])) == 2
    assert await validate_chain(conn, pid) is True
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_record_decision.py -v`
Expected: FAIL (modules not found).

- [ ] **Step 3: Implement `conflict.py` and `tools/record_decision.py`**

`conflict.py`:
```python
async def check_on_insert(conn, project_id, decision_row) -> list:
    # Slice 1 stub. The conflict-engine slice implements:
    #   scope filter -> vector+keyword retrieval -> deterministic checks
    #   -> per-candidate LLM judgment -> evidence check (ARCHITECTURE §7).
    # Returning [] keeps the locked-transaction insertion point real so the
    # engine drops in without changing record_decision.
    return []
```

`tools/record_decision.py`:
```python
import hashlib
from keel import repo
from keel.scope import reconcile
from keel.events import append_event
from keel.inbox import build_inbox
from keel.conflict import check_on_insert
from keel.principal import Principal


def _scope_lock_key(project_id, tag: str) -> int:
    material = f"scope:{project_id}:{tag}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big", signed=True)


async def record_decision(pool, principal: Principal, *, statement, rationale,
                          scope_tags, supersedes=None) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            participant = await repo.get_participant(
                conn, principal.project_id, principal.person_id, principal.session_id
            )
            if participant is None:
                raise LookupError("session not registered; call register_session first")

            tags = await reconcile(conn, principal.project_id, scope_tags)  # raises ValueError if empty

            # serialize per scope tag (sorted order avoids deadlock)
            for tag in sorted(tags):
                await conn.execute("SELECT pg_advisory_xact_lock($1)",
                                   _scope_lock_key(principal.project_id, tag))

            supersedes_id = None
            if supersedes:
                target = await repo.get_decision(conn, supersedes)
                if target is None or target["project_id"] != principal.project_id:
                    raise ValueError("supersedes target not found in this project")
                supersedes_id = target["id"]

            row = await repo.insert_decision(
                conn, project_id=principal.project_id, statement=statement,
                rationale=rationale, scope_tags=tags, owner_person_id=principal.person_id,
                source_participant_id=participant["id"], supersedes_id=supersedes_id,
                status="active",
            )
            if supersedes_id:
                await repo.mark_superseded(conn, supersedes_id)

            conflicts = await check_on_insert(conn, principal.project_id, row)

            await append_event(
                conn, principal.project_id,
                actor=f"person:{principal.person_id}/session:{principal.session_id}",
                action="decision.recorded",
                payload={"decision_id": str(row["id"]), "scope_tags": tags,
                         "supersedes": str(supersedes_id) if supersedes_id else None},
            )
            box = await build_inbox(conn, principal)

    return {"decision_id": str(row["id"]), "status": row["status"],
            "scope_tags": tags, "conflicts": conflicts, "inbox": box}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_record_decision.py -v`
Expected: PASS (all six, including concurrency and atomic-rollback cases).

- [ ] **Step 5: Commit**

```bash
git add keel/keel/conflict.py keel/keel/tools/record_decision.py keel/tests/test_record_decision.py
git commit -m "feat(keel): record_decision with serialized insert, supersedes, conflict stub"
```

---

### Task 9: MCP server wiring + header→Principal auth

**Files:**
- Create: `keel/keel/server.py`
- Test: `keel/tests/test_server_transport.py`

**Interfaces:**
- Consumes: all three tool handlers, `repo.get_person_by_token`, pool lifecycle.
- Produces:
  - `app` — ASGI app (streamable HTTP) exposing the three tools over MCP, mounted with an auth middleware that resolves `Authorization: Bearer <token>` → person+project and `X-Keel-Session: <id>` → `Principal`, stored in a `contextvar`. Unknown/missing token → HTTP 401 before any tool runs.
  - `current_principal() -> Principal` — read the contextvar inside tool wrappers; raises if unset.
  - `token_hash(token: str) -> str` — `sha256` hex, matching `person.token_hash` and `scripts/seed.py`.

- [ ] **Step 1: Write failing test `tests/test_server_transport.py`**

```python
import os
import hashlib
import pytest
import httpx
from keel import repo
from keel.db import pool as db

# This test exercises the ASGI app end to end via an in-process transport.
# It uses the MCP streamable-HTTP JSON-RPC envelope through the mounted app.

pytestmark = pytest.mark.asyncio


async def _seed_token(pool):
    async with pool.acquire() as conn:
        pid = await repo.upsert_project(conn, "demo")
        await repo.upsert_person(conn, pid, "vasan",
                                 hashlib.sha256(b"dev-token").hexdigest())


async def test_unknown_token_is_401(db_pool):
    from keel.server import app
    await _seed_token(db_pool)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/mcp", headers={"Authorization": "Bearer wrong",
                                          "X-Keel-Session": "s1"}, json={})
        assert r.status_code == 401


async def test_roundtrip_register_record_get(db_pool):
    """register_session -> record_decision -> get_context over the transport.
    Asserts the recorded decision is returned and every response carries inbox."""
    from keel.server import app, call_tool_for_test
    await _seed_token(db_pool)
    # call_tool_for_test(token, session, tool, args) is a thin test-only helper
    # that drives the same auth middleware + handler path as the HTTP route.
    reg = await call_tool_for_test("dev-token", "s1", "register_session",
                                   {"harness": "claude-code", "tier": "deep", "session_id": "s1"})
    assert "participant_id" in reg and reg["inbox"]["alerts"] == []
    rec = await call_tool_for_test("dev-token", "s1", "record_decision",
                                   {"statement": "cursor pagination", "rationale": "scales",
                                    "scope_tags": ["api:orders"]})
    assert rec["status"] == "active"
    ctx = await call_tool_for_test("dev-token", "s1", "get_context",
                                   {"scope_tags": ["api:orders"]})
    assert any(d["id"] == rec["decision_id"] for d in ctx["decisions"])
    assert ctx["inbox"] == {"alerts": [], "handoffs": [], "new_lessons": []}
```

> Note: `call_tool_for_test` is a documented test-only entry point exported from `server.py` that runs the real auth resolution (`token_hash` lookup → `Principal`) and dispatches to the real handler, so the roundtrip covers the auth path without depending on the MCP client's exact JSON-RPC framing. The 401 test exercises the HTTP route directly.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_server_transport.py -v`
Expected: FAIL (`keel.server` not found).

- [ ] **Step 3: Implement `server.py`**

```python
import hashlib
import contextvars
import os

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from keel.db import pool as db
from keel.config import get_settings
from keel.principal import Principal
from keel import repo
from keel.tools.register_session import register_session as _register_session
from keel.tools.get_context import get_context as _get_context
from keel.tools.record_decision import record_decision as _record_decision

_principal_var: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "keel_principal", default=None
)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_principal() -> Principal:
    p = _principal_var.get()
    if p is None:
        raise PermissionError("no authenticated principal in context")
    return p


async def _resolve_principal(token: str, session_id: str | None) -> Principal | None:
    pool = db.get_pool()
    async with pool.acquire() as conn:
        person = await repo.get_person_by_token(conn, token_hash(token))
    if person is None:
        return None
    return Principal(project_id=person["project_id"], person_id=person["id"],
                     session_id=session_id)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        auth = request.headers.get("authorization", "")
        session = request.headers.get("x-keel-session")
        token = auth[7:] if auth.lower().startswith("bearer ") else None
        if not token:
            return JSONResponse({"error": "missing bearer token"}, status_code=401)
        principal = await _resolve_principal(token, session)
        if principal is None:
            return JSONResponse({"error": "invalid token"}, status_code=401)
        tok = _principal_var.set(principal)
        try:
            return await call_next(request)
        finally:
            _principal_var.reset(tok)


mcp = FastMCP("keel")


@mcp.tool()
async def register_session(harness: str, tier: str, session_id: str,
                           allowed_scopes: list[str] | None = None) -> dict:
    return await _register_session(db.get_pool(), current_principal(),
                                   harness=harness, tier=tier, session_id=session_id,
                                   allowed_scopes=allowed_scopes)


@mcp.tool()
async def get_context(scope_tags: list[str] | None = None) -> dict:
    return await _get_context(db.get_pool(), current_principal(), scope_tags=scope_tags)


@mcp.tool()
async def record_decision(statement: str, rationale: str, scope_tags: list[str],
                          supersedes: str | None = None) -> dict:
    return await _record_decision(db.get_pool(), current_principal(), statement=statement,
                                  rationale=rationale, scope_tags=scope_tags, supersedes=supersedes)


# Test-only helper: run the real auth resolution + dispatch without MCP framing.
_HANDLERS = {
    "register_session": lambda p, a: _register_session(db.get_pool(), p, **a),
    "get_context": lambda p, a: _get_context(db.get_pool(), p, **a),
    "record_decision": lambda p, a: _record_decision(db.get_pool(), p, **a),
}


async def call_tool_for_test(token: str, session: str, tool: str, args: dict) -> dict:
    principal = await _resolve_principal(token, session)
    if principal is None:
        raise PermissionError("invalid token")
    return await _HANDLERS[tool](principal, args)


def _build_app() -> Starlette:
    mcp_app = mcp.streamable_http_app()   # mounts the MCP route (default path /mcp)
    mcp_app.add_middleware(AuthMiddleware)

    async def _startup():
        await db.init_pool(get_settings().database_url)

    async def _shutdown():
        await db.close_pool()

    mcp_app.add_event_handler("startup", _startup)
    mcp_app.add_event_handler("shutdown", _shutdown)
    return mcp_app


app = _build_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
```

> Implementer note: confirm the exact mount path and app factory name in the installed `mcp` SDK (`streamable_http_app()` and default `/mcp` path). If the SDK version mounts under a different path or needs a lifespan rather than event handlers, adjust `_build_app` and the 401 test's URL accordingly — the handler and auth logic are unaffected. Pin the installed `mcp` version in `pyproject.toml` once confirmed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_server_transport.py -v`
Expected: PASS (401 on bad token; full roundtrip with inbox on each response).

- [ ] **Step 5: Run the full suite**

Run: `pytest -v`
Expected: all tasks' tests PASS.

- [ ] **Step 6: Commit**

```bash
git add keel/keel/server.py keel/tests/test_server_transport.py
git commit -m "feat(keel): MCP streamable-HTTP server + bearer/session auth"
```

---

### Task 10: Seed script + manual two-session smoke doc

**Files:**
- Create: `keel/scripts/__init__.py`, `keel/scripts/seed.py`
- Modify: `keel/README.md` (append a manual two-session smoke-test section)

**Interfaces:**
- Consumes: `repo`, `server.token_hash`, pool lifecycle.
- Produces: `python -m keel.scripts.seed` — creates project `demo` and persons `vasan` / `teammate` with tokens from env (`KEEL_DEV_TOKEN`, `KEEL_TEAMMATE_TOKEN`, defaulting to `dev-token` / `teammate-token`). Idempotent.

- [ ] **Step 1: Write failing test `tests/test_seed.py`**

```python
import hashlib
from keel import repo
from keel.scripts.seed import seed


async def test_seed_creates_demo_project_and_people(db_pool):
    await seed(db_pool, dev_token="dev-token", teammate_token="teammate-token")
    async with db_pool.acquire() as conn:
        p = await repo.get_person_by_token(conn, hashlib.sha256(b"dev-token").hexdigest())
        t = await repo.get_person_by_token(conn, hashlib.sha256(b"teammate-token").hexdigest())
    assert p["display_name"] == "vasan"
    assert t["display_name"] == "teammate"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/test_seed.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `scripts/seed.py`**

```python
import asyncio
import os
from keel import repo
from keel.db import pool as db
from keel.config import get_settings
from keel.server import token_hash


async def seed(pool, *, dev_token: str, teammate_token: str) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            pid = await repo.upsert_project(conn, "demo")
            await repo.upsert_person(conn, pid, "vasan", token_hash(dev_token))
            await repo.upsert_person(conn, pid, "teammate", token_hash(teammate_token))


async def _main() -> None:
    pool = await db.init_pool(get_settings().database_url)
    try:
        await seed(pool,
                   dev_token=os.environ.get("KEEL_DEV_TOKEN", "dev-token"),
                   teammate_token=os.environ.get("KEEL_TEAMMATE_TOKEN", "teammate-token"))
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_seed.py -v`
Expected: PASS.

- [ ] **Step 5: Append manual smoke-test section to `README.md`**

```markdown
## Manual two-session smoke test (Slice 1)

1. `docker compose up -d db`
2. `pip install -e ".[dev]" && python -m keel.scripts.seed`
3. `python -m keel.server`  (listens on :8000, MCP at /mcp)
4. Session A (token `dev-token`, `X-Keel-Session: A`): register_session → record_decision
   `{statement: "orders API uses cursor pagination", rationale: "...", scope_tags: ["api:orders"]}`.
5. Session B (token `teammate-token`, `X-Keel-Session: B`): register_session → get_context
   `{scope_tags: ["api:orders"]}` returns A's decision. Cross-session fetch confirmed.
```

- [ ] **Step 6: Commit**

```bash
git add keel/scripts/ keel/tests/test_seed.py keel/README.md
git commit -m "feat(keel): seed script + manual two-session smoke doc"
```

---

## Self-Review Notes

- **Spec coverage:** §3 components (MCP server, store, event log) → Tasks 1,2,9; §4 data model → Task 1 (full schema) + Tasks 4/8 (decision/participant writes); §5 tools `register_session`/`get_context`/`record_decision` + piggyback `inbox` → Tasks 6,7,8,5; §7.1 serialized-per-scope insert → Task 8; §11 bearer-token identity + hash-chained log → Tasks 9,2. Deferred-by-design (named): conflict LLM judgment (§7), propagation/alerts (§8), hooks adapter (§6.1), drift (§7.1 sources), dashboard, OAuth/light tier (§6.2), GCP deploy (§10).
- **Review Focus → tests:** empty scope (Task 8 `test_record_rejects_empty_scope`), concurrent same-scope (Task 8 `test_concurrent_same_scope_serializes_chain_valid`), tag-variant lookup (Task 7 `test_get_context_normalizes_tag_variant`), bad supersedes atomicity (Task 8 `test_supersedes_cross_project_errors_atomically`), unknown token 401 (Task 9 `test_unknown_token_is_401`).
- **Open implementer risk:** the `mcp` SDK's streamable-HTTP app factory name and mount path, and its auth hook, are the one unverified external contract (ties to OPEN_QUESTIONS #8). Task 9's note instructs confirming/pinning the version. The test-only `call_tool_for_test` keeps the roundtrip coverage independent of JSON-RPC framing so a framing mismatch does not block the slice.
