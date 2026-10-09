import pytest
from keel import repo
from keel.principal import Principal
from keel.tools.check_intent import check_intent
from keel.tools.record_decision import record_decision
from tests.fakes import ScriptedJudge
import keel.tools.check_intent as ci


async def _ctx(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "v", "h")
    await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    return pid, person


async def test_warns_without_persisting(conn, db_pool, monkeypatch):
    monkeypatch.setattr(ci, "get_judge", lambda settings=None: ScriptedJudge())
    pid, person = await _ctx(conn)
    await record_decision(db_pool, Principal(pid, person, "s1"),
                          statement="orders API uses cursor-based pagination",
                          rationale="scales", scope_tags=["api:orders"])
    out = await check_intent(db_pool, Principal(pid, person, "s1"),
                             planned_action="switch orders to offset pagination",
                             scope_tags=["api:orders"])
    assert len(out["conflicts"]) == 1 and out["conflicts"][0]["relation"] == "contradicts"
    assert "coverage" in out and out["inbox"] == {"alerts": [], "handoffs": [], "new_lessons": []}
    assert await conn.fetchval("SELECT count(*) FROM conflict WHERE project_id=$1", pid) == 0
    assert await conn.fetchval("SELECT count(*) FROM decision WHERE project_id=$1", pid) == 1


async def test_empty_scope_raises(conn, db_pool):
    pid, person = await _ctx(conn)
    with pytest.raises(ValueError):
        await check_intent(db_pool, Principal(pid, person, "s1"), planned_action="x",
                           scope_tags=["  "])


async def test_disabled_by_default(conn, db_pool):
    pid, person = await _ctx(conn)
    await record_decision(db_pool, Principal(pid, person, "s1"),
                          statement="orders API uses cursor pagination", rationale="r",
                          scope_tags=["api:orders"])
    out = await check_intent(db_pool, Principal(pid, person, "s1"),
                             planned_action="offset pagination", scope_tags=["api:orders"])
    assert out["coverage"] == "disabled" and out["conflicts"] == []
