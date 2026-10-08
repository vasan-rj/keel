import uuid
from datetime import datetime, timezone
from keel.events import event_hash, append_event, validate_chain


async def _project(conn):
    return await conn.fetchval("INSERT INTO project (name) VALUES ('p') RETURNING id")


def test_event_hash_is_deterministic():
    pid = uuid.UUID("00000000-0000-0000-0000-000000000001")
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    h1 = event_hash(None, pid, "actor", "act", {"b": 1, "a": 2}, ts)
    h2 = event_hash(None, pid, "actor", "act", {"a": 2, "b": 1}, ts)
    assert h1 == h2  # key order must not matter
    h3 = event_hash(None, pid, "actor", "act", {"a": 2, "b": 3}, ts)
    assert h1 != h3


async def test_append_links_prev_hash(conn):
    pid = await _project(conn)
    async with conn.transaction():
        e1 = await append_event(conn, pid, "a", "x", {"n": 1})
        e2 = await append_event(conn, pid, "a", "y", {"n": 2})
    assert e1["prev_hash"] is None
    assert e2["prev_hash"] == e1["hash"]
    assert await validate_chain(conn, pid) is True


async def test_validate_chain_detects_tamper(conn):
    pid = await _project(conn)
    async with conn.transaction():
        await append_event(conn, pid, "a", "x", {"n": 1})
    await conn.execute("UPDATE event SET payload_json = '{\"n\": 999}' WHERE project_id = $1", pid)
    assert await validate_chain(conn, pid) is False
