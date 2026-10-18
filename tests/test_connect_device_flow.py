import httpx
from datetime import datetime, timedelta, timezone
from keel import repo
from keel.server import app, token_hash


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_device_start_returns_codes(db_pool):
    async with _client() as c:
        r = await c.post("/connect/device", json={"harness": "claude-code", "label": "laptop"})
    assert r.status_code == 200
    body = r.json()
    assert body["user_code"] and body["device_code"] and body["interval"] >= 1


async def test_poll_pending_then_expired(db_pool):
    async with _client() as c:
        start = (await c.post("/connect/device", json={"harness": "x"})).json()
        r = await c.post("/connect/token", json={"device_code": start["device_code"]})
        assert r.status_code == 428 and r.json()["error"] == "authorization_pending"
    # force-expire and re-poll
    async with db_pool.acquire() as conn:
        g = await repo.get_device_grant_by_code_hash(conn, token_hash(start["device_code"]))
        await conn.execute("UPDATE device_grant SET expires_at=now() - interval '1 min' WHERE id=$1",
                           g["id"])
    async with _client() as c:
        r = await c.post("/connect/token", json={"device_code": start["device_code"]})
    assert r.status_code == 410 and r.json()["error"] == "expired_token"


async def test_claim_is_one_shot(conn, db_pool):
    # pre-approve a grant by hand (approve endpoint covered in Task 7) and seed the
    # process-local one-shot store the way /connect/approve will.
    from keel.connect.tokenstore import ONE_SHOT
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "v", token_hash("owner"))
    tok = await repo.insert_token(conn, project_id=pid, person_id=person,
                                  token_hash=token_hash("agent-xyz"), kind="agent", scope="full")
    exp = datetime.now(timezone.utc) + timedelta(minutes=10)
    g = await repo.insert_device_grant(conn, device_code_hash=token_hash("dc1"),
                                       user_code="AAAA-2345", harness="x", label=None, expires_at=exp)
    await repo.update_device_grant(conn, g["id"], status="approved", scope="full",
                                   person_id=person, token_id=tok["id"],
                                   approved_at=datetime.now(timezone.utc))
    ONE_SHOT.put(str(g["id"]), "agent-xyz")
    async with _client() as c:
        r1 = await c.post("/connect/token", json={"device_code": "dc1"})
        r2 = await c.post("/connect/token", json={"device_code": "dc1"})
    assert r1.status_code == 200
    body = r1.json()
    assert body["project"] == str(pid) and body["person"] == str(person) and body["scope"] == "full"
    assert r2.status_code == 410  # claimed, never returns the token twice
