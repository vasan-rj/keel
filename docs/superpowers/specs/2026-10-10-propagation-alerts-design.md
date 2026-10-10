# Propagation & Alerts Slice — Design Spec

**Version:** 0.1 · **Last updated:** 2026-10-10 · **Status:** approved for planning

Makes recorded changes *propagate*: when a decision is recorded (or supersedes another) or a conflict is detected, create `alert` rows for the affected participants and deliver them via the piggyback `inbox`. Adds the P0 tools that drive and consume alerts. Source of truth: `context/ARCHITECTURE.md` §8 (propagation), §7.1 (who gets alerted on conflict), §6.3 (delivery), §4 (tables), §5 (tools), §1 (principles). Builds on Slice 1 (schema + inbox stub + 4 tools) and Slice 2 (conflict detection).

## 0. Scope

- **In:** propagation engine (`change` alerts on decision record/supersede; `conflict` alerts on detection), piggyback `inbox` delivery (fill the stub), and tools: `declare_dependency`, `claim_scope`/`release_scope`, `list_alerts`/`ack_alert`, `resolve_conflict`.
- **Out (named follow-ups):** handoff (`create_handoff`/`accept_handoff`/`decline_handoff`) — next slice; drift / `report_activity`; Claude Code hook adapter; Slack; dashboard; lessons.
- **Delivery:** piggyback `inbox` only (best-effort, "before the next action", §6.3). No server push, no hooks.

## 1. Principles honored
- **Humans resolve; Keel flags** (§1.3): alerts are informational; `resolve_conflict` is owner-only, no auto-overwrite.
- **Warn, never block** (§1.3): alert creation never fails or blocks the triggering write.
- **Append-only** (§1.6): every alert/claim/dependency/ack/resolve writes an `event`; hash chain stays valid.
- **Decisions are data** (§11): alert summaries built from decision/conflict text are data, not instructions.
- **Deterministic + transactional**: propagation is pure DB work inside the triggering write's transaction (no LLM).

## 2. Propagation logic (ARCHITECTURE §8)

On a recorded decision, inside `record_decision`'s outer transaction (after detection, before the `decision.recorded` event):

1. **`propagate_decision(conn, project_id, decision_row, author_participant_id, superseded_id)`** → `change` alerts.
   - Targets = participants with an **active claim** (`expires_at` null or future) whose `scope_tags && decision.scope_tags`, UNION participants with a **dependency** (`dependent_type='participant'`) on `decision_row.id` or on `superseded_id`.
   - **Exclude `author_participant_id`** (the author's own session). The author's *other* sessions are included only if they independently hold a claim/dependency (intra-person beat = the other session claimed the scope).
   - Insert `alert(kind='change', ref_id=decision_row.id, target_participant_id, target_person_id)` per distinct target; one `alerts.created` event summarizing the batch.
2. **`propagate_conflicts(conn, project_id, conflicts, author_participant_id)`** → `conflict` alerts.
   - For each detected conflict (from the pipeline's returned list, which now carries the persisted `conflict_id` and `candidate_id`): target = active participants of the **candidate decision's owner** (`decision.owner_person_id`), excluding `author_participant_id`.
   - Insert `alert(kind='conflict', ref_id=conflict_id, target_participant_id, target_person_id)`; one `alerts.created` event.
   - Skipped when detection degraded/disabled (empty conflicts list).

Propagation runs in the **outer** transaction (durable with the decision), not the detection savepoint. It uses the conflicts the pipeline already returned — no re-query.

## 3. Pipeline change (carry the conflict id)

`keel/keel/conflict/pipeline.py`: capture `insert_conflict(...)`'s returned row id and set it on the `Conflict` (new field `conflict_id: str | None = None`, default None so `persist=False` / check_intent leaves it None). `check_on_insert` already returns `[c.__dict__ ...]`, so `conflict_id` and `candidate_id` flow out unchanged.

## 4. Inbox delivery (fill the stub)

`keel/keel/inbox.py` `build_inbox(conn, principal)`:
- Resolve the caller's participant (`repo.get_participant(project_id, person_id, session_id)`); if none, return empty shape (unregistered session).
- `alerts` = unacknowledged alerts for this participant (`target_participant_id = participant.id AND acknowledged_at IS NULL`), each expanded to `{id, kind, ref_id, summary, created_at}` where `summary` comes from the referenced decision statement (`kind='change'`) or conflict explanation (`kind='conflict'`).
- Set `delivered_at = now()` for returned alerts whose `delivered_at` is null (first-delivery timestamp); keep returning until acked.
- `handoffs` = `[]` (key kept), `new_lessons` = `[]`.

Every tool response already calls `build_inbox` (register_session/get_context/record_decision/check_intent), so delivery is automatic once the stub is filled.

## 5. Tools (ARCHITECTURE §5)

MCP wrappers in `server.py` (+ `_HANDLERS` + docstrings, following the existing pattern; principal from the auth contextvar). Handlers in `keel/keel/tools/`:

| Tool | Behavior |
|---|---|
| `declare_dependency(decision_id)` | Insert `dependency(decision_id, dependent_type='participant', dependent_ref=<caller participant id>)`; event. Validates the decision exists in the caller's project. |
| `claim_scope(scope_tags, ttl_seconds=3600)` | Normalize tags; insert `claim(participant_id=caller, scope_tags, expires_at=now+ttl)`; event. Not a lock. |
| `release_scope(scope_tags=None)` | Delete the caller's claims (all, or those overlapping `scope_tags`); event. |
| `list_alerts()` | The caller's unacknowledged alerts (same shape as the inbox `alerts`). |
| `ack_alert(alert_id, note=None)` | Set `acknowledged_at=now()` on the caller's alert (error if not theirs / not found); event with the note. |
| `resolve_conflict(conflict_id, resolution)` | **Owner-only**: caller's person must equal the conflict's candidate decision (`decision_a_id`) owner, else `PermissionError`. Set `conflict.status='resolved'`, `resolution`, `resolved_by=<person>`; event. |

All return `{..., "inbox": <build_inbox>}` so they also deliver pending alerts.

## 6. Repo helpers (new, in `keel/keel/repo.py`)
- `participants_with_claim_overlap(conn, project_id, scope_tags) -> list[Record]` (active claims, `expires_at IS NULL OR > now()`, `scope_tags && $`, join participant, `status='active'`).
- `participants_with_dependency(conn, decision_ids: list) -> list[Record]` (dependency `dependent_type='participant'`, `decision_id = ANY`, resolve `dependent_ref`→participant).
- `participants_of_person(conn, project_id, person_id) -> list[Record]` (active).
- `insert_alert(conn, *, project_id, target_participant_id, target_person_id, kind, ref_id) -> Record`.
- `pending_alerts_for_participant(conn, participant_id) -> list[Record]` (unacked).
- `mark_alert_delivered(conn, alert_id)`; `ack_alert(conn, alert_id, participant_id) -> bool` (acked only if owned+unacked).
- `insert_dependency(conn, decision_id, participant_id)`.
- `insert_claim(conn, project_id, participant_id, scope_tags, expires_at)`; `release_claims(conn, participant_id, scope_tags=None)`.
- `get_conflict(conn, conflict_id)`; `resolve_conflict(conn, conflict_id, resolution, resolved_by) -> None`.

## 7. Testing (TDD, hermetic — no network)
- `propagate_decision`: a second participant with an overlapping active claim gets a `change` alert on a new decision; the author's own session is excluded; the author's *other* session that holds a claim IS alerted; a non-overlapping-scope claim → no alert; an expired claim → no alert.
- supersede: a participant with a `dependency` on the superseded decision gets a `change` alert.
- `propagate_conflicts`: inject a fake judge (Slice-2 pattern) so a conflict is detected; the candidate decision owner's other session gets a `conflict` alert referencing the conflict id; the author session is excluded; degraded/disabled detection → no conflict alert.
- `build_inbox`: returns unacked alerts with expanded summaries; after `ack_alert` the alert no longer appears; unregistered session → empty shape.
- tools: `declare_dependency`/`claim_scope`/`release_scope` create/remove rows + events; `list_alerts` matches the inbox; `ack_alert` on someone else's alert errors; `resolve_conflict` by a non-owner raises `PermissionError`, by the owner sets status/resolution/resolved_by.
- event chain stays valid after propagation + each tool (`validate_chain`).
- full suite stays green (72 passed, 2 skipped baseline).

## 8. Risks
- **Alert fan-out**: a decision on a broad scope with many claimers creates many alerts — bounded by participant count; acceptable, no cap this slice (note for later).
- **Self-alert avoidance** relies on `author_participant_id`; a decision recorded by a session that also claims the scope must not alert itself — the exclude covers it (test).
- **Propagation is in the write txn**: a bug there could roll back the decision. Mitigation: propagation is simple INSERTs over validated data; wrap in the same outer txn (atomic by design — an alert failure *should* surface, unlike the best-effort detection which has its savepoint). Keep it minimal and well-tested.
