from keel import repo
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal


async def register_session(pool, principal: Principal, *, harness, tier,
                           session_id, allowed_scopes=None) -> dict:
    allowed_scopes = allowed_scopes or []
    # The session used for every later call comes from the X-Keel-Session header
    # (principal.session_id). Register under that so header-based lookups in
    # record_decision/get_context resolve this participant. If the client also
    # passed a session_id argument and the two disagree, fail loudly rather than
    # register one id and answer later calls under another (a silent divergence
    # that surfaces as a cryptic "session not registered").
    if principal.session_id is not None and principal.session_id != session_id:
        raise ValueError(
            f"session_id mismatch: X-Keel-Session header {principal.session_id!r} "
            f"!= tool argument {session_id!r}"
        )
    session_id = principal.session_id or session_id
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
