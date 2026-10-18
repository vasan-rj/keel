import pytest
from keel import repo
from keel.authz import require_write
from keel.principal import Principal
from keel.server import token_hash
from keel.tools.record_decision import record_decision


def test_require_write_blocks_read_only():
    with pytest.raises(PermissionError):
        require_write(Principal(project_id="p", person_id="u", scope="read_only"))


def test_require_write_allows_full():
    assert require_write(Principal(project_id="p", person_id="u", scope="full")) is None


async def test_record_decision_refused_for_read_only(conn, db_pool):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "v", token_hash("t"))
    pr = Principal(project_id=pid, person_id=person, session_id="s1", scope="read_only")
    with pytest.raises(PermissionError):
        await record_decision(db_pool, pr, statement="x", rationale="y",
                              scope_tags=["api:orders"])
