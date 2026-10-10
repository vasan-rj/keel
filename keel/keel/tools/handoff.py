from datetime import datetime, timedelta, timezone
from keel import repo
from keel.ids import as_uuid
from keel.scope import normalize_tags
from keel.events import append_event
from keel.inbox import build_inbox
from keel.principal import Principal

_DEFAULT_CLAIM_TTL_S = 3600


async def _require_participant(conn, principal):
    part = await repo.get_participant(conn, principal.project_id, principal.person_id,
                                      principal.session_id)
    if part is None:
        raise LookupError("session not registered; call register_session first")
    return part


def _actor(principal) -> str:
    return f"person:{principal.person_id}/session:{principal.session_id}"


async def create_handoff(pool, principal: Principal, *, to_person, scope_tags,
                         note=None, to_session=None) -> dict:
    tags = normalize_tags(scope_tags)  # raises ValueError if empty
    async with pool.acquire() as conn:
        async with conn.transaction():
            sender = await _require_participant(conn, principal)
            recipient = await repo.get_person_by_name(conn, principal.project_id, to_person)
            if recipient is None:
                raise LookupError("recipient not found in this project")
            to_part_id = None
            if to_session:
                rp = await repo.get_participant(conn, principal.project_id,
                                                recipient["id"], to_session)
                to_part_id = rp["id"] if rp else None
            decisions = await repo.active_decisions(conn, principal.project_id, tags)
            conflicts = await repo.open_conflicts_in_scope(conn, principal.project_id, tags)
            decision_ids = [d["id"] for d in decisions]
            conflict_ids = [c["id"] for c in conflicts]
            h = await repo.insert_handoff(
                conn, project_id=principal.project_id, from_participant_id=sender["id"],
                to_person_id=recipient["id"], to_participant_id=to_part_id,
                scope_tags=tags, decision_ids=decision_ids, conflict_ids=conflict_ids, note=note)
            await append_event(conn, principal.project_id, actor=_actor(principal),
                               action="handoff.created",
                               payload={"handoff_id": str(h["id"]),
                                        "to_person_id": str(recipient["id"]),
                                        "scope_tags": tags,
                                        "decisions": len(decision_ids),
                                        "conflicts": len(conflict_ids)})
            box = await build_inbox(conn, principal)
    return {"handoff_id": str(h["id"]), "status": "pending", "scope_tags": tags,
            "decision_ids": [str(i) for i in decision_ids],
            "conflict_ids": [str(i) for i in conflict_ids], "inbox": box}


async def _load_for_recipient(conn, principal, handoff_id):
    try:
        hid = as_uuid(handoff_id)
    except ValueError:
        raise LookupError("handoff not found in this project")
    h = await repo.get_handoff(conn, hid)
    if h is None or h["project_id"] != principal.project_id:
        raise LookupError("handoff not found in this project")
    if h["to_person_id"] != principal.person_id:
        raise PermissionError("only the handoff recipient may act on it")
    if h["status"] != "pending":
        raise ValueError(f"handoff is not pending (status={h['status']})")
    return hid, h


async def accept_handoff(pool, principal: Principal, *, handoff_id) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            receiver = await _require_participant(conn, principal)
            hid, h = await _load_for_recipient(conn, principal, handoff_id)
            tags = list(h["scope_tags"])
            expires = datetime.now(timezone.utc) + timedelta(seconds=_DEFAULT_CLAIM_TTL_S)
            await repo.insert_claim(conn, principal.project_id, receiver["id"], tags, expires)
            # don't release when the sender session is also the receiver — that would
            # delete the claim just inserted (degenerate same-session self-handoff).
            if h["from_participant_id"] != receiver["id"]:
                await repo.release_claims(conn, h["from_participant_id"], tags)
            deps = 0
            for did in h["decision_ids"]:
                if await repo.get_decision(conn, did) is not None:
                    await repo.insert_dependency(conn, did, receiver["id"])
                    deps += 1
            await repo.set_handoff_status(conn, hid, "accepted",
                                          accepted_at=datetime.now(timezone.utc),
                                          to_participant_id=receiver["id"])
            await append_event(conn, principal.project_id, actor=_actor(principal),
                               action="handoff.accepted",
                               payload={"handoff_id": str(hid), "scope_tags": tags,
                                        "dependencies": deps})
            box = await build_inbox(conn, principal)
    return {"handoff_id": str(hid), "status": "accepted", "claimed_scope_tags": tags,
            "dependencies": deps, "inbox": box}


async def decline_handoff(pool, principal: Principal, *, handoff_id) -> dict:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _require_participant(conn, principal)
            hid, h = await _load_for_recipient(conn, principal, handoff_id)
            await repo.set_handoff_status(conn, hid, "declined")
            await append_event(conn, principal.project_id, actor=_actor(principal),
                               action="handoff.declined", payload={"handoff_id": str(hid)})
            box = await build_inbox(conn, principal)
    return {"handoff_id": str(hid), "status": "declined", "inbox": box}
