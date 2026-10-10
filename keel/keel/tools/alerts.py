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
