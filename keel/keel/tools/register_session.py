from keel import repo
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal


async def register_session(pool, principal: Principal, *, harness, tier,
                           session_id, allowed_scopes=None) -> dict:
    allowed_scopes = allowed_scopes or []
    async with pool.acquire() as conn:
        async with conn.transaction():
            part_id = await repo.upsert_participant(
                conn, principal.project_id, principal.person_id,
                harness, tier, session_id, allowed_scopes,
            )
            await append_event(
                conn, principal.project_id,
                actor=f"person:{principal.person_id}/session:{session_id}",
                action="participant.registered",
                payload={"participant_id": str(part_id), "harness": harness,
                         "tier": tier, "allowed_scopes": allowed_scopes},
            )
            box = await build_inbox(conn, Principal(principal.project_id, principal.person_id, session_id))
    return {"participant_id": str(part_id), "project_id": str(principal.project_id),
            "session_id": session_id, "inbox": box}
