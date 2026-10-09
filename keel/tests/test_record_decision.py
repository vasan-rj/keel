import asyncio
import pytest
from keel import repo
from keel.principal import Principal
from keel.events import validate_chain
from keel.tools.record_decision import record_decision
from keel.tools.get_context import get_context


async def _ctx(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    await repo.upsert_participant(conn, pid, person, "claude-code", "deep", "s1", [])
    return pid, person


async def test_record_creates_active_decision_and_event(conn, db_pool):
    pid, person = await _ctx(conn)
    out = await record_decision(db_pool, Principal(pid, person, "s1"),
                                statement="use cursor pagination", rationale="scales",
                                scope_tags=["API: Orders"])
    assert out["status"] == "active"
    assert out["scope_tags"] == ["api:orders"]
    assert out["conflicts"] == []
    ctx = await get_context(db_pool, Principal(pid, person, "s1"), scope_tags=["api:orders"])
    assert any(d["id"] == out["decision_id"] for d in ctx["decisions"])
    assert await validate_chain(conn, pid) is True


async def test_record_rejects_empty_scope(conn, db_pool):
    pid, person = await _ctx(conn)
    with pytest.raises(ValueError):
        await record_decision(db_pool, Principal(pid, person, "s1"),
                              statement="x", rationale="y", scope_tags=["  "])


async def test_record_requires_registered_session(conn, db_pool):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")  # no participant
    with pytest.raises(LookupError):
        await record_decision(db_pool, Principal(pid, person, "nope"),
                              statement="x", rationale="y", scope_tags=["api:orders"])


async def test_supersedes_flips_status(conn, db_pool):
    pid, person = await _ctx(conn)
    first = await record_decision(db_pool, Principal(pid, person, "s1"),
                                  statement="page size 20", rationale="r",
                                  scope_tags=["api:orders"])
    second = await record_decision(db_pool, Principal(pid, person, "s1"),
                                   statement="page size 50", rationale="r",
                                   scope_tags=["api:orders"], supersedes=first["decision_id"])
    assert (await repo.get_decision(conn, first["decision_id"]))["status"] == "superseded"
    assert second["status"] == "active"


async def test_supersedes_cross_project_errors_atomically(conn, db_pool):
    pid, person = await _ctx(conn)
    other = await repo.upsert_project(conn, "other")
    oper = await repo.upsert_person(conn, other, "x", "h2")
    opart = await repo.upsert_participant(conn, other, oper, "cc", "deep", "os", [])
    foreign = await repo.insert_decision(conn, project_id=other, statement="f", rationale="r",
                                         scope_tags=["api:orders"], owner_person_id=oper,
                                         source_participant_id=opart)
    with pytest.raises(ValueError):
        await record_decision(db_pool, Principal(pid, person, "s1"),
                              statement="x", rationale="y", scope_tags=["api:orders"],
                              supersedes=str(foreign["id"]))
    assert len(await repo.active_decisions(conn, pid, None)) == 0


async def test_concurrent_same_scope_serializes_chain_valid(conn, db_pool):
    pid, person = await _ctx(conn)
    p = Principal(pid, person, "s1")
    await asyncio.gather(
        record_decision(db_pool, p, statement="a", rationale="r", scope_tags=["api:orders"]),
        record_decision(db_pool, p, statement="b", rationale="r", scope_tags=["api:orders"]),
    )
    assert len(await repo.active_decisions(conn, pid, ["api:orders"])) == 2
    assert await validate_chain(conn, pid) is True


from tests.fakes import ScriptedJudge
import keel.conflict as conflict_pkg


async def test_record_flags_pagination_conflict(conn, db_pool, monkeypatch):
    monkeypatch.setattr(conflict_pkg, "get_judge", lambda settings=None: ScriptedJudge())
    pid, person = await _ctx(conn)
    first = await record_decision(db_pool, Principal(pid, person, "s1"),
                                  statement="orders API uses cursor-based pagination",
                                  rationale="scales", scope_tags=["api:orders"])
    assert first["conflicts"] == []
    second = await record_decision(db_pool, Principal(pid, person, "s1"),
                                   statement="orders API should use offset pagination",
                                   rationale="simpler", scope_tags=["api:orders"])
    assert len(second["conflicts"]) == 1 and second["conflicts"][0]["relation"] == "contradicts"
    assert second["coverage"] == "full" and second["degraded"] is False
    assert await conn.fetchval("SELECT count(*) FROM conflict WHERE project_id=$1", pid) == 1
    assert await conn.fetchval(
        "SELECT count(*) FROM decision WHERE project_id=$1 AND embedding IS NOT NULL", pid) == 2
    assert await validate_chain(conn, pid) is True


async def test_record_detection_disabled_by_default(conn, db_pool):
    # autouse fixture sets provider=none -> coverage disabled, no conflicts
    pid, person = await _ctx(conn)
    await record_decision(db_pool, Principal(pid, person, "s1"),
                          statement="orders API uses cursor pagination", rationale="r",
                          scope_tags=["api:orders"])
    out = await record_decision(db_pool, Principal(pid, person, "s1"),
                                statement="orders API uses offset pagination", rationale="r",
                                scope_tags=["api:orders"])
    assert out["conflicts"] == [] and out["coverage"] == "disabled"
