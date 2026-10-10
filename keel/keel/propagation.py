"""Propagation: turn a recorded decision / detected conflict into alerts.

All deterministic DB work, run inside record_decision's outer transaction
(durable with the decision). Never calls the LLM. The author's own session is
never alerted; their other sessions are reached only via their own claim or
dependency.
"""

from keel import repo
from keel.events import append_event


async def propagate_decision(conn, project_id, decision_row, author_participant_id,
                             superseded_id=None) -> list[str]:
    """`change` alerts: participants with an overlapping active claim, UNION those
    with a dependency on this decision or the one it supersedes. Author excluded."""
    scope_tags = list(decision_row["scope_tags"])
    targets = {}  # participant_id -> person_id
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
    """`conflict` alerts to the candidate decision owner's active sessions (author
    excluded). `conflicts` are the dicts from check_on_insert (carry candidate_id
    + conflict_id)."""
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
