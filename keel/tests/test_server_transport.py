import hashlib
import pytest
import httpx
from keel import repo


async def _seed_token(pool):
    async with pool.acquire() as conn:
        pid = await repo.upsert_project(conn, "demo")
        await repo.upsert_person(conn, pid, "vasan",
                                 hashlib.sha256(b"dev-token").hexdigest())


async def test_unknown_token_is_401(db_pool):
    from keel.server import app
    await _seed_token(db_pool)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.post("/mcp", headers={"Authorization": "Bearer wrong",
                                          "X-Keel-Session": "s1"}, json={})
        assert r.status_code == 401


async def test_roundtrip_register_record_get(db_pool):
    """register_session -> record_decision -> get_context via the real auth path."""
    from keel.server import call_tool_for_test
    await _seed_token(db_pool)
    reg = await call_tool_for_test("dev-token", "s1", "register_session",
                                   {"harness": "claude-code", "tier": "deep", "session_id": "s1"})
    assert "participant_id" in reg and reg["inbox"]["alerts"] == []
    rec = await call_tool_for_test("dev-token", "s1", "record_decision",
                                   {"statement": "cursor pagination", "rationale": "scales",
                                    "scope_tags": ["api:orders"]})
    assert rec["status"] == "active"
    ctx = await call_tool_for_test("dev-token", "s1", "get_context",
                                   {"scope_tags": ["api:orders"]})
    assert any(d["id"] == rec["decision_id"] for d in ctx["decisions"])
    assert ctx["inbox"] == {"alerts": [], "handoffs": [], "new_lessons": []}
