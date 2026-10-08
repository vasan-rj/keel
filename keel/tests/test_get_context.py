from keel import repo
from keel.principal import Principal
from keel.tools.get_context import get_context


async def _seed(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "claude-code", "deep", "s1", [])
    await repo.insert_decision(conn, project_id=pid, statement="cursor pagination",
                               rationale="r", scope_tags=["api:orders"],
                               owner_person_id=person, source_participant_id=part)
    return pid, person


async def test_get_context_filters_by_scope(conn, db_pool):
    pid, person = await _seed(conn)
    out = await get_context(db_pool, Principal(pid, person, "s1"), scope_tags=["api:orders"])
    assert len(out["decisions"]) == 1
    assert out["decisions"][0]["statement"] == "cursor pagination"
    assert out["inbox"] == {"alerts": [], "handoffs": [], "new_lessons": []}
    assert out["lessons"] == []


async def test_get_context_normalizes_tag_variant(conn, db_pool):
    pid, person = await _seed(conn)
    out = await get_context(db_pool, Principal(pid, person, "s1"), scope_tags=["API: Orders"])
    assert len(out["decisions"]) == 1  # variant must resolve to api:orders


async def test_get_context_no_scope_returns_all_active(conn, db_pool):
    pid, person = await _seed(conn)
    out = await get_context(db_pool, Principal(pid, person, "s1"), scope_tags=None)
    assert len(out["decisions"]) == 1
