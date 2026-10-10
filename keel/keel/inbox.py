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
