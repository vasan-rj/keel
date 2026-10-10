import pytest
from keel import repo
from keel.principal import Principal
from keel.tools.resolve_conflict import resolve_conflict


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
