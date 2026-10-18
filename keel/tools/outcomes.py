from keel import repo
from keel.ids import as_uuid
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal
from keel.authz import require_write

_RESULTS = {"held", "reversed", "caused_rework"}
_VERDICTS = {"useful", "noise"}


async def _require_participant(conn, principal):
    part = await repo.get_participant(conn, principal.project_id, principal.person_id,
                                      principal.session_id)
    if part is None:
        raise LookupError("session not registered; call register_session first")
    return part


async def record_outcome(pool, principal: Principal, *, decision_id, result,
                         evidence_ref=None) -> dict:
    require_write(principal)
    if result not in _RESULTS:
        raise ValueError(f"result must be one of {sorted(_RESULTS)}")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_participant(conn, principal)
            try:
                did = as_uuid(decision_id)
            except ValueError:
                raise LookupError("decision not found in this project")
            d = await repo.get_decision(conn, did)
            if d is None or d["project_id"] != principal.project_id:
                raise ValueError("decision not found in this project")
            o = await repo.insert_outcome(conn, decision_id=did, result=result,
                                          evidence_ref=evidence_ref, source="manual",
                                          confirmed_by=principal.person_id)
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="outcome.recorded",
                               payload={"decision_id": str(did), "result": result})
            box = await build_inbox(conn, principal)
    return {"outcome_id": str(o["id"]), "inbox": box}


async def rate_alert(pool, principal: Principal, *, alert_id, verdict, note=None) -> dict:
    require_write(principal)
    if verdict not in _VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(_VERDICTS)}")
    async with pool.acquire() as conn:
        async with conn.transaction():
            part = await _require_participant(conn, principal)
            try:
                aid = as_uuid(alert_id)
            except ValueError:
                raise LookupError("alert not found")
            a = await repo.get_alert(conn, aid)
            if a is None or a["project_id"] != principal.project_id:
                raise LookupError("alert not found in this project")
            if a["target_participant_id"] != part["id"]:
                raise PermissionError("you can only rate alerts addressed to you")
            fb = await repo.insert_alert_feedback(conn, alert_id=aid, verdict=verdict, note=note)
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="alert.rated",
                               payload={"alert_id": str(aid), "verdict": verdict})
            box = await build_inbox(conn, principal)
    return {"feedback_id": str(fb["id"]), "inbox": box}
