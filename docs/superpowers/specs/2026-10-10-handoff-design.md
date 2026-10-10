# Handoff Slice — Design Spec

**Version:** 0.1 · **Last updated:** 2026-10-10 · **Status:** approved for planning

Makes scope handoff first-class: a registered participant hands a scope to another person (optionally a specific session) with context attached; the receiver sees it in their piggyback `inbox` and accepts or declines. Accepting transfers the claim and declares dependencies so future changes propagate to the receiver. Source of truth: `context/ARCHITECTURE.md` §4 (`handoff` table), §5 (tools), §8 (handoff flow, line 257), §1 (principles); `context/PRD.md` FR-33/34/35. Builds on Slice 1 (schema + inbox + 4 tools), Slice 2 (conflict detection), Slice 3 (claims, dependencies, alerts, inbox delivery).

## 0. Scope

- **In:** `create_handoff`, `accept_handoff`, `decline_handoff`; snapshot of active decisions + open conflicts + active claims overlapping the scope at create time; piggyback `inbox` delivery of pending handoffs (fill the `handoffs` key, currently `[]`); events for create/accept/decline; 5 new repo helpers.
- **Out (named follow-ups):** Claude Code hook adapter (SessionStart/UserPromptSubmit injection); dashboard; `list_handoffs` tool; re-handoff / expiry policy; drift / `report_activity`; lessons; model router.
- **Delivery:** piggyback `inbox` only (best-effort, "before the next action", §6.3). No hooks, no push.

## 1. Decisions (resolved in brainstorming)
- **Receiver identity:** `to_person` is a **display_name**, resolved by `(project_id, display_name)` (same identifier `person` uses). No such person → `LookupError`.
- **Accept = true transfer:** create a claim for the receiver on the handoff `scope_tags`, **release the sender's overlapping claims**, and declare receiver dependencies on each snapshotted decision. Sender steps off the area.
- **Scope:** the 3 tools + inbox delivery only; piggyback only.

## 2. Principles honored
- **Humans resolve** (§1.3): only the receiver (caller's person == `to_person_id`) may accept or decline; sender cannot self-accept.
- **Warn, never block** (§1.3): handoff creation never blocks any other work; a handoff is informational until accepted.
- **Append-only** (§1.6): create/accept/decline each append an `event`; hash chain stays valid.
- **Decisions are data** (§11): the inbox handoff carries decision/conflict **ids and the note**, not instructions to execute.
- **Deterministic + transactional:** all pure DB work, no LLM. Accept's claim-transfer + dependency inserts + status flip are one atomic transaction — a failure surfaces, no half-transfer.

## 3. Handoff lifecycle

### 3.1 create_handoff(pool, principal, *, to_person, scope_tags, note=None, to_session=None) -> dict
Inside one transaction:
1. `_require_participant` (sender must be registered) → `LookupError` if not.
2. `tags = normalize_tags(scope_tags)` (raises `ValueError` if empty).
3. Resolve receiver: `repo.get_person_by_name(conn, project_id, to_person)` → `LookupError("recipient not found in this project")` if none.
4. Optional `to_session`: if given, resolve the receiver's participant `get_participant(project_id, receiver_person_id, to_session)`; store its id as `to_participant_id` (null if not given / not found — delivery falls back to all the receiver's sessions).
5. **Snapshot** (ids only):
   - `decision_ids` = active decisions overlapping `tags` (`repo.active_decisions(conn, project_id, tags)` → their ids).
   - `conflict_ids` = open conflicts whose `decision_a` overlaps `tags` (`repo.open_conflicts_in_scope(conn, project_id, tags)` → ids).
   - Claims: the attachment is the scope itself; the sender's active claims overlapping `tags` are what accept will release. Not stored separately (derivable at accept time); snapshot is `scope_tags` + `decision_ids` + `conflict_ids` per the `handoff` columns.
6. `insert_handoff(status='pending', from_participant_id=sender, to_person_id, to_participant_id?, scope_tags=tags, decision_ids, conflict_ids, note)`.
7. `handoff.created` event (actor = sender person/session; payload = handoff_id, to_person_id, scope_tags, counts).
8. Return `{"handoff_id", "status": "pending", "scope_tags": tags, "decision_ids": [...], "conflict_ids": [...], "inbox": build_inbox}`.

### 3.2 accept_handoff(pool, principal, *, handoff_id) -> dict
Inside one transaction:
1. Parse `handoff_id` via `as_uuid`; malformed → `LookupError`.
2. `h = get_handoff(conn, hid)`; `None` or `h["project_id"] != project_id` → `LookupError("handoff not found in this project")`.
3. **Receiver-only:** `h["to_person_id"] != principal.person_id` → `PermissionError`.
4. Status must be `pending` → else `ValueError("handoff is not pending")` (already accepted/declined).
5. `receiver_part = _require_participant` (the accepting session must be registered).
6. **Transfer:**
   - `insert_claim(conn, project_id, receiver_part["id"], h["scope_tags"], expires=now+default_ttl)` (default 3600s, same as claim_scope).
   - `release_claims(conn, h["from_participant_id"], h["scope_tags"])` — release the sender's overlapping claims (partial-tag-safe, per Slice 3 fix).
   - For each `decision_id` in `h["decision_ids"]` that still exists: `insert_dependency(conn, decision_id, receiver_part["id"])`.
7. `set_handoff_status(conn, hid, 'accepted', accepted_at=now, to_participant_id=receiver_part["id"])`.
8. `handoff.accepted` event.
9. Return `{"handoff_id", "status": "accepted", "claimed_scope_tags": [...], "dependencies": <n>, "inbox": build_inbox}`.

### 3.3 decline_handoff(pool, principal, *, handoff_id) -> dict
Parse id; load; receiver-only; pending-only; `set_handoff_status(hid, 'declined')`; `handoff.declined` event. No claim/dependency changes. Return `{"handoff_id", "status": "declined", "inbox": build_inbox}`.

## 4. Inbox delivery (fill the `handoffs` key)

`keel/keel/inbox.py` `build_inbox` — after the alerts block, add:
- `handoffs` = `pending_handoffs_for_person(conn, participant_person_id)`: handoffs with `status='pending'` and `to_person_id = <caller person>`, each expanded to `{id, from_participant_id, scope_tags, decision_ids, conflict_ids, note, created_at}`.
- The participant lookup already happens for alerts; reuse the caller's `person_id` (available from `principal.person_id`). Unregistered session → empty shape (already handled: returns early before alerts/handoffs).
- `new_lessons` stays `[]`.

Pending handoffs keep appearing until accepted or declined (no per-session delivered flag this slice — handoff is person-targeted, not participant-targeted).

## 5. Repo helpers (new, in `keel/keel/repo.py`)
- `get_person_by_name(conn, project_id, display_name) -> Record | None`.
- `insert_handoff(conn, *, project_id, from_participant_id, to_person_id, to_participant_id, scope_tags, decision_ids, conflict_ids, note) -> Record`.
- `get_handoff(conn, handoff_id) -> Record | None`.
- `pending_handoffs_for_person(conn, project_id, to_person_id) -> list[Record]` (`status='pending'`, newest first by `created_at`).
- `open_conflicts_in_scope(conn, project_id, scope_tags) -> list[Record]` (status `open`, join `decision` on `decision_a_id`, `scope_tags && $`).
- `set_handoff_status(conn, handoff_id, status, *, accepted_at=None, to_participant_id=None) -> None` (updates status; sets accepted_at/to_participant_id when provided).

Reuse: `active_decisions`, `insert_claim`, `release_claims`, `insert_dependency`, `get_participant`, `get_decision`.

## 6. Tools + registration
- `keel/keel/tools/handoff.py`: `create_handoff`, `accept_handoff`, `decline_handoff` — `_require_participant` + `as_uuid` at the id boundary; each returns `{..., "inbox": build_inbox}`.
- `keel/keel/server.py`: 3 `@mcp.tool()` wrappers (docstrings ≥20 chars, `current_principal()` + `db.get_pool()`) + 3 `_HANDLERS` entries. Update `tests/test_tool_descriptions.py` expected name set to 13 tools.

## 7. Testing (TDD, hermetic — no network; autouse fixture forces provider=none)
- **create_handoff:** registered sender hands `api:orders` to a named teammate → a `pending` handoff exists with the active decisions + open conflicts in scope snapshotted; unknown `to_person` → `LookupError`; empty scope → `ValueError`; unregistered sender → `LookupError`; event chain valid.
- **inbox:** the receiver's session sees the pending handoff in `inbox["handoffs"]` with the note + ids; a third party (different person) does not; after accept it no longer appears.
- **accept_handoff (transfer):** receiver accepts → receiver holds a claim on the scope; the **sender's** overlapping claim is gone; the receiver's participant has dependencies on each snapshotted decision; status `accepted`, `accepted_at` set, `to_participant_id` = accepting session; a subsequent `record_decision` on the scope by a third party now alerts the receiver (end-to-end: transfer wired propagation). 
- **receiver-only:** a non-receiver calling accept/decline → `PermissionError`; handoff unchanged.
- **status guard:** accept or decline on an already-accepted/declined handoff → `ValueError`; no duplicate claim/dependency.
- **decline_handoff:** pending→declined, no claim/dependency change; event chain valid.
- **malformed id:** accept/decline with a non-uuid id → `LookupError` (not a DataError).
- full suite stays green (97 passed, 2 skipped baseline → grows).

## 8. Risks
- **Snapshot staleness:** decision_ids are captured at create time; one may be superseded before accept. Mitigation: accept skips dependencies for decisions that no longer exist; a superseded-but-present decision still gets a dependency (receiver then gets change alerts — acceptable, that is the point).
- **Double-claim window:** between create and accept both sender and receiver may briefly hold claims (sender's released only on accept). Acceptable — claims are not locks.
- **Accept atomicity:** claim insert + sender release + dependency inserts + status flip are one transaction; unlike best-effort detection, a failure here **should** surface (no savepoint), consistent with Slice 3 propagation. Keep the handler minimal and well-tested.
- **Fan-out / re-handoff:** no cap and no re-handoff policy this slice (noted for later).
