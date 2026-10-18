from keel import repo
from keel.server import _resolve_principal, token_hash


async def _seed(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", token_hash("legacy-tok"))
    return pid, person


async def test_legacy_person_token_resolves_full_scope(conn, db_pool):
    pid, person = await _seed(conn)
    p = await _resolve_principal("legacy-tok", "s1")
    assert p.person_id == person and p.project_id == pid and p.scope == "full"


async def test_agent_token_resolves_with_scope(conn, db_pool):
    pid, person = await _seed(conn)
    await repo.insert_token(conn, project_id=pid, person_id=person,
                            token_hash=token_hash("agent-tok"), kind="agent",
                            label="laptop", scope="read_only")
    p = await _resolve_principal("agent-tok", "s2")
    assert p.person_id == person and p.scope == "read_only"


async def test_revoked_token_is_rejected(conn, db_pool):
    pid, person = await _seed(conn)
    row = await repo.insert_token(conn, project_id=pid, person_id=person,
                                  token_hash=token_hash("rev-tok"), kind="agent")
    assert await repo.revoke_token(conn, row["id"], person) is True
    assert await _resolve_principal("rev-tok", "s3") is None
