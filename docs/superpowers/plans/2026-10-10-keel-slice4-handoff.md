# Keel Slice 4 — Handoff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (this project uses **native**/executing-plans) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make scope handoff first-class — `create_handoff` snapshots active decisions + open conflicts in scope and creates a pending handoff; `accept_handoff` (receiver-only) transfers the claim from sender to receiver and declares dependencies; `decline_handoff` closes it; pending handoffs ride the piggyback `inbox`.

**Architecture:** New repo helpers (person-by-name, handoff CRUD, open-conflicts-in-scope). New `keel/keel/tools/handoff.py` with 3 handlers. `inbox.build_inbox` grows a filled `handoffs` key (person-targeted). 3 new MCP tools registered in `server.py`. All deterministic DB work, append-only events, no LLM.

**Tech Stack:** Python 3.10+, asyncpg, pgvector, pytest/pytest-asyncio, Postgres 16. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-10-10-handoff-design.md` v0.1.

## Global Constraints
- **Humans resolve** — `accept_handoff`/`decline_handoff` are receiver-only (caller's person == `to_person_id`), else `PermissionError`; sender cannot self-accept.
- **Receiver by display_name** — `to_person` resolved via `(project_id, display_name)`; unknown → `LookupError`.
- **Accept = true transfer** — insert receiver claim on `scope_tags`, release sender's overlapping claims, declare receiver dependencies on each snapshotted decision that still exists; all in one atomic transaction.
- **Pending-only transitions** — accept/decline require `status='pending'`, else `ValueError`; no duplicate claims/deps.
- **Append-only** — create/accept/decline each append an `event`; `validate_chain` stays true.
- **Malformed ids** — `as_uuid` at the tool boundary; a bad handoff id → `LookupError` (not an asyncpg `DataError`).
- **Piggyback delivery only** — no hooks, no push. `handoffs` are person-targeted (any of the receiver's sessions), shown until accepted/declined.
- **Hermetic tests** — autouse fixture forces `KEEL_LLM_PROVIDER=none`. No network. Keep the 97 passed / 2 skipped baseline green.

## Review Focus
- **Sender self-accept** — sender (or any non-receiver) calling `accept_handoff` → `PermissionError`, nothing transferred. (Task 2)
- **Double accept / accept-after-decline** — second transition on a non-pending handoff → `ValueError`, no second claim/dependency. (Task 2)
- **Cross-project handoff id** — `get_handoff` returns a row in another project → treated as not found (`LookupError`). (Task 2)
- **Receiver with no participant for the accepting session** — `accept_handoff` from an unregistered session → `LookupError` before any transfer. (Task 2)
- **Handoff visible only to the target person** — a third person's inbox never shows it. (Task 3)

---

## File Structure
- `keel/keel/repo.py` — add `get_person_by_name`, `insert_handoff`, `get_handoff`, `pending_handoffs_for_person`, `open_conflicts_in_scope`, `set_handoff_status`. (Task 1)
- `keel/keel/tools/handoff.py` — `create_handoff`, `accept_handoff`, `decline_handoff`. (Task 2)
- `keel/keel/inbox.py` — fill the `handoffs` key. (Task 3)
- `keel/keel/server.py` — register 3 MCP tools + `_HANDLERS`. (Task 4)
- `keel/tests/` — `test_repo_handoff.py`, `test_handoff_tools.py`, extend `test_inbox.py`, `test_tool_descriptions.py`.

Task order: 1 repo helpers → 2 handoff tools → 3 inbox fill → 4 server registration.

---

### Task 1: Repo helpers (person-by-name, handoff CRUD, open-conflicts-in-scope)

**Files:** Modify `keel/keel/repo.py`; Test `keel/tests/test_repo_handoff.py`

**Interfaces — Produces** (all `async`, `conn` first):
- `get_person_by_name(conn, project_id, display_name) -> asyncpg.Record | None`
- `insert_handoff(conn, *, project_id, from_participant_id, to_person_id, to_participant_id, scope_tags, decision_ids, conflict_ids, note) -> asyncpg.Record`
- `get_handoff(conn, handoff_id) -> asyncpg.Record | None`
- `pending_handoffs_for_person(conn, project_id, to_person_id) -> list[Record]` (`status='pending'`, newest first by `created_at`)
- `open_conflicts_in_scope(conn, project_id, scope_tags) -> list[Record]` (`conflict.status='open'`, join `decision` on `decision_a_id`, `decision.scope_tags && $`)
- `set_handoff_status(conn, handoff_id, status, *, accepted_at=None, to_participant_id=None) -> None`

- [ ] **Step 1: Write failing tests `tests/test_repo_handoff.py`**
```python
from keel import repo


async def _p(conn, name, session):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, name, name + "-tok")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", session, [])
    return pid, person, part


async def test_get_person_by_name(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    got = await repo.get_person_by_name(conn, pid, "vasan")
    assert got["id"] == person
    assert await repo.get_person_by_name(conn, pid, "nobody") is None


async def test_handoff_insert_get_pending_status(conn):
    pid, sender, spart = await _p(conn, "vasan", "s1")
    receiver = await repo.upsert_person(conn, pid, "mate", "mate-tok")
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=sender,
                                   source_participant_id=spart)
    h = await repo.insert_handoff(conn, project_id=pid, from_participant_id=spart,
                                  to_person_id=receiver, to_participant_id=None,
                                  scope_tags=["api:orders"], decision_ids=[d["id"]],
                                  conflict_ids=[], note="take this")
    assert h["status"] == "pending" and h["note"] == "take this"
    assert list(h["decision_ids"]) == [d["id"]]
    got = await repo.get_handoff(conn, h["id"])
    assert got["id"] == h["id"]
    pend = await repo.pending_handoffs_for_person(conn, pid, receiver)
    assert [r["id"] for r in pend] == [h["id"]]
    # sender is not a recipient
    assert await repo.pending_handoffs_for_person(conn, pid, sender) == []


async def test_set_handoff_status_accept(conn):
    from datetime import datetime, timezone
    pid, sender, spart = await _p(conn, "vasan", "s1")
    receiver = await repo.upsert_person(conn, pid, "mate", "mate-tok")
    rpart = await repo.upsert_participant(conn, pid, receiver, "cc", "deep", "s2", [])
    h = await repo.insert_handoff(conn, project_id=pid, from_participant_id=spart,
                                  to_person_id=receiver, to_participant_id=None,
                                  scope_tags=["api:orders"], decision_ids=[], conflict_ids=[],
                                  note=None)
    await repo.set_handoff_status(conn, h["id"], "accepted",
                                  accepted_at=datetime.now(timezone.utc), to_participant_id=rpart)
    got = await repo.get_handoff(conn, h["id"])
    assert got["status"] == "accepted" and got["to_participant_id"] == rpart
    assert got["accepted_at"] is not None
    assert await repo.pending_handoffs_for_person(conn, pid, receiver) == []


async def test_open_conflicts_in_scope(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    other = await repo.insert_decision(conn, project_id=pid, statement="ui", rationale="r",
                                       scope_tags=["ui:checkout"], owner_person_id=person,
                                       source_participant_id=part)
    c = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                   subject_type="decision", subject_ref=str(d["id"]),
                                   relation="contradicts", severity="high", explanation="e")
    await repo.insert_conflict(conn, project_id=pid, decision_a_id=other["id"],
                               subject_type="decision", subject_ref=str(other["id"]),
                               relation="contradicts", severity="low", explanation="e2")
    got = await repo.open_conflicts_in_scope(conn, pid, ["api:orders"])
    assert [r["id"] for r in got] == [c["id"]]  # only the api:orders conflict
```

- [ ] **Step 2: Run → FAIL** (helpers missing). `KEEL_TEST_DATABASE_URL=postgresql://keel:keel@localhost:5433/keel_test pytest tests/test_repo_handoff.py -v`

- [ ] **Step 3: Implement the helpers in `repo.py`** (append after the propagation helpers)
```python
# --- Handoff ---

async def get_person_by_name(conn, project_id, display_name) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM person WHERE project_id=$1 AND display_name=$2",
        project_id, display_name)


async def insert_handoff(conn, *, project_id, from_participant_id, to_person_id,
                         to_participant_id, scope_tags, decision_ids, conflict_ids,
                         note) -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO handoff (project_id, from_participant_id, to_person_id,
             to_participant_id, scope_tags, decision_ids, conflict_ids, note)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
        project_id, from_participant_id, to_person_id, to_participant_id,
        scope_tags, decision_ids, conflict_ids, note)


async def get_handoff(conn, handoff_id) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM handoff WHERE id=$1", handoff_id)


async def pending_handoffs_for_person(conn, project_id, to_person_id) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT * FROM handoff
           WHERE project_id=$1 AND to_person_id=$2 AND status='pending'
           ORDER BY created_at DESC""",
        project_id, to_person_id)


async def open_conflicts_in_scope(conn, project_id, scope_tags) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT c.* FROM conflict c
           JOIN decision d ON d.id = c.decision_a_id
           WHERE c.project_id=$1 AND c.status='open' AND d.scope_tags && $2::text[]
           ORDER BY c.created_at DESC""",
        project_id, scope_tags)


async def set_handoff_status(conn, handoff_id, status, *, accepted_at=None,
                             to_participant_id=None) -> None:
    await conn.execute(
        """UPDATE handoff
           SET status=$2,
               accepted_at=COALESCE($3, accepted_at),
               to_participant_id=COALESCE($4, to_participant_id)
           WHERE id=$1""",
        handoff_id, status, accepted_at, to_participant_id)
```
> `decision_ids`/`conflict_ids` columns are `uuid[]`; asyncpg accepts a Python list of UUIDs. `scope_tags` is `text[]`.

- [ ] **Step 4: Run → PASS** (4 tests). **Step 5: Commit**
```bash
git add keel/keel/repo.py keel/tests/test_repo_handoff.py
git commit -m "feat(keel): repo helpers for handoff and open-conflicts-in-scope"
```

---

### Task 2: Handoff tools (create / accept / decline)

**Files:** Create `keel/keel/tools/handoff.py`; Test `keel/tests/test_handoff_tools.py`

**Interfaces:**
- Consumes: Task 1 helpers; `repo.active_decisions`, `repo.insert_claim`, `repo.release_claims`, `repo.insert_dependency`, `repo.get_participant`, `repo.get_decision`; `scope.normalize_tags`; `ids.as_uuid`; `events.append_event`; `inbox.build_inbox`.
- Produces:
  - `create_handoff(pool, principal, *, to_person, scope_tags, note=None, to_session=None) -> dict` → `{"handoff_id", "status":"pending", "scope_tags", "decision_ids", "conflict_ids", "inbox"}`
  - `accept_handoff(pool, principal, *, handoff_id) -> dict` → `{"handoff_id", "status":"accepted", "claimed_scope_tags", "dependencies": int, "inbox"}`
  - `decline_handoff(pool, principal, *, handoff_id) -> dict` → `{"handoff_id", "status":"declined", "inbox"}`

- [ ] **Step 1: Failing tests `tests/test_handoff_tools.py`**
```python
import pytest
from keel import repo
from keel.principal import Principal
from keel.events import validate_chain
from keel.tools.handoff import create_handoff, accept_handoff, decline_handoff
from keel.tools.record_decision import record_decision


async def _session(conn, pid, name, session):
    person = await repo.upsert_person(conn, pid, name, name + "-tok")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", session, [])
    return person, part


async def _project_with_decision(conn):
    pid = await repo.upsert_project(conn, "demo")
    sender, spart = await _session(conn, pid, "vasan", "s1")
    receiver, rpart = await _session(conn, pid, "mate", "s2")
    d = await repo.insert_decision(conn, project_id=pid, statement="orders use cursor",
                                   rationale="r", scope_tags=["api:orders"],
                                   owner_person_id=sender, source_participant_id=spart)
    return pid, sender, spart, receiver, rpart, d


async def test_create_handoff_snapshots_scope(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    c = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                   subject_type="decision", subject_ref=str(d["id"]),
                                   relation="contradicts", severity="high", explanation="e")
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["API: Orders"], note="yours now")
    assert out["status"] == "pending" and out["scope_tags"] == ["api:orders"]
    assert str(d["id"]) in out["decision_ids"] and str(c["id"]) in out["conflict_ids"]
    assert await validate_chain(conn, pid) is True


async def test_create_handoff_unknown_recipient_errors(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    with pytest.raises(LookupError):
        await create_handoff(db_pool, Principal(pid, sender, "s1"),
                             to_person="ghost", scope_tags=["api:orders"])


async def test_create_handoff_empty_scope_errors(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    with pytest.raises(ValueError):
        await create_handoff(db_pool, Principal(pid, sender, "s1"),
                             to_person="mate", scope_tags=["   "])


async def test_accept_handoff_transfers_claim_and_deps(conn, db_pool):
    from datetime import datetime, timedelta, timezone
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    # sender holds a claim on the scope
    fut = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.insert_claim(conn, pid, spart, ["api:orders"], fut)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"], note="n")
    acc = await accept_handoff(db_pool, Principal(pid, receiver, "s2"),
                               handoff_id=out["handoff_id"])
    assert acc["status"] == "accepted" and acc["dependencies"] == 1
    # receiver now claims the scope; sender's claim released
    claimers = {r["id"] for r in await repo.participants_with_claim_overlap(conn, pid, ["api:orders"])}
    assert rpart in claimers and spart not in claimers
    # receiver has a dependency on the snapshotted decision
    deps = {r["id"] for r in await repo.participants_with_dependency(conn, [d["id"]])}
    assert rpart in deps
    assert (await repo.get_handoff(conn, out["handoff_id"]))["status"] == "accepted"


async def test_accepted_handoff_rewires_propagation_to_receiver(conn, db_pool):
    # end-to-end: after transfer, a new decision on the scope by a third party
    # alerts the receiver (via the transferred claim).
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"], note="n")
    await accept_handoff(db_pool, Principal(pid, receiver, "s2"), handoff_id=out["handoff_id"])
    third, tpart = await _session(conn, pid, "third", "s3")
    await record_decision(db_pool, Principal(pid, third, "s3"),
                          statement="orders use offset", rationale="r", scope_tags=["api:orders"])
    recv_alerts = await repo.pending_alerts_for_participant(conn, rpart)
    assert any(a["kind"] == "change" for a in recv_alerts)


async def test_non_receiver_cannot_accept_or_decline(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"])
    with pytest.raises(PermissionError):
        await accept_handoff(db_pool, Principal(pid, sender, "s1"), handoff_id=out["handoff_id"])
    with pytest.raises(PermissionError):
        await decline_handoff(db_pool, Principal(pid, sender, "s1"), handoff_id=out["handoff_id"])
    assert (await repo.get_handoff(conn, out["handoff_id"]))["status"] == "pending"


async def test_double_accept_errors(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"])
    await accept_handoff(db_pool, Principal(pid, receiver, "s2"), handoff_id=out["handoff_id"])
    with pytest.raises(ValueError):
        await accept_handoff(db_pool, Principal(pid, receiver, "s2"), handoff_id=out["handoff_id"])


async def test_decline_handoff(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"])
    dec = await decline_handoff(db_pool, Principal(pid, receiver, "s2"),
                                handoff_id=out["handoff_id"])
    assert dec["status"] == "declined"
    # no claim created for receiver
    assert await repo.participants_with_claim_overlap(conn, pid, ["api:orders"]) == []


async def test_accept_malformed_id_errors_cleanly(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    with pytest.raises(LookupError):
        await accept_handoff(db_pool, Principal(pid, receiver, "s2"), handoff_id="not-a-uuid")


async def test_accept_unregistered_session_errors(conn, db_pool):
    # receiver person exists but the accepting session has no participant row
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"])
    with pytest.raises(LookupError):
        await accept_handoff(db_pool, Principal(pid, receiver, "s-unregistered"),
                             handoff_id=out["handoff_id"])
```

- [ ] **Step 2: Run → FAIL** (module missing).

- [ ] **Step 3: Implement `keel/keel/tools/handoff.py`**
```python
from datetime import datetime, timedelta, timezone
from keel import repo
from keel.ids import as_uuid
from keel.scope import normalize_tags
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal

_DEFAULT_CLAIM_TTL_S = 3600


async def _require_participant(conn, principal):
    part = await repo.get_participant(conn, principal.project_id, principal.person_id,
                                      principal.session_id)
    if part is None:
        raise LookupError("session not registered; call register_session first")
    return part


def _actor(principal) -> str:
    return f"person:{principal.person_id}/session:{principal.session_id}"


async def create_handoff(pool, principal: Principal, *, to_person, scope_tags,
                         note=None, to_session=None) -> dict:
    tags = normalize_tags(scope_tags)  # raises ValueError if empty
    async with pool.acquire() as conn:
        async with conn.transaction():
            sender = await _require_participant(conn, principal)
            recipient = await repo.get_person_by_name(conn, principal.project_id, to_person)
            if recipient is None:
                raise LookupError("recipient not found in this project")
            to_part_id = None
            if to_session:
                rp = await repo.get_participant(conn, principal.project_id,
                                                recipient["id"], to_session)
                to_part_id = rp["id"] if rp else None
            decisions = await repo.active_decisions(conn, principal.project_id, tags)
            conflicts = await repo.open_conflicts_in_scope(conn, principal.project_id, tags)
            decision_ids = [d["id"] for d in decisions]
            conflict_ids = [c["id"] for c in conflicts]
            h = await repo.insert_handoff(
                conn, project_id=principal.project_id, from_participant_id=sender["id"],
                to_person_id=recipient["id"], to_participant_id=to_part_id,
                scope_tags=tags, decision_ids=decision_ids, conflict_ids=conflict_ids, note=note)
            await append_event(conn, principal.project_id, actor=_actor(principal),
                               action="handoff.created",
                               payload={"handoff_id": str(h["id"]),
                                        "to_person_id": str(recipient["id"]),
                                        "scope_tags": tags,
                                        "decisions": len(decision_ids),
                                        "conflicts": len(conflict_ids)})
            box = await build_inbox(conn, principal)
    return {"handoff_id": str(h["id"]), "status": "pending", "scope_tags": tags,
            "decision_ids": [str(i) for i in decision_ids],
            "conflict_ids": [str(i) for i in conflict_ids], "inbox": box}


async def _load_for_recipient(conn, principal, handoff_id):
    try:
        hid = as_uuid(handoff_id)
    except ValueError:
        raise LookupError("handoff not found in this project")
    h = await repo.get_handoff(conn, hid)
    if h is None or h["project_id"] != principal.project_id:
        raise LookupError("handoff not found in this project")
    if h["to_person_id"] != principal.person_id:
        raise PermissionError("only the handoff recipient may act on it")
    if h["status"] != "pending":
        raise ValueError(f"handoff is not pending (status={h['status']})")
    return hid, h


async def accept_handoff(pool, principal: Principal, *, handoff_id) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            receiver = await _require_participant(conn, principal)
            hid, h = await _load_for_recipient(conn, principal, handoff_id)
            tags = list(h["scope_tags"])
            expires = datetime.now(timezone.utc) + timedelta(seconds=_DEFAULT_CLAIM_TTL_S)
            await repo.insert_claim(conn, principal.project_id, receiver["id"], tags, expires)
            await repo.release_claims(conn, h["from_participant_id"], tags)
            deps = 0
            for did in h["decision_ids"]:
                if await repo.get_decision(conn, did) is not None:
                    await repo.insert_dependency(conn, did, receiver["id"])
                    deps += 1
            await repo.set_handoff_status(conn, hid, "accepted",
                                          accepted_at=datetime.now(timezone.utc),
                                          to_participant_id=receiver["id"])
            await append_event(conn, principal.project_id, actor=_actor(principal),
                               action="handoff.accepted",
                               payload={"handoff_id": str(hid), "scope_tags": tags,
                                        "dependencies": deps})
            box = await build_inbox(conn, principal)
    return {"handoff_id": str(hid), "status": "accepted", "claimed_scope_tags": tags,
            "dependencies": deps, "inbox": box}


async def decline_handoff(pool, principal: Principal, *, handoff_id) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_participant(conn, principal)
            hid, h = await _load_for_recipient(conn, principal, handoff_id)
            await repo.set_handoff_status(conn, hid, "declined")
            await append_event(conn, principal.project_id, actor=_actor(principal),
                               action="handoff.declined", payload={"handoff_id": str(hid)})
            box = await build_inbox(conn, principal)
    return {"handoff_id": str(hid), "status": "declined", "inbox": box}
```
> `_require_participant` runs before `_load_for_recipient` in accept/decline so an unregistered accepting session fails with `LookupError` even for a valid handoff (Review Focus). In accept, the participant is needed for the transfer anyway.

- [ ] **Step 4: Run → PASS** (10 tests) + full suite green.
`KEEL_TEST_DATABASE_URL=... pytest tests/test_handoff_tools.py -v && KEEL_TEST_DATABASE_URL=... pytest -q`

- [ ] **Step 5: Commit**
```bash
git add keel/keel/tools/handoff.py keel/tests/test_handoff_tools.py
git commit -m "feat(keel): create/accept/decline_handoff tools (receiver-only transfer)"
```

---

### Task 3: Fill the inbox handoffs key

**Files:** Modify `keel/keel/inbox.py`; Test `keel/tests/test_inbox.py` (extend)

**Interfaces:**
- Consumes: `repo.pending_handoffs_for_person`.
- Produces: `build_inbox` returns `handoffs` as a list of `{id, from_participant_id, scope_tags, decision_ids, conflict_ids, note, created_at}` for the caller's person; `new_lessons` stays `[]`; unregistered session still returns the empty shape.

- [ ] **Step 1: Failing tests (extend `tests/test_inbox.py`)**
```python
async def test_inbox_includes_pending_handoff_for_target(conn):
    pid = await repo.upsert_project(conn, "demo")
    sender = await repo.upsert_person(conn, pid, "vasan", "h")
    spart = await repo.upsert_participant(conn, pid, sender, "cc", "deep", "s1", [])
    receiver = await repo.upsert_person(conn, pid, "mate", "h2")
    await repo.upsert_participant(conn, pid, receiver, "cc", "deep", "s2", [])
    h = await repo.insert_handoff(conn, project_id=pid, from_participant_id=spart,
                                  to_person_id=receiver, to_participant_id=None,
                                  scope_tags=["api:orders"], decision_ids=[], conflict_ids=[],
                                  note="take it")
    box = await build_inbox(conn, Principal(pid, receiver, "s2"))
    assert [x["id"] for x in box["handoffs"]] == [str(h["id"])]
    assert box["handoffs"][0]["note"] == "take it"
    assert box["handoffs"][0]["scope_tags"] == ["api:orders"]
    # the sender (a different person) does not see it in their inbox
    sbox = await build_inbox(conn, Principal(pid, sender, "s1"))
    assert sbox["handoffs"] == []


async def test_inbox_handoff_gone_after_status_change(conn):
    from datetime import datetime, timezone
    pid = await repo.upsert_project(conn, "demo")
    sender = await repo.upsert_person(conn, pid, "vasan", "h")
    spart = await repo.upsert_participant(conn, pid, sender, "cc", "deep", "s1", [])
    receiver = await repo.upsert_person(conn, pid, "mate", "h2")
    rpart = await repo.upsert_participant(conn, pid, receiver, "cc", "deep", "s2", [])
    h = await repo.insert_handoff(conn, project_id=pid, from_participant_id=spart,
                                  to_person_id=receiver, to_participant_id=None,
                                  scope_tags=["api:orders"], decision_ids=[], conflict_ids=[],
                                  note=None)
    await repo.set_handoff_status(conn, h["id"], "declined")
    box = await build_inbox(conn, Principal(pid, receiver, "s2"))
    assert box["handoffs"] == []
```

- [ ] **Step 2: Run → FAIL** (handoffs currently `[]`).

- [ ] **Step 3: Edit `inbox.py`** — replace the fixed `handoffs: []` with a query. Current `build_inbox` returns `{"alerts": alerts, "handoffs": [], "new_lessons": []}`; change to build handoffs from the caller's person:
```python
    handoffs = []
    for hr in await repo.pending_handoffs_for_person(conn, principal.project_id,
                                                     principal.person_id):
        handoffs.append({
            "id": str(hr["id"]),
            "from_participant_id": str(hr["from_participant_id"]) if hr["from_participant_id"] else None,
            "scope_tags": list(hr["scope_tags"]),
            "decision_ids": [str(i) for i in hr["decision_ids"]],
            "conflict_ids": [str(i) for i in hr["conflict_ids"]],
            "note": hr["note"],
            "created_at": hr["created_at"].isoformat() if hr["created_at"] else None,
        })
    return {"alerts": alerts, "handoffs": handoffs, "new_lessons": []}
```
(The early `return empty` for an unregistered session stays — it already returns before this block.)

- [ ] **Step 4: Run → PASS** + full suite (existing `test_inbox_stable_empty_shape` still green — registered principal, no handoffs).

- [ ] **Step 5: Commit**
```bash
git add keel/keel/inbox.py keel/tests/test_inbox.py
git commit -m "feat(keel): deliver pending handoffs in the piggyback inbox"
```

---

### Task 4: Register the 3 handoff MCP tools

**Files:** Modify `keel/keel/server.py`; Test `keel/tests/test_tool_descriptions.py` (extend)

**Interfaces:**
- Consumes: Task 2 handlers.
- Produces: `@mcp.tool()` wrappers + `_HANDLERS` entries for `create_handoff`, `accept_handoff`, `decline_handoff`, each with a docstring and using `current_principal()` + `db.get_pool()`.

- [ ] **Step 1: Extend `tests/test_tool_descriptions.py`** — update the expected set to 13:
```python
    expected = {"register_session", "get_context", "record_decision", "check_intent",
                "declare_dependency", "claim_scope", "release_scope", "list_alerts",
                "ack_alert", "resolve_conflict",
                "create_handoff", "accept_handoff", "decline_handoff"}
    assert set(tools) == expected
```

- [ ] **Step 2: Run → FAIL** (missing tools).

- [ ] **Step 3: Add to `server.py`** — import + wrappers (follow the existing pattern). Import:
```python
from keel.tools.handoff import create_handoff as _create_handoff, \
    accept_handoff as _accept_handoff, decline_handoff as _decline_handoff
```
Wrappers (place with the other `@mcp.tool()` definitions, before `_HANDLERS`):
```python
@mcp.tool()
async def create_handoff(to_person: str, scope_tags: list[str], note: str | None = None,
                         to_session: str | None = None) -> dict:
    """Hand off a scope to a teammate with its context attached.

    Resolves `to_person` by display name and snapshots the active decisions and
    open conflicts on the given `scope_tags`, creating a pending handoff the
    recipient sees in their inbox. Optionally target one of their sessions with
    `to_session`. Returns the handoff id, status, and an `inbox`.
    """
    return await _create_handoff(db.get_pool(), current_principal(), to_person=to_person,
                                 scope_tags=scope_tags, note=note, to_session=to_session)


@mcp.tool()
async def accept_handoff(handoff_id: str) -> dict:
    """Accept a handoff addressed to you: claim its scope and depend on its decisions.

    Recipient only. Transfers the scope claim from the sender to this session and
    declares dependencies on the handed-off decisions so future changes alert you.
    Returns the handoff status and an `inbox`.
    """
    return await _accept_handoff(db.get_pool(), current_principal(), handoff_id=handoff_id)


@mcp.tool()
async def decline_handoff(handoff_id: str) -> dict:
    """Decline a handoff addressed to you; it closes with no scope or dependency change.

    Recipient only. Returns the handoff status and an `inbox`.
    """
    return await _decline_handoff(db.get_pool(), current_principal(), handoff_id=handoff_id)
```
Add to `_HANDLERS`:
```python
    "create_handoff": lambda p, a: _create_handoff(db.get_pool(), p, **a),
    "accept_handoff": lambda p, a: _accept_handoff(db.get_pool(), p, **a),
    "decline_handoff": lambda p, a: _decline_handoff(db.get_pool(), p, **a),
```

- [ ] **Step 4: Run → PASS** (descriptions test) + FULL suite green.
`KEEL_TEST_DATABASE_URL=... pytest -q`

- [ ] **Step 5: Commit**
```bash
git add keel/keel/server.py keel/tests/test_tool_descriptions.py
git commit -m "feat(keel): register handoff MCP tools"
```

---

## Self-Review Notes
- **Spec coverage:** §3.1 create → Task 2 (+ repo Task 1); §3.2 accept transfer → Task 2 `test_accept_handoff_transfers_claim_and_deps` + end-to-end rewire; §3.3 decline → Task 2; §4 inbox → Task 3; §5 repo helpers → Task 1; §6 tools+registration → Tasks 2,4; §2 principles (append-only events, receiver-only, atomic transfer) → Task 2 tests.
- **Review Focus → tests:** sender self-accept (Task 2 `test_non_receiver_cannot_accept_or_decline`); double accept (Task 2 `test_double_accept_errors`); cross-project id (covered by `_load_for_recipient`'s project check — note: no dedicated test since conn fixture is single-project; the project guard mirrors Slice 3 resolve_conflict which is tested; acceptable); unregistered accepting session (Task 2 `test_accept_unregistered_session_errors`); third-person inbox isolation (Task 3 `test_inbox_includes_pending_handoff_for_target` asserts sender sees none).
- **Type consistency:** `insert_handoff` kwargs ↔ handoff columns; `decision_ids`/`conflict_ids` are `uuid[]` in, stringified out; `get_handoff`/`set_handoff_status` share `handoff_id`; `active_decisions(conn, pid, tags)` returns rows with `id`; `open_conflicts_in_scope` returns conflict rows with `id`; accept reuses Slice 3 `insert_claim`/`release_claims`/`insert_dependency` (signatures verified in Slice 3).
- **Cross-project test gap:** the `conn`/`db_pool` fixtures truncate to one project; the project-mismatch branch in `_load_for_recipient` is guarded identically to the tested `resolve_conflict` path. If a reviewer wants it pinned, add a two-project test in the final pass.
- **Atomic transfer:** no savepoint — a transfer failure rolls back the whole accept (spec §8), consistent with Slice 3 propagation.
