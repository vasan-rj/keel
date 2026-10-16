import pytest
import asyncio
import json
from keel import repo
from keel.principal import Principal
from keel.tools.resolve_conflict import resolve_conflict
from keel.tools.get_context import get_context
from keel.events import validate_chain


async def _setup(conn):
    pid = await repo.upsert_project(conn, "demo")
    owner = await repo.upsert_person(conn, pid, "owner", "h1")
    owner_part = await repo.upsert_participant(conn, pid, owner, "cc", "deep", "s1", [])
    other = await repo.upsert_person(conn, pid, "other", "h2")
    await repo.upsert_participant(conn, pid, other, "cc", "deep", "s2", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=owner,
                                   source_participant_id=owner_part)
    c = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                   subject_type="decision", subject_ref=str(d["id"]),
                                   relation="contradicts", severity="high", explanation="e")
    return pid, owner, other, c


async def test_owner_resolves(conn, db_pool):
    pid, owner, other, c = await _setup(conn)
    out = await resolve_conflict(db_pool, Principal(pid, owner, "s1"),
                                 conflict_id=str(c["id"]), resolution="keep")
    assert out["resolved"] is True
    got = await repo.get_conflict(conn, c["id"])
    assert got["status"] == "resolved" and got["resolution"] == "keep" and got["resolved_by"] == owner


async def test_non_owner_cannot_resolve(conn, db_pool):
    pid, owner, other, c = await _setup(conn)
    with pytest.raises(PermissionError):
        await resolve_conflict(db_pool, Principal(pid, other, "s2"),
                               conflict_id=str(c["id"]), resolution="keep")
    assert (await repo.get_conflict(conn, c["id"]))["status"] == "open"


async def test_missing_conflict_errors(conn, db_pool):
    pid, owner, other, c = await _setup(conn)
    import uuid
    with pytest.raises(LookupError):
        await resolve_conflict(db_pool, Principal(pid, owner, "s1"),
                               conflict_id=str(uuid.uuid4()), resolution="keep")


async def test_malformed_conflict_id_errors_cleanly(conn, db_pool):
    pid, owner, other, c = await _setup(conn)
    with pytest.raises(LookupError):  # not an asyncpg DataError
        await resolve_conflict(db_pool, Principal(pid, owner, "s1"),
                               conflict_id="not-a-uuid", resolution="keep")


async def _pair(conn):
    pid, owner, other, conflict = await _setup(conn)
    part = await repo.get_participant(conn, pid, other, "s2")
    new = await repo.insert_decision(
        conn, project_id=pid, statement="offset", rationale="simpler",
        scope_tags=["api:orders"], owner_person_id=other,
        source_participant_id=part["id"])
    await conn.execute("UPDATE conflict SET subject_ref=$2 WHERE id=$1",
                       conflict["id"], str(new["id"]))
    return pid, owner, other, conflict, new


@pytest.mark.parametrize("outcome", ["keep_existing", "accept_new"])
async def test_resolution_changes_effective_context_and_notifies_dependents(conn, db_pool, outcome):
    pid, owner, other, conflict, new = await _pair(conn)
    existing_id = conflict["decision_a_id"]
    observer = await repo.upsert_participant(conn, pid, other, "cc", "deep", "observer", [])
    await repo.insert_dependency(conn, existing_id, observer)
    await repo.insert_dependency(conn, new["id"], observer)
    out = await resolve_conflict(
        db_pool, Principal(pid, owner, "s1"), conflict_id=str(conflict["id"]),
        resolution="agreed by the team", outcome=outcome)
    kept, retired = ((existing_id, new["id"]) if outcome == "keep_existing"
                     else (new["id"], existing_id))
    context = await get_context(db_pool, Principal(pid, other, "s2"), scope_tags=["api:orders"])
    assert [d["id"] for d in context["decisions"]] == [str(kept)]
    assert (await repo.get_decision(conn, retired))["status"] == (
        "rejected" if outcome == "keep_existing" else "superseded")
    if outcome == "accept_new":
        assert (await repo.get_decision(conn, kept))["supersedes_id"] == existing_id
    assert out["kept_decision_id"] == str(kept)
    alerts = await repo.pending_alerts_for_participant(conn, observer)
    assert any(a["kind"] == "change" and a["ref_id"] == kept for a in alerts)
    event = await conn.fetchval("SELECT payload_json FROM event WHERE action='conflict.resolved'")
    assert json.loads(event)["outcome"] == outcome
    assert await validate_chain(conn, pid)


async def test_legacy_resolution_defaults_to_keep_existing(conn, db_pool):
    pid, owner, other, conflict, new = await _pair(conn)
    await resolve_conflict(db_pool, Principal(pid, owner, "s1"),
                           conflict_id=str(conflict["id"]), resolution="keep")
    assert (await repo.get_decision(conn, new["id"]))["status"] == "rejected"


@pytest.mark.parametrize("outcome", ["typo", "accept_new"])
async def test_invalid_resolution_rolls_back(conn, db_pool, outcome):
    pid, owner, other, conflict = await _setup(conn)
    if outcome == "accept_new":
        await conn.execute("UPDATE conflict SET subject_type='planned_action', subject_ref='planned' WHERE id=$1",
                           conflict["id"])
    with pytest.raises(ValueError):
        await resolve_conflict(db_pool, Principal(pid, owner, "s1"),
                               conflict_id=str(conflict["id"]), resolution="note", outcome=outcome)
    assert (await repo.get_conflict(conn, conflict["id"]))["status"] == "open"
    assert await conn.fetchval("SELECT count(*) FROM event") == 0


async def test_cross_project_subject_cannot_be_retired(conn, db_pool):
    pid, owner, other, conflict, new = await _pair(conn)
    foreign_pid = await repo.upsert_project(conn, "foreign")
    await conn.execute("UPDATE decision SET project_id=$2 WHERE id=$1", new["id"], foreign_pid)
    with pytest.raises(ValueError, match="project"):
        await resolve_conflict(db_pool, Principal(pid, owner, "s1"),
                               conflict_id=str(conflict["id"]), resolution="keep")
    assert (await repo.get_decision(conn, new["id"]))["status"] == "active"
    assert (await repo.get_conflict(conn, conflict["id"]))["status"] == "open"


async def test_concurrent_resolutions_have_one_winner(conn, db_pool):
    pid, owner, other, conflict, new = await _pair(conn)
    async def resolve(outcome):
        return await resolve_conflict(
            db_pool, Principal(pid, owner, "s1"), conflict_id=str(conflict["id"]),
            resolution="team choice", outcome=outcome)
    results = await asyncio.gather(resolve("keep_existing"), resolve("accept_new"),
                                   return_exceptions=True)
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, ValueError) for r in results) == 1
    assert len(await repo.active_decisions(conn, pid, None)) == 1
    assert await conn.fetchval("SELECT count(*) FROM event WHERE action='conflict.resolved'") == 1
