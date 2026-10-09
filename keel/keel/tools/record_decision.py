import hashlib
import logging
from keel import repo
from keel.scope import reconcile
from keel.events import append_event
from keel.inbox import build_inbox
from keel.conflict import check_on_insert
from keel.llm.embeddings import get_embedder
from keel.principal import Principal

log = logging.getLogger("keel.tools")


def _scope_lock_key(project_id, tag: str) -> int:
    material = f"scope:{project_id}:{tag}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big", signed=True)


async def record_decision(pool, principal: Principal, *, statement, rationale,
                          scope_tags, supersedes=None) -> dict:
    try:
        embedding = await get_embedder().embed(f"{statement}\n{rationale}")
        embed_degraded = False
    except Exception as exc:
        log.warning("embedding failed; recording decision without embedding: %s", exc)
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
            for tag in sorted(tags):
                await conn.execute("SELECT pg_advisory_xact_lock($1)",
                                   _scope_lock_key(principal.project_id, tag))

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
                status="active", embedding=embedding,
            )
            if supersedes_id:
                await repo.mark_superseded(conn, supersedes_id)

            try:
                result = await check_on_insert(conn, principal.project_id, row)
            except Exception as exc:
                log.warning("conflict detection failed; degrading: %s", exc)
                result = {"conflicts": [], "degraded": True, "coverage": "degraded"}

            await append_event(
                conn, principal.project_id,
                actor=f"person:{principal.person_id}/session:{principal.session_id}",
                action="decision.recorded",
                payload={"decision_id": str(row["id"]), "scope_tags": tags,
                         "supersedes": str(supersedes_id) if supersedes_id else None},
            )
            box = await build_inbox(conn, principal)

    degraded = result["degraded"] or embed_degraded
    coverage = "degraded" if embed_degraded else result["coverage"]
    return {"decision_id": str(row["id"]), "status": row["status"],
            "scope_tags": tags, "conflicts": result["conflicts"], "degraded": degraded,
            "coverage": coverage, "inbox": box}
