# Keel Slice 3 — Propagation & Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans (this project uses **native**/executing-plans) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make recorded changes propagate — create `change` alerts (claim/dependency targeting) when a decision is recorded or supersedes another, and `conflict` alerts when a conflict is detected; deliver them via the piggyback `inbox`; add the P0 tools `declare_dependency`, `claim_scope`/`release_scope`, `list_alerts`/`ack_alert`, `resolve_conflict`.

**Architecture:** A new `keel/keel/propagation.py` computes affected participants (active claim overlap + dependency, author's own session excluded) and inserts `alert` rows inside `record_decision`'s existing transaction. `inbox.build_inbox` is filled to return the caller's unacknowledged alerts on every tool response. New tool handlers under `keel/keel/tools/` + repo helpers. All deterministic DB work; no LLM; append-only events throughout.

**Tech Stack:** Python 3.10+, asyncpg, pgvector, pytest/pytest-asyncio, Postgres 16. (No new dependencies.)

**Spec:** `docs/superpowers/specs/2026-10-10-propagation-alerts-design.md` v0.1.

## Global Constraints
- **Warn, never block** — alerts are informational; no tool blocks (ARCHITECTURE §1.3).
- **Humans resolve** — `resolve_conflict` is owner-only (caller's person == candidate decision `owner_person_id`), else `PermissionError`; no auto-overwrite.
- **Exclude the author's own session** from propagation targets (`author_participant_id`); the author's *other* sessions are included only via their own claim/dependency.
- **Append-only** — every alert batch / claim / dependency / ack / resolve writes an `event`; `validate_chain` stays true.
- **Propagation is transactional with the decision** (outer txn in `record_decision`, NOT the detection savepoint) and uses the conflicts the pipeline already returned (no re-query).
- **Piggyback delivery only** — no hooks, no Slack, no push.
- **Hermetic tests** — autouse fixture forces `KEEL_LLM_PROVIDER=none`; conflict-alert tests inject a fake judge (Slice-2 `tests/fakes.py` pattern). No network.
- **Builds on Slices 1–2** — keep the 72 passed / 2 skipped baseline green; `from keel.conflict import check_on_insert` and all existing tools unchanged in behavior except the added alert delivery.

## Review Focus
- **Author session that also claims the scope** must NOT alert itself on its own decision — exclusion by `author_participant_id`. (Task 3)
- **Expired claim** (`expires_at` in the past) must NOT receive `change` alerts. (Task 2/3)
- **`resolve_conflict` by a non-owner** → `PermissionError`, conflict unchanged. (Task 6)
- **`ack_alert` on an alert that isn't the caller's** (or already acked) → error / no-op, not a silent cross-participant ack. (Task 5)
- **Unregistered session calling a tool** → `build_inbox` returns the empty shape, no crash. (Task 4)

---

## File Structure
- `keel/keel/repo.py` — new helpers (claims, dependencies, alerts, participants-of-person, conflict get/resolve). (Task 1)
- `keel/keel/conflict/pipeline.py` — carry `conflict_id` on `Conflict`. (Task 2)
- `keel/keel/propagation.py` — `propagate_decision`, `propagate_conflicts`. (Task 3)
- `keel/keel/tools/record_decision.py` — call propagation in the outer txn. (Task 3)
- `keel/keel/inbox.py` — fill `build_inbox`. (Task 4)
- `keel/keel/tools/alerts.py` — `list_alerts`, `ack_alert`. (Task 5)
- `keel/keel/tools/claims.py` — `declare_dependency`, `claim_scope`, `release_scope`. (Task 5)
- `keel/keel/tools/resolve_conflict.py` — `resolve_conflict`. (Task 6)
- `keel/keel/server.py` — register the 6 new MCP tools + `_HANDLERS`. (Task 7)
- `keel/tests/` — one test module per unit.

Task order: 1 repo helpers → 2 conflict_id → 3 propagation + record_decision wiring → 4 inbox → 5 alert/claim tools → 6 resolve_conflict → 7 server registration.

---

### Task 1: Repo helpers (claims, dependencies, alerts, participants, conflict)

**Files:** Modify `keel/keel/repo.py`; Test `keel/tests/test_repo_propagation.py`

**Interfaces — Produces** (all `async`, take `conn` first):
- `insert_claim(conn, project_id, participant_id, scope_tags, expires_at) -> asyncpg.Record`
- `release_claims(conn, participant_id, scope_tags=None) -> int` (count removed; all of the participant's claims when `scope_tags` is None, else those overlapping)
- `participants_with_claim_overlap(conn, project_id, scope_tags) -> list[Record]` (distinct active participants with a non-expired claim overlapping scope_tags)
- `insert_dependency(conn, decision_id, participant_id) -> asyncpg.Record` (`dependent_type='participant'`, `dependent_ref=str(participant_id)`)
- `participants_with_dependency(conn, decision_ids: list) -> list[Record]` (distinct participants referenced by dependencies on any of `decision_ids`)
- `participants_of_person(conn, project_id, person_id) -> list[Record]` (active)
- `insert_alert(conn, *, project_id, target_participant_id, target_person_id, kind, ref_id) -> Record`
- `pending_alerts_for_participant(conn, participant_id) -> list[Record]` (`acknowledged_at IS NULL`, newest first)
- `mark_alert_delivered(conn, alert_id) -> None` (set `delivered_at=now()` where null)
- `ack_alert(conn, alert_id, participant_id) -> bool` (True only if the alert belongs to the participant and was unacked)
- `get_conflict(conn, conflict_id) -> Record | None`
- `resolve_conflict(conn, conflict_id, resolution, resolved_by) -> None`

- [ ] **Step 1: Write failing tests `tests/test_repo_propagation.py`**
```python
from datetime import datetime, timedelta, timezone
from keel import repo


async def _p(conn, name, session):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, name, name + "-tok")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", session, [])
    return pid, person, part


async def test_claim_overlap_active_only(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await repo.insert_claim(conn, pid, part, ["api:orders"], future)
    got = await repo.participants_with_claim_overlap(conn, pid, ["api:orders"])
    assert [r["id"] for r in got] == [part]
    assert await repo.participants_with_claim_overlap(conn, pid, ["ui:checkout"]) == []
    # expired claim excluded
    _, _, part2 = await _p(conn, "t", "s2")
    await repo.insert_claim(conn, pid, part2, ["api:orders"], past)
    ids = {r["id"] for r in await repo.participants_with_claim_overlap(conn, pid, ["api:orders"])}
    assert part2 not in ids and part in ids


async def test_release_claims(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.insert_claim(conn, pid, part, ["api:orders"], future)
    await repo.insert_claim(conn, pid, part, ["ui:checkout"], future)
    assert await repo.release_claims(conn, part, ["api:orders"]) == 1
    left = await repo.participants_with_claim_overlap(conn, pid, ["ui:checkout"])
    assert len(left) == 1
    assert await repo.release_claims(conn, part) == 1  # the rest


async def test_dependency_targets(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    await repo.insert_dependency(conn, d["id"], part)
    got = await repo.participants_with_dependency(conn, [d["id"]])
    assert [r["id"] for r in got] == [part]


async def test_alert_insert_pending_deliver_ack(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    a = await repo.insert_alert(conn, project_id=pid, target_participant_id=part,
                                target_person_id=person, kind="change", ref_id=d["id"])
    pend = await repo.pending_alerts_for_participant(conn, part)
    assert [r["id"] for r in pend] == [a["id"]]
    await repo.mark_alert_delivered(conn, a["id"])
    assert (await repo.get_conflict(conn, d["id"])) is None  # unrelated id -> None
    assert await repo.ack_alert(conn, a["id"], part) is True
    assert await repo.pending_alerts_for_participant(conn, part) == []
    assert await repo.ack_alert(conn, a["id"], part) is False  # already acked


async def test_resolve_conflict(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    c = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                   subject_type="decision", subject_ref=str(d["id"]),
                                   relation="contradicts", severity="high", explanation="e")
    await repo.resolve_conflict(conn, c["id"], "keep", person)
    got = await repo.get_conflict(conn, c["id"])
    assert got["status"] == "resolved" and got["resolution"] == "keep" and got["resolved_by"] == person
```

- [ ] **Step 2: Run → FAIL** (helpers missing). `KEEL_TEST_DATABASE_URL=postgresql://keel:keel@localhost:5433/keel_test pytest tests/test_repo_propagation.py -v`

- [ ] **Step 3: Implement the helpers in `repo.py`**
```python
async def insert_claim(conn, project_id, participant_id, scope_tags, expires_at):
    return await conn.fetchrow(
        """INSERT INTO claim (project_id, participant_id, scope_tags, expires_at)
           VALUES ($1,$2,$3,$4) RETURNING *""",
        project_id, participant_id, scope_tags, expires_at)


async def release_claims(conn, participant_id, scope_tags=None) -> int:
    if scope_tags:
        res = await conn.execute(
            "DELETE FROM claim WHERE participant_id=$1 AND scope_tags && $2::text[]",
            participant_id, scope_tags)
    else:
        res = await conn.execute("DELETE FROM claim WHERE participant_id=$1", participant_id)
    return int(res.split()[-1])  # "DELETE <n>"


async def participants_with_claim_overlap(conn, project_id, scope_tags):
    return await conn.fetch(
        """SELECT DISTINCT p.* FROM participant p
           JOIN claim c ON c.participant_id = p.id
           WHERE c.project_id=$1 AND p.status='active'
             AND c.scope_tags && $2::text[]
             AND (c.expires_at IS NULL OR c.expires_at > now())""",
        project_id, scope_tags)


async def insert_dependency(conn, decision_id, participant_id):
    return await conn.fetchrow(
        """INSERT INTO dependency (decision_id, dependent_type, dependent_ref)
           VALUES ($1,'participant',$2) RETURNING *""",
        decision_id, str(participant_id))


async def participants_with_dependency(conn, decision_ids):
    return await conn.fetch(
        """SELECT DISTINCT p.* FROM participant p
           JOIN dependency d ON d.dependent_type='participant' AND d.dependent_ref = p.id::text
           WHERE d.decision_id = ANY($1::uuid[])""",
        decision_ids)


async def participants_of_person(conn, project_id, person_id):
    return await conn.fetch(
        "SELECT * FROM participant WHERE project_id=$1 AND person_id=$2 AND status='active'",
        project_id, person_id)


async def insert_alert(conn, *, project_id, target_participant_id, target_person_id, kind, ref_id):
    return await conn.fetchrow(
        """INSERT INTO alert (project_id, target_participant_id, target_person_id, kind, ref_id)
           VALUES ($1,$2,$3,$4,$5) RETURNING *""",
        project_id, target_participant_id, target_person_id, kind, ref_id)


async def pending_alerts_for_participant(conn, participant_id):
    return await conn.fetch(
        """SELECT * FROM alert WHERE target_participant_id=$1 AND acknowledged_at IS NULL
           ORDER BY id DESC""",
        participant_id)


async def mark_alert_delivered(conn, alert_id) -> None:
    await conn.execute(
        "UPDATE alert SET delivered_at=now() WHERE id=$1 AND delivered_at IS NULL", alert_id)


async def ack_alert(conn, alert_id, participant_id) -> bool:
    res = await conn.execute(
        """UPDATE alert SET acknowledged_at=now()
           WHERE id=$1 AND target_participant_id=$2 AND acknowledged_at IS NULL""",
        alert_id, participant_id)
    return res.split()[-1] == "1"


async def get_conflict(conn, conflict_id):
    return await conn.fetchrow("SELECT * FROM conflict WHERE id=$1", conflict_id)


async def resolve_conflict(conn, conflict_id, resolution, resolved_by) -> None:
    await conn.execute(
        """UPDATE conflict SET status='resolved', resolution=$2, resolved_by=$3 WHERE id=$1""",
        conflict_id, resolution, resolved_by)
```
> `get_conflict(conn, d["id"])` returning None for a decision id is correct — the ids are distinct UUID spaces; the test just asserts a non-conflict id yields None.

- [ ] **Step 4: Run → PASS** (5 tests). **Step 5: Commit**
```bash
git add keel/keel/repo.py keel/tests/test_repo_propagation.py
git commit -m "feat(keel): repo helpers for claims, dependencies, alerts, conflict resolve"
```

---

### Task 2: Carry conflict_id on Conflict

**Files:** Modify `keel/keel/conflict/pipeline.py`; Test `keel/tests/test_pipeline.py` (extend)

**Interfaces:**
- Consumes: `repo.insert_conflict(...)` returns a row with `id`.
- Produces: `Conflict` dataclass gains `conflict_id: str | None = None` (last field, default None); when `persist=True`, it is set to the inserted conflict row id; `check_on_insert`'s returned dicts include `conflict_id`.

- [ ] **Step 1: Failing test (append to `tests/test_pipeline.py`)**
```python
async def test_persisted_conflict_carries_conflict_id(conn):
    from keel import repo
    from keel.llm.embeddings import DeterministicEmbedder
    from keel.conflict.pipeline import detect, Subject
    from keel.conflict.judge import CompositeJudge  # noqa  (ensure import path stable)
    from tests.fakes import ScriptedJudge
    e = DeterministicEmbedder()
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "v", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    await repo.insert_decision(conn, project_id=pid, statement="orders API uses cursor pagination",
                               rationale="r", scope_tags=["api:orders"], owner_person_id=person,
                               source_participant_id=part, embedding=await e.embed("cursor"))
    subj = Subject("use offset pagination for orders", ["api:orders"], await e.embed("offset"),
                   "decision", "00000000-0000-0000-0000-0000000000aa")
    res = await detect(conn, pid, subj, judge=ScriptedJudge(), top_k=8, threshold=0.6,
                       persist=True, model="m1")
    assert len(res.conflicts) == 1
    cid = res.conflicts[0].conflict_id
    assert cid is not None
    assert await repo.get_conflict(conn, cid) is not None  # it's a real conflict row id
```
> `from keel.conflict.judge import CompositeJudge` may not exist (Slice 2 is LLM-only, no composite). If that import fails, drop that line — it is only a path-stability guard. Keep `ScriptedJudge`.

- [ ] **Step 2: Run → FAIL** (`conflict_id` is None / attribute missing).

- [ ] **Step 3: Edit `pipeline.py`** — add the field to the dataclass and set it on persist. Current (around lines 19, 61-64):
```python
@dataclass
class Conflict:
    candidate_id: str; relation: str; severity: str
    explanation: str; evidence: str; confidence: float
    conflict_id: str | None = None
```
In `detect`, when persisting, capture the row and set the id. Replace the append+insert block so the Conflict carries the id:
```python
        conflict = Conflict(str(cand["id"]), j.relation, sev, j.explanation,
                            j.evidence, j.confidence)
        if persist:
            crow = await repo.insert_conflict(
                conn, project_id=project_id, decision_a_id=cand["id"],
                subject_type=subject.subject_type, subject_ref=subject.subject_ref,
                relation=j.relation, severity=sev, explanation=j.explanation)
            conflict.conflict_id = str(crow["id"])
        conflicts.append(conflict)
```
(Keep the rest of `detect` — evidence gate, event, coverage — unchanged.)

- [ ] **Step 4: Run → PASS**; also run `tests/test_pipeline.py` + `tests/test_record_decision.py` to confirm no regression (the extra default field is backward-compatible).

- [ ] **Step 5: Commit**
```bash
git add keel/keel/conflict/pipeline.py keel/tests/test_pipeline.py
git commit -m "feat(keel): carry persisted conflict_id on Conflict for alert targeting"
```

---

### Task 3: Propagation engine + record_decision wiring

**Files:** Create `keel/keel/propagation.py`; Modify `keel/keel/tools/record_decision.py`; Test `keel/tests/test_propagation.py`

**Interfaces:**
- Consumes: Task 1 repo helpers; `events.append_event`; `repo.get_decision`.
- Produces:
  - `async def propagate_decision(conn, project_id, decision_row, author_participant_id, superseded_id=None) -> list[str]` (alert ids created)
  - `async def propagate_conflicts(conn, project_id, conflicts: list[dict], author_participant_id) -> list[str]` (`conflicts` are the dicts from `check_on_insert`, each with `candidate_id` + `conflict_id`)
  - `record_decision` calls both inside the outer transaction after detection.

- [ ] **Step 1: Failing tests `tests/test_propagation.py`**
```python
from keel import repo
from keel.principal import Principal
from keel.events import validate_chain
from keel.tools.record_decision import record_decision
import keel.conflict as conflict_pkg
from tests.fakes import ScriptedJudge


async def _person_session(conn, pid, name, session):
    person = await repo.upsert_person(conn, pid, name, name + "-tok")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", session, [])
    return person, part


async def test_change_alert_to_overlapping_claimer_excludes_author(conn, db_pool):
    from datetime import datetime, timedelta, timezone
    pid = await repo.upsert_project(conn, "demo")
    author_person, author_part = await _person_session(conn, pid, "vasan", "s1")
    other_person, other_part = await _person_session(conn, pid, "teammate", "s2")
    fut = datetime.now(timezone.utc) + timedelta(hours=1)
    # both the author's session and the teammate claim api:orders
    await repo.insert_claim(conn, pid, author_part, ["api:orders"], fut)
    await repo.insert_claim(conn, pid, other_part, ["api:orders"], fut)
    out = await record_decision(db_pool, Principal(pid, author_person, "s1"),
                                statement="orders API uses cursor pagination", rationale="r",
                                scope_tags=["api:orders"])
    assert out["conflicts"] == []  # provider=none -> no detection
    # teammate (other_part) alerted; author's own session (author_part) NOT
    teammate_alerts = await repo.pending_alerts_for_participant(conn, other_part)
    author_alerts = await repo.pending_alerts_for_participant(conn, author_part)
    assert len(teammate_alerts) == 1 and teammate_alerts[0]["kind"] == "change"
    assert author_alerts == []
    assert await validate_chain(conn, pid) is True


async def test_no_alert_for_nonoverlapping_or_expired_claim(conn, db_pool):
    from datetime import datetime, timedelta, timezone
    pid = await repo.upsert_project(conn, "demo")
    author_person, author_part = await _person_session(conn, pid, "vasan", "s1")
    other_person, other_part = await _person_session(conn, pid, "teammate", "s2")
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    fut = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.insert_claim(conn, pid, other_part, ["ui:checkout"], fut)   # wrong scope
    _, exp_part = await _person_session(conn, pid, "exp", "s3")
    await repo.insert_claim(conn, pid, exp_part, ["api:orders"], past)     # expired
    await record_decision(db_pool, Principal(pid, author_person, "s1"),
                          statement="orders API uses cursor pagination", rationale="r",
                          scope_tags=["api:orders"])
    assert await repo.pending_alerts_for_participant(conn, other_part) == []
    assert await repo.pending_alerts_for_participant(conn, exp_part) == []


async def test_supersede_alerts_dependent(conn, db_pool):
    pid = await repo.upsert_project(conn, "demo")
    author_person, author_part = await _person_session(conn, pid, "vasan", "s1")
    dep_person, dep_part = await _person_session(conn, pid, "teammate", "s2")
    first = await record_decision(db_pool, Principal(pid, author_person, "s1"),
                                  statement="page size is 20", rationale="r",
                                  scope_tags=["api:orders"])
    await repo.insert_dependency(conn, first["decision_id"], dep_part)
    await record_decision(db_pool, Principal(pid, author_person, "s1"),
                          statement="page size is 50", rationale="r",
                          scope_tags=["api:orders"], supersedes=first["decision_id"])
    alerts = await repo.pending_alerts_for_participant(conn, dep_part)
    assert len(alerts) == 1 and alerts[0]["kind"] == "change"


async def test_conflict_alert_to_candidate_owner(conn, db_pool, monkeypatch):
    monkeypatch.setattr(conflict_pkg, "get_judge", lambda settings=None: ScriptedJudge())
    pid = await repo.upsert_project(conn, "demo")
    owner_person, owner_part = await _person_session(conn, pid, "owner", "s1")
    # owner records cursor; a SECOND session of the owner will receive the conflict alert
    _, owner_part2 = await _person_session(conn, pid, "owner", "s2")
    await record_decision(db_pool, Principal(pid, owner_person, "s1"),
                          statement="orders API uses cursor-based pagination", rationale="r",
                          scope_tags=["api:orders"])
    # a different author records the contradicting offset decision
    author2_person, _ = await _person_session(conn, pid, "vasan2", "s3")
    out = await record_decision(db_pool, Principal(pid, author2_person, "s3"),
                                statement="orders API should use offset pagination", rationale="r",
                                scope_tags=["api:orders"])
    assert len(out["conflicts"]) == 1
    owner_alerts = await repo.pending_alerts_for_participant(conn, owner_part)
    assert any(a["kind"] == "conflict" for a in owner_alerts)
```
> Note on the last test: the author of the offset decision (`vasan2`/s3) is excluded; the candidate (cursor) decision's owner (`owner`) is alerted on its sessions (s1, s2). s1 may also receive a `change` alert depending on claims — the assertion only requires a `conflict` alert exists for the owner.

- [ ] **Step 2: Run → FAIL** (`keel.propagation` missing).

- [ ] **Step 3: Implement `keel/keel/propagation.py`**
```python
from keel import repo
from keel.events import append_event


async def propagate_decision(conn, project_id, decision_row, author_participant_id,
                             superseded_id=None) -> list[str]:
    scope_tags = list(decision_row["scope_tags"])
    targets = {}
    for p in await repo.participants_with_claim_overlap(conn, project_id, scope_tags):
        targets[p["id"]] = p["person_id"]
    dep_ids = [decision_row["id"]] + ([superseded_id] if superseded_id else [])
    for p in await repo.participants_with_dependency(conn, dep_ids):
        targets[p["id"]] = p["person_id"]
    targets.pop(author_participant_id, None)  # never alert the author's own session
    alert_ids = []
    for part_id, person_id in targets.items():
        a = await repo.insert_alert(conn, project_id=project_id, target_participant_id=part_id,
                                    target_person_id=person_id, kind="change",
                                    ref_id=decision_row["id"])
        alert_ids.append(str(a["id"]))
    if alert_ids:
        await append_event(conn, project_id, actor="propagation", action="alerts.created",
                           payload={"kind": "change", "decision_id": str(decision_row["id"]),
                                    "count": len(alert_ids)})
    return alert_ids


async def propagate_conflicts(conn, project_id, conflicts, author_participant_id) -> list[str]:
    alert_ids = []
    for c in conflicts:
        cand = await repo.get_decision(conn, c["candidate_id"])
        if cand is None or cand["owner_person_id"] is None:
            continue
        for p in await repo.participants_of_person(conn, project_id, cand["owner_person_id"]):
            if p["id"] == author_participant_id:
                continue
            a = await repo.insert_alert(conn, project_id=project_id, target_participant_id=p["id"],
                                        target_person_id=cand["owner_person_id"], kind="conflict",
                                        ref_id=c["conflict_id"])
            alert_ids.append(str(a["id"]))
    if alert_ids:
        await append_event(conn, project_id, actor="propagation", action="alerts.created",
                           payload={"kind": "conflict", "count": len(alert_ids)})
    return alert_ids
```

- [ ] **Step 4: Wire into `record_decision.py`** — add `from keel import propagation` (repo already imported). After the detection try/except block and BEFORE the `decision.recorded` event append, insert:
```python
            await propagation.propagate_decision(
                conn, principal.project_id, row, participant["id"], superseded_id)
            await propagation.propagate_conflicts(
                conn, principal.project_id, result["conflicts"], participant["id"])
```
(`participant` is the row fetched earlier in record_decision; `row` is the inserted decision; `superseded_id` is already computed; `result["conflicts"]` are the dicts.)

- [ ] **Step 5: Run → PASS** (4 tests) + full suite green.
`KEEL_TEST_DATABASE_URL=... pytest tests/test_propagation.py tests/test_record_decision.py -v && KEEL_TEST_DATABASE_URL=... pytest -q`

- [ ] **Step 6: Commit**
```bash
git add keel/keel/propagation.py keel/keel/tools/record_decision.py keel/tests/test_propagation.py
git commit -m "feat(keel): propagate change + conflict alerts on record_decision"
```

---

### Task 4: Fill the inbox (piggyback delivery)

**Files:** Modify `keel/keel/inbox.py`; Test `keel/tests/test_inbox.py` (extend)

**Interfaces:**
- Consumes: `repo.get_participant`, `repo.pending_alerts_for_participant`, `repo.mark_alert_delivered`, `repo.get_decision`, `repo.get_conflict`.
- Produces: `build_inbox(conn, principal)` returns `{"alerts": [ {id, kind, ref_id, summary, created_at} ... ], "handoffs": [], "new_lessons": []}`; sets `delivered_at`; empty shape when the session has no participant.

- [ ] **Step 1: Failing tests (extend `tests/test_inbox.py`)**
```python
from keel import repo
from keel.principal import Principal
from keel.inbox import build_inbox


async def test_inbox_returns_unacked_alerts_with_summary(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor pagination",
                                   rationale="r", scope_tags=["api:orders"],
                                   owner_person_id=person, source_participant_id=part)
    await repo.insert_alert(conn, project_id=pid, target_participant_id=part,
                            target_person_id=person, kind="change", ref_id=d["id"])
    box = await build_inbox(conn, Principal(pid, person, "s1"))
    assert len(box["alerts"]) == 1
    al = box["alerts"][0]
    assert al["kind"] == "change" and "cursor pagination" in al["summary"]
    assert box["handoffs"] == [] and box["new_lessons"] == []


async def test_inbox_empty_for_unregistered_session(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")  # no participant for session s9
    box = await build_inbox(conn, Principal(pid, person, "s9"))
    assert box == {"alerts": [], "handoffs": [], "new_lessons": []}


async def test_inbox_drops_after_ack(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    a = await repo.insert_alert(conn, project_id=pid, target_participant_id=part,
                                target_person_id=person, kind="change", ref_id=d["id"])
    await repo.ack_alert(conn, a["id"], part)
    box = await build_inbox(conn, Principal(pid, person, "s1"))
    assert box["alerts"] == []
```

- [ ] **Step 2: Run → FAIL** (stub returns empty; first test fails).

- [ ] **Step 3: Implement `inbox.py`**
```python
from keel import repo
from keel.principal import Principal


async def _summary(conn, kind, ref_id) -> str:
    if kind == "conflict":
        c = await repo.get_conflict(conn, ref_id)
        return c["explanation"] if c else ""
    d = await repo.get_decision(conn, ref_id)
    return d["statement"] if d else ""


async def build_inbox(conn, principal: Principal) -> dict:
    empty = {"alerts": [], "handoffs": [], "new_lessons": []}
    part = await repo.get_participant(conn, principal.project_id, principal.person_id,
                                      principal.session_id)
    if part is None:
        return empty
    rows = await repo.pending_alerts_for_participant(conn, part["id"])
    alerts = []
    for r in rows:
        await repo.mark_alert_delivered(conn, r["id"])
        alerts.append({"id": str(r["id"]), "kind": r["kind"], "ref_id": str(r["ref_id"]),
                       "summary": await _summary(conn, r["kind"], r["ref_id"]),
                       "created_at": r["delivered_at"].isoformat() if r["delivered_at"] else None})
    return {"alerts": alerts, "handoffs": [], "new_lessons": []}
```
> `created_at`: the `alert` table has no `created_at` column (see schema) — use `delivered_at` (just set) as the timestamp. If the reviewer prefers a true creation time, that is a schema follow-up; do not add a column in this task.

- [ ] **Step 4: Run → PASS** + full suite (existing inbox test `test_inbox_stable_empty_shape` still passes — no alerts for that principal).

- [ ] **Step 5: Commit**
```bash
git add keel/keel/inbox.py keel/tests/test_inbox.py
git commit -m "feat(keel): piggyback inbox delivery of pending alerts"
```

---

### Task 5: Alert + claim/dependency tools

**Files:** Create `keel/keel/tools/alerts.py`, `keel/keel/tools/claims.py`; Test `keel/tests/test_alert_claim_tools.py`

**Interfaces:**
- `alerts.list_alerts(pool, principal) -> dict` → `{"alerts": [...same shape as inbox...], "inbox": <build_inbox>}`
- `alerts.ack_alert(pool, principal, *, alert_id, note=None) -> dict` → `{"acknowledged": bool, "inbox": ...}`; `acknowledged` False if not the caller's / already acked.
- `claims.declare_dependency(pool, principal, *, decision_id) -> dict` → `{"dependency_id": str, "inbox": ...}`; errors if the decision is not in the caller's project.
- `claims.claim_scope(pool, principal, *, scope_tags, ttl_seconds=3600) -> dict` → `{"claim_id": str, "scope_tags": [...normalized...], "inbox": ...}`
- `claims.release_scope(pool, principal, *, scope_tags=None) -> dict` → `{"released": int, "inbox": ...}`
- All resolve the caller's participant via `repo.get_participant`; raise `LookupError` if unregistered.

- [ ] **Step 1: Failing tests `tests/test_alert_claim_tools.py`**
```python
import pytest
from keel import repo
from keel.principal import Principal
from keel.tools.alerts import list_alerts, ack_alert
from keel.tools.claims import declare_dependency, claim_scope, release_scope


async def _ctx(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    return pid, person, part


async def test_claim_and_release(conn, db_pool):
    pid, person, part = await _ctx(conn)
    out = await claim_scope(db_pool, Principal(pid, person, "s1"),
                            scope_tags=["API: Orders"], ttl_seconds=3600)
    assert out["scope_tags"] == ["api:orders"] and out["claim_id"]
    got = await repo.participants_with_claim_overlap(conn, pid, ["api:orders"])
    assert [r["id"] for r in got] == [part]
    rel = await release_scope(db_pool, Principal(pid, person, "s1"), scope_tags=["api:orders"])
    assert rel["released"] == 1


async def test_declare_dependency(conn, db_pool):
    pid, person, part = await _ctx(conn)
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    out = await declare_dependency(db_pool, Principal(pid, person, "s1"), decision_id=str(d["id"]))
    assert out["dependency_id"]
    assert [r["id"] for r in await repo.participants_with_dependency(conn, [d["id"]])] == [part]


async def test_list_and_ack_alert(conn, db_pool):
    pid, person, part = await _ctx(conn)
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    a = await repo.insert_alert(conn, project_id=pid, target_participant_id=part,
                                target_person_id=person, kind="change", ref_id=d["id"])
    listed = await list_alerts(db_pool, Principal(pid, person, "s1"))
    assert len(listed["alerts"]) == 1
    acked = await ack_alert(db_pool, Principal(pid, person, "s1"), alert_id=str(a["id"]))
    assert acked["acknowledged"] is True
    assert (await list_alerts(db_pool, Principal(pid, person, "s1")))["alerts"] == []


async def test_ack_other_participants_alert_fails(conn, db_pool):
    pid, person, part = await _ctx(conn)
    other = await repo.upsert_person(conn, pid, "teammate", "h2")
    opart = await repo.upsert_participant(conn, pid, other, "cc", "deep", "s2", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    a = await repo.insert_alert(conn, project_id=pid, target_participant_id=opart,
                                target_person_id=other, kind="change", ref_id=d["id"])
    out = await ack_alert(db_pool, Principal(pid, person, "s1"), alert_id=str(a["id"]))
    assert out["acknowledged"] is False  # not the caller's alert
    assert len(await repo.pending_alerts_for_participant(conn, opart)) == 1


async def test_declare_dependency_foreign_decision_errors(conn, db_pool):
    pid, person, part = await _ctx(conn)
    other = await repo.upsert_project(conn, "other")
    operson = await repo.upsert_person(conn, other, "x", "h3")
    opart = await repo.upsert_participant(conn, other, operson, "cc", "deep", "os", [])
    foreign = await repo.insert_decision(conn, project_id=other, statement="f", rationale="r",
                                         scope_tags=["api:orders"], owner_person_id=operson,
                                         source_participant_id=opart)
    with pytest.raises(ValueError):
        await declare_dependency(db_pool, Principal(pid, person, "s1"),
                                 decision_id=str(foreign["id"]))
```

- [ ] **Step 2: Run → FAIL** (modules missing).

- [ ] **Step 3: Implement `tools/claims.py`**
```python
from datetime import datetime, timedelta, timezone
from keel import repo
from keel.scope import normalize_tags
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal


async def _require_participant(conn, principal):
    part = await repo.get_participant(conn, principal.project_id, principal.person_id,
                                      principal.session_id)
    if part is None:
        raise LookupError("session not registered; call register_session first")
    return part


async def declare_dependency(pool, principal: Principal, *, decision_id) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            part = await _require_participant(conn, principal)
            d = await repo.get_decision(conn, decision_id)
            if d is None or d["project_id"] != principal.project_id:
                raise ValueError("decision not found in this project")
            dep = await repo.insert_dependency(conn, decision_id, part["id"])
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="dependency.declared",
                               payload={"decision_id": str(decision_id)})
            box = await build_inbox(conn, principal)
    return {"dependency_id": str(dep["id"]), "inbox": box}


async def claim_scope(pool, principal: Principal, *, scope_tags, ttl_seconds=3600) -> dict:
    tags = normalize_tags(scope_tags)
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    async with pool.acquire() as conn:
        async with conn.transaction():
            part = await _require_participant(conn, principal)
            claim = await repo.insert_claim(conn, principal.project_id, part["id"], tags, expires)
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="scope.claimed", payload={"scope_tags": tags})
            box = await build_inbox(conn, principal)
    return {"claim_id": str(claim["id"]), "scope_tags": tags, "inbox": box}


async def release_scope(pool, principal: Principal, *, scope_tags=None) -> dict:
    tags = normalize_tags(scope_tags) if scope_tags else None
    async with pool.acquire() as conn:
        async with conn.transaction():
            part = await _require_participant(conn, principal)
            n = await repo.release_claims(conn, part["id"], tags)
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="scope.released", payload={"scope_tags": tags, "count": n})
            box = await build_inbox(conn, principal)
    return {"released": n, "inbox": box}
```

- [ ] **Step 4: Implement `tools/alerts.py`**
```python
from keel import repo
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal


async def _require_participant(conn, principal):
    part = await repo.get_participant(conn, principal.project_id, principal.person_id,
                                      principal.session_id)
    if part is None:
        raise LookupError("session not registered; call register_session first")
    return part


async def list_alerts(pool, principal: Principal) -> dict:
    async with pool.acquire() as conn:
        box = await build_inbox(conn, principal)
    return {"alerts": box["alerts"], "inbox": box}


async def ack_alert(pool, principal: Principal, *, alert_id, note=None) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            part = await _require_participant(conn, principal)
            ok = await repo.ack_alert(conn, alert_id, part["id"])
            if ok:
                await append_event(conn, principal.project_id,
                                   actor=f"person:{principal.person_id}/session:{principal.session_id}",
                                   action="alert.acknowledged",
                                   payload={"alert_id": str(alert_id), "note": note})
            box = await build_inbox(conn, principal)
    return {"acknowledged": ok, "inbox": box}
```

- [ ] **Step 5: Run → PASS** (5 tests) + full suite.

- [ ] **Step 6: Commit**
```bash
git add keel/keel/tools/alerts.py keel/keel/tools/claims.py keel/tests/test_alert_claim_tools.py
git commit -m "feat(keel): declare_dependency, claim_scope/release_scope, list_alerts/ack_alert tools"
```

---

### Task 6: resolve_conflict tool (owner-only)

**Files:** Create `keel/keel/tools/resolve_conflict.py`; Test `keel/tests/test_resolve_conflict.py`

**Interfaces:**
- `resolve_conflict(pool, principal, *, conflict_id, resolution) -> dict` → `{"resolved": True, "inbox": ...}`; raises `PermissionError` if the caller's person is not the owner of the conflict's `decision_a_id`; raises `LookupError` if the conflict does not exist / not in project.

- [ ] **Step 1: Failing tests `tests/test_resolve_conflict.py`**
```python
import pytest
from keel import repo
from keel.principal import Principal
from keel.tools.resolve_conflict import resolve_conflict


async def _setup(conn):
    pid = await repo.upsert_project(conn, "demo")
    owner = await repo.upsert_person(conn, pid, "owner", "h1")
    owner_part = await repo.upsert_participant(conn, pid, owner, "cc", "deep", "s1", [])
    other = await repo.upsert_person(conn, pid, "other", "h2")
    await repo.upsert_participant(conn, pid, other, "cc", "deep", "s2", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=owner,
                                   source_participant_id=owner_part)
    c = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                   subject_type="decision", subject_ref=str(d["id"]),
                                   relation="contradicts", severity="high", explanation="e")
    return pid, owner, other, c


async def test_owner_resolves(conn, db_pool):
    pid, owner, other, c = await _setup(conn)
    out = await resolve_conflict(db_pool, Principal(pid, owner, "s1"),
                                 conflict_id=str(c["id"]), resolution="keep")
    assert out["resolved"] is True
    got = await repo.get_conflict(conn, c["id"])
    assert got["status"] == "resolved" and got["resolution"] == "keep" and got["resolved_by"] == owner


async def test_non_owner_cannot_resolve(conn, db_pool):
    pid, owner, other, c = await _setup(conn)
    with pytest.raises(PermissionError):
        await resolve_conflict(db_pool, Principal(pid, other, "s2"),
                               conflict_id=str(c["id"]), resolution="keep")
    assert (await repo.get_conflict(conn, c["id"]))["status"] == "open"


async def test_missing_conflict_errors(conn, db_pool):
    pid, owner, other, c = await _setup(conn)
    import uuid
    with pytest.raises(LookupError):
        await resolve_conflict(db_pool, Principal(pid, owner, "s1"),
                               conflict_id=str(uuid.uuid4()), resolution="keep")
```

- [ ] **Step 2: Run → FAIL** (module missing).

- [ ] **Step 3: Implement `tools/resolve_conflict.py`**
```python
from keel import repo
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal


async def resolve_conflict(pool, principal: Principal, *, conflict_id, resolution) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            c = await repo.get_conflict(conn, conflict_id)
            if c is None or c["project_id"] != principal.project_id:
                raise LookupError("conflict not found in this project")
            cand = await repo.get_decision(conn, c["decision_a_id"])
            if cand is None or cand["owner_person_id"] != principal.person_id:
                raise PermissionError("only the decision owner may resolve this conflict")
            await repo.resolve_conflict(conn, conflict_id, resolution, principal.person_id)
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="conflict.resolved",
                               payload={"conflict_id": str(conflict_id), "resolution": resolution})
            box = await build_inbox(conn, principal)
    return {"resolved": True, "inbox": box}
```

- [ ] **Step 4: Run → PASS** (3 tests) + full suite.

- [ ] **Step 5: Commit**
```bash
git add keel/keel/tools/resolve_conflict.py keel/tests/test_resolve_conflict.py
git commit -m "feat(keel): resolve_conflict tool (owner-only)"
```

---

### Task 7: Register the 6 new MCP tools

**Files:** Modify `keel/keel/server.py`; Test `keel/tests/test_tool_descriptions.py` (extend)

**Interfaces:**
- Consumes: the Task 5/6 handlers.
- Produces: `@mcp.tool()` wrappers + `_HANDLERS` entries for `declare_dependency`, `claim_scope`, `release_scope`, `list_alerts`, `ack_alert`, `resolve_conflict`, each with a docstring and using `current_principal()` + `db.get_pool()`.

- [ ] **Step 1: Extend `tests/test_tool_descriptions.py`**
Update the expected name set and add a description assertion:
```python
    expected = {"register_session", "get_context", "record_decision", "check_intent",
                "declare_dependency", "claim_scope", "release_scope", "list_alerts",
                "ack_alert", "resolve_conflict"}
    assert set(tools) == expected
```
and (in the behavior test) assert each new tool has a non-empty >=20-char description.

- [ ] **Step 2: Run → FAIL** (missing tools).

- [ ] **Step 3: Add to `server.py`** — imports and wrappers (follow the existing `check_intent` pattern). Imports:
```python
from keel.tools.claims import declare_dependency as _declare_dependency, \
    claim_scope as _claim_scope, release_scope as _release_scope
from keel.tools.alerts import list_alerts as _list_alerts, ack_alert as _ack_alert
from keel.tools.resolve_conflict import resolve_conflict as _resolve_conflict
```
Wrappers:
```python
@mcp.tool()
async def declare_dependency(decision_id: str) -> dict:
    """Record that this session depends on a decision, so you are alerted when it changes."""
    return await _declare_dependency(db.get_pool(), current_principal(), decision_id=decision_id)


@mcp.tool()
async def claim_scope(scope_tags: list[str], ttl_seconds: int = 3600) -> dict:
    """Claim the scope you are actively working so new/changed decisions there alert you. Not a lock."""
    return await _claim_scope(db.get_pool(), current_principal(), scope_tags=scope_tags,
                              ttl_seconds=ttl_seconds)


@mcp.tool()
async def release_scope(scope_tags: list[str] | None = None) -> dict:
    """Release scope claims for this session (all, or those overlapping scope_tags)."""
    return await _release_scope(db.get_pool(), current_principal(), scope_tags=scope_tags)


@mcp.tool()
async def list_alerts() -> dict:
    """List this session's unacknowledged alerts (conflicts and changes affecting your work)."""
    return await _list_alerts(db.get_pool(), current_principal())


@mcp.tool()
async def ack_alert(alert_id: str, note: str | None = None) -> dict:
    """Acknowledge an alert so it stops appearing; optionally attach a note."""
    return await _ack_alert(db.get_pool(), current_principal(), alert_id=alert_id, note=note)


@mcp.tool()
async def resolve_conflict(conflict_id: str, resolution: str) -> dict:
    """Resolve a conflict on a decision you own (keep, supersede, or reject). Owner only."""
    return await _resolve_conflict(db.get_pool(), current_principal(), conflict_id=conflict_id,
                                   resolution=resolution)
```
Add each to `_HANDLERS`:
```python
    "declare_dependency": lambda p, a: _declare_dependency(db.get_pool(), p, **a),
    "claim_scope": lambda p, a: _claim_scope(db.get_pool(), p, **a),
    "release_scope": lambda p, a: _release_scope(db.get_pool(), p, **a),
    "list_alerts": lambda p, a: _list_alerts(db.get_pool(), p, **a),
    "ack_alert": lambda p, a: _ack_alert(db.get_pool(), p, **a),
    "resolve_conflict": lambda p, a: _resolve_conflict(db.get_pool(), p, **a),
```
> `list_alerts` takes no kwargs; its `_HANDLERS` lambda must call `_list_alerts(db.get_pool(), p)` (ignore `a`/pass `**a` with empty dict). Use `lambda p, a: _list_alerts(db.get_pool(), p)`.

- [ ] **Step 4: Run → PASS** (descriptions test) + FULL suite green.
`KEEL_TEST_DATABASE_URL=... pytest -q`

- [ ] **Step 5: Commit**
```bash
git add keel/keel/server.py keel/tests/test_tool_descriptions.py
git commit -m "feat(keel): register propagation/alert MCP tools"
```

---

## Self-Review Notes
- **Spec coverage:** §2 propagation → Task 3 (+ repo Task 1, conflict_id Task 2); §4 inbox → Task 4; §5 tools → Tasks 5,6,7; §6 repo helpers → Task 1; §1 principles (append-only events, owner-only, exclude author) → Tasks 3,5,6 tests.
- **Review Focus → tests:** author-self-exclusion (Task 3 `test_change_alert_...excludes_author`); expired claim (Task 1 `test_claim_overlap_active_only` + Task 3 `test_no_alert_for_nonoverlapping_or_expired_claim`); non-owner resolve (Task 6 `test_non_owner_cannot_resolve`); cross-participant ack (Task 5 `test_ack_other_participants_alert_fails`); unregistered session inbox (Task 4 `test_inbox_empty_for_unregistered_session`).
- **Type consistency:** `participants_with_claim_overlap`/`_with_dependency`/`participants_of_person` all return participant rows (have `id`, `person_id`); propagation keys targets by `id`→`person_id`; `insert_alert` kwargs match the alert columns; `ack_alert(conn, alert_id, participant_id)->bool` used by the tool; `check_on_insert` dicts carry `candidate_id`+`conflict_id` consumed by `propagate_conflicts`.
- **alert table has no `created_at`:** inbox uses `delivered_at` for the timestamp (noted in Task 4); no schema change.
- **Propagation not savepoint-wrapped:** intentional (spec §8 risk) — alert inserts are simple and should be atomic with the decision; only *detection* has the best-effort savepoint.
- **Open risk:** alert fan-out on broad scopes is unbounded (spec §8); acceptable this slice, note for a later cap.
