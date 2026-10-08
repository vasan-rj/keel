from keel import repo
from keel.principal import Principal
from keel.events import validate_chain
from keel.tools.register_session import register_session


async def _principal(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    return pid, person


async def test_register_creates_participant_and_event(conn, db_pool):
    pid, person = await _principal(conn)
    principal = Principal(project_id=pid, person_id=person, session_id=None)
    out = await register_session(db_pool, principal, harness="claude-code",
                                 tier="deep", session_id="s1", allowed_scopes=["api:orders"])
    assert out["project_id"] == str(pid)
    assert out["session_id"] == "s1"
    assert out["inbox"] == {"alerts": [], "handoffs": [], "new_lessons": []}
    part = await repo.get_participant(conn, pid, person, "s1")
    assert part is not None and str(part["id"]) == out["participant_id"]
    assert await validate_chain(conn, pid) is True
