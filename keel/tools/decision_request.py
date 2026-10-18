from keel import repo
from keel.scope import normalize_tags
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal
from keel.authz import require_write


async def request_decision(pool, principal: Principal, *, question, owner_person,
                           options=None, scope_tags=None) -> dict:
    require_write(principal)
    if not question or not question.strip():
        raise ValueError("question is required")
    tags = normalize_tags(scope_tags) if scope_tags else []
    async with pool.acquire() as conn:
        async with conn.transaction():
            part = await repo.get_participant(conn, principal.project_id,
                                              principal.person_id, principal.session_id)
            if part is None:
                raise LookupError("session not registered; call register_session first")
            owner = await repo.get_person_by_name(conn, principal.project_id, owner_person)
            if owner is None:
                raise LookupError("owner not found in this project")
            r = await repo.insert_decision_request(
                conn, project_id=principal.project_id, requester_participant_id=part["id"],
                owner_person_id=owner["id"], question=question, options=options or [],
                scope_tags=tags)
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="decision.requested",
                               payload={"request_id": str(r["id"]),
                                        "owner_person_id": str(owner["id"])})
            box = await build_inbox(conn, principal)
    return {"request_id": str(r["id"]), "status": "open", "inbox": box}
