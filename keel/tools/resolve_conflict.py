from typing import Literal

from keel import propagation, repo
from keel.ids import as_uuid
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal
from keel.scope import lock_scope_tags


ResolutionOutcome = Literal["keep_existing", "accept_new"]


async def _lock_resolution_decisions(conn, principal, conflict, outcome):
    existing_id = conflict["decision_a_id"]
    subject_id = None
    if conflict["subject_type"] == "decision":
        try:
            subject_id = as_uuid(conflict["subject_ref"])
        except ValueError:
            raise ValueError("conflict subject is not a decision in this project") from None
    elif outcome == "accept_new":
        raise ValueError("accept_new requires a recorded decision")

    ids = {existing_id} | ({subject_id} if subject_id is not None else set())
    scopes = set()
    for decision_id in ids:
        row = await repo.get_decision(conn, decision_id)
        if row is None or row["project_id"] != principal.project_id:
            raise ValueError("conflict decisions must belong to this project")
        scopes.update(row["scope_tags"])
    # Recording also takes these scope locks before changing decisions. Without
    # them an in-flight judge could persist a verdict against a retired decision.
    await lock_scope_tags(conn, principal.project_id, list(scopes))
    # Consistent ordering also serializes resolutions of different conflicts
    # involving the same decisions, without taking locks in opposing orders.
    rows = {r["id"]: r for r in await repo.lock_decisions(conn, principal.project_id, list(ids))}
    if set(rows) != ids:
        raise ValueError("conflict decisions must belong to this project")
    return rows, existing_id, subject_id


async def _apply_outcome(conn, principal, rows, existing_id, subject_id, outcome):
    existing = rows[existing_id]
    if existing["owner_person_id"] != principal.person_id:
        raise PermissionError("only the decision owner may resolve this conflict")
    if any(r["status"] != "active" for r in rows.values()):
        raise ValueError("conflict decision is no longer active; refresh context")

    kept = existing
    retired = rows.get(subject_id) if subject_id != existing_id else None
    if outcome == "accept_new":
        if retired is None:
            raise ValueError("accept_new requires a different recorded decision")
        kept, retired = retired, existing
        if kept["supersedes_id"] not in (None, existing_id):
            raise ValueError("new decision already supersedes a different decision")
        await repo.mark_superseded(conn, retired["id"])
        await repo.link_supersedes(conn, kept["id"], retired["id"])
    elif retired is not None:
        await repo.reject_decision(conn, retired["id"])
    return kept, retired


async def resolve_conflict(pool, principal: Principal, *, conflict_id, resolution,
                           outcome: ResolutionOutcome = "keep_existing") -> dict:
    if outcome not in ("keep_existing", "accept_new"):
        raise ValueError("outcome must be keep_existing or accept_new")
    if not isinstance(resolution, str) or not resolution.strip():
        raise ValueError("resolution note is required")
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                cid = as_uuid(conflict_id)
            except ValueError:
                raise LookupError("conflict not found in this project")
            c = await repo.get_conflict(conn, cid)
            if c is None or c["project_id"] != principal.project_id:
                raise LookupError("conflict not found in this project")
            rows, existing_id, subject_id = await _lock_resolution_decisions(conn, principal, c, outcome)
            # Every resolver locks scopes/decisions before conflicts, so retiring
            # a decision can also close its other conflicts without a lock cycle.
            c = await repo.get_conflict(conn, cid, for_update=True)
            if c["status"] != "open":
                raise ValueError("conflict is already resolved")
            kept, retired = await _apply_outcome(conn, principal, rows, existing_id, subject_id, outcome)
            await repo.resolve_conflict(conn, cid, resolution, principal.person_id)
            await repo.acknowledge_conflict_alerts(conn, principal.project_id, cid)
            if retired is not None:
                await repo.acknowledge_retired_decision_alerts(conn, principal.project_id, retired["id"])
                obsolete = await repo.dismiss_obsolete_conflicts(
                    conn, principal.project_id, retired["id"], principal.person_id,
                    f"Decision retired by conflict resolution {cid}")
                for obsolete_id in obsolete:
                    await repo.acknowledge_conflict_alerts(conn, principal.project_id, obsolete_id)
                    await append_event(
                        conn, principal.project_id,
                        actor=f"person:{principal.person_id}/session:{principal.session_id}",
                        action="conflict.dismissed",
                        payload={"conflict_id": str(obsolete_id), "resolved_by_conflict_id": str(cid),
                                 "retired_decision_id": str(retired["id"])})
                participant = await repo.get_participant(
                    conn, principal.project_id, principal.person_id, principal.session_id)
                change = dict(kept)
                change["scope_tags"] = sorted(set(kept["scope_tags"]) | set(retired["scope_tags"]))
                await propagation.propagate_decision(
                    conn, principal.project_id, change,
                    participant["id"] if participant else None, retired["id"],
                    notify_people=[kept["owner_person_id"], retired["owner_person_id"]])
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="conflict.resolved",
                               payload={"conflict_id": str(cid), "resolution": resolution,
                                        "outcome": outcome, "kept_decision_id": str(kept["id"]),
                                        "retired_decision_id": str(retired["id"]) if retired else None})
            box = await build_inbox(conn, principal)
    return {"resolved": True, "outcome": outcome, "kept_decision_id": str(kept["id"]),
            "retired_decision_id": str(retired["id"]) if retired else None, "inbox": box}
