from datetime import datetime, timedelta, timezone
from keel import repo
from keel.ids import as_uuid
from keel.scope import normalize_tags
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal


async def _require_participant(conn, principal):
    part = await repo.get_participant(conn, principal.project_id, principal.person_id,
                                      principal.session_id)
    if part is None:
        raise LookupError("session not registered; call register_session first")
    return part


async def declare_dependency(pool, principal: Principal, *, decision_id) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            part = await _require_participant(conn, principal)
            try:
                did = as_uuid(decision_id)
            except ValueError:
                raise ValueError("decision not found in this project")
            d = await repo.get_decision(conn, did)
            if d is None or d["project_id"] != principal.project_id:
                raise ValueError("decision not found in this project")
            dep = await repo.insert_dependency(conn, did, part["id"])
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="dependency.declared",
                               payload={"decision_id": str(decision_id)})
            box = await build_inbox(conn, principal)
    return {"dependency_id": str(dep["id"]), "inbox": box}


async def claim_scope(pool, principal: Principal, *, scope_tags, ttl_seconds=3600) -> dict:
    tags = normalize_tags(scope_tags)
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    async with pool.acquire() as conn:
        async with conn.transaction():
            part = await _require_participant(conn, principal)
            claim = await repo.insert_claim(conn, principal.project_id, part["id"], tags, expires)
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="scope.claimed", payload={"scope_tags": tags})
            box = await build_inbox(conn, principal)
    return {"claim_id": str(claim["id"]), "scope_tags": tags, "inbox": box}


async def release_scope(pool, principal: Principal, *, scope_tags=None) -> dict:
    tags = normalize_tags(scope_tags) if scope_tags else None
    async with pool.acquire() as conn:
        async with conn.transaction():
            part = await _require_participant(conn, principal)
            n = await repo.release_claims(conn, part["id"], tags)
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="scope.released", payload={"scope_tags": tags, "count": n})
            box = await build_inbox(conn, principal)
    return {"released": n, "inbox": box}
