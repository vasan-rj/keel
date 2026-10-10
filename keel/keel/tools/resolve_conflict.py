from keel import repo
from keel.ids import as_uuid
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal


async def resolve_conflict(pool, principal: Principal, *, conflict_id, resolution) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                cid = as_uuid(conflict_id)
            except ValueError:
                raise LookupError("conflict not found in this project")
            c = await repo.get_conflict(conn, cid)
            if c is None or c["project_id"] != principal.project_id:
                raise LookupError("conflict not found in this project")
            cand = await repo.get_decision(conn, c["decision_a_id"])
            if cand is None or cand["owner_person_id"] != principal.person_id:
                raise PermissionError("only the decision owner may resolve this conflict")
            await repo.resolve_conflict(conn, cid, resolution, principal.person_id)
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="conflict.resolved",
                               payload={"conflict_id": str(conflict_id), "resolution": resolution})
            box = await build_inbox(conn, principal)
    return {"resolved": True, "inbox": box}
