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
                       "created_at": r["created_at"].isoformat() if r["created_at"] else None})
    handoffs = []
    for hr in await repo.pending_handoffs_for_person(conn, principal.project_id,
                                                     principal.person_id):
        # don't surface a handoff back to the session that created it (self-handoff)
        if hr["from_participant_id"] == part["id"]:
            continue
        handoffs.append({
            "id": str(hr["id"]),
            "from_participant_id": str(hr["from_participant_id"]) if hr["from_participant_id"] else None,
            "scope_tags": list(hr["scope_tags"]),
            "decision_ids": [str(i) for i in hr["decision_ids"]],
            "conflict_ids": [str(i) for i in hr["conflict_ids"]],
            "note": hr["note"],
            "created_at": hr["created_at"].isoformat() if hr["created_at"] else None,
        })
    new_lessons = []
    for lr in await repo.active_lessons(conn, principal.project_id, None):
        new_lessons.append({
            "id": str(lr["id"]), "statement": lr["statement"],
            "scope_tags": list(lr["scope_tags"]),
            "expires_at": lr["expires_at"].isoformat() if lr["expires_at"] else None,
        })
    return {"alerts": alerts, "handoffs": handoffs, "new_lessons": new_lessons}
