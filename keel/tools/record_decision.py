import logging
from keel import repo
from keel import propagation
from keel.scope import lock_scope_tags, reconcile
from keel.events import append_event
from keel.inbox import build_inbox
from keel.conflict import check_on_insert
from keel.llm.embeddings import get_embedder
from keel.principal import Principal
from keel.authz import require_write

log = logging.getLogger("keel.tools")


async def record_decision(pool, principal: Principal, *, statement, rationale,
                          scope_tags, supersedes=None) -> dict:
    require_write(principal)
    """Record a decision (kind='decision'). Thin wrapper over the shared core."""
    return await _record(pool, principal, statement=statement, rationale=rationale,
                         scope_tags=scope_tags, kind="decision", supersedes=supersedes)


async def _record(pool, principal: Principal, *, statement, rationale, scope_tags,
                  kind="decision", supersedes=None, expires_at=None) -> dict:
    """Shared record path for decisions and lessons (same conflict pipeline,
    propagation, and event chain). `kind` is 'decision' or 'lesson'; `expires_at`
    sets a lesson's expiry."""
    try:
        embedding = await get_embedder().embed(f"{statement}\n{rationale}")
        embed_degraded = False
    except Exception as exc:
        log.warning("embedding failed; recording %s without embedding: %s", kind, exc)
        embedding = None
        embed_degraded = True
    async with pool.acquire() as conn:
        async with conn.transaction():
            participant = await repo.get_participant(
                conn, principal.project_id, principal.person_id, principal.session_id
            )
            if participant is None:
                raise LookupError("session not registered; call register_session first")

            tags = await reconcile(conn, principal.project_id, scope_tags)  # raises ValueError if empty

            # serialize per scope tag (sorted order avoids deadlock)
            await lock_scope_tags(conn, principal.project_id, tags)

            supersedes_id = None
            if supersedes:
                target = await repo.get_decision(conn, supersedes)
                if target is None or target["project_id"] != principal.project_id:
                    raise ValueError("supersedes target not found in this project")
                supersedes_id = target["id"]

            row = await repo.insert_decision(
                conn, project_id=principal.project_id, statement=statement,
                rationale=rationale, scope_tags=tags, owner_person_id=principal.person_id,
                source_participant_id=participant["id"], supersedes_id=supersedes_id,
                status="active", embedding=embedding, kind=kind, expires_at=expires_at,
            )
            if supersedes_id:
                await repo.mark_superseded(conn, supersedes_id)

            try:
                # savepoint: a Postgres error during detection rolls back only
                # detection, leaving the outer txn (the decision write) healthy.
                async with conn.transaction():
                    result = await check_on_insert(conn, principal.project_id, row)
            except Exception as exc:
                log.warning("conflict detection failed; degrading: %s", exc)
                result = {"conflicts": [], "degraded": True, "coverage": "degraded"}

            await propagation.propagate_decision(
                conn, principal.project_id, row, participant["id"], supersedes_id)
            await propagation.propagate_conflicts(
                conn, principal.project_id, result["conflicts"], participant["id"])

            await append_event(
                conn, principal.project_id,
                actor=f"person:{principal.person_id}/session:{principal.session_id}",
                action=f"{kind}.recorded",
                payload={"decision_id": str(row["id"]), "kind": kind, "scope_tags": tags,
                         "supersedes": str(supersedes_id) if supersedes_id else None},
            )
            box = await build_inbox(conn, principal)

    degraded = result["degraded"] or embed_degraded
    coverage = "degraded" if embed_degraded else result["coverage"]
    return {"decision_id": str(row["id"]), "kind": kind, "status": row["status"],
            "scope_tags": tags, "conflicts": result["conflicts"], "degraded": degraded,
            "coverage": coverage,
            "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
            "inbox": box}
