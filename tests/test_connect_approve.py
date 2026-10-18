import httpx
from keel import repo
from keel.server import app, token_hash


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _start(c, harness="claude-code"):
    return (await c.post("/connect/device", json={"harness": harness})).json()


async def test_approve_then_claim_yields_working_token(conn, db_pool, monkeypatch):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "alice", token_hash("owner-tok"))
    await conn.execute("UPDATE person SET email=$2, firebase_uid=$3 WHERE id=$1",
                       person, "alice@x.com", "uid-alice")
    monkeypatch.setenv("KEEL_FIREBASE_VERIFIER", "fake")
    async with _client() as c:
        start = await _start(c)
        r = await c.post("/connect/approve",
                         headers={"Authorization": "Bearer fake:uid-alice:alice@x.com"},
                         json={"user_code": start["user_code"], "scope": "read_only"})
        assert r.status_code == 200 and r.json()["approved"] is True
        claim = await c.post("/connect/token", json={"device_code": start["device_code"]})
    assert claim.status_code == 200
    body = claim.json()
    assert body["scope"] == "read_only" and body["project"] == str(pid)
    async with db_pool.acquire() as c2:
        tok = await repo.get_token_by_hash(c2, token_hash(body["token"]))
    assert tok is not None and tok["kind"] == "agent"


async def test_approve_unknown_email_refused_without_default_project(db_pool, monkeypatch):
    monkeypatch.setenv("KEEL_FIREBASE_VERIFIER", "fake")
    monkeypatch.delenv("KEEL_DEFAULT_PROJECT_ID", raising=False)
    async with _client() as c:
        start = await _start(c)
        r = await c.post("/connect/approve",
                         headers={"Authorization": "Bearer fake:uid-new:new@x.com"},
                         json={"user_code": start["user_code"]})
    assert r.status_code == 403


async def test_approve_creates_person_with_default_project(conn, db_pool, monkeypatch):
    pid = await repo.upsert_project(conn, "demo")
    monkeypatch.setenv("KEEL_FIREBASE_VERIFIER", "fake")
    monkeypatch.setenv("KEEL_DEFAULT_PROJECT_ID", str(pid))
    async with _client() as c:
        start = await _start(c)
        r = await c.post("/connect/approve",
                         headers={"Authorization": "Bearer fake:uid-new:new@x.com"},
                         json={"user_code": start["user_code"]})
    assert r.status_code == 200
    async with db_pool.acquire() as c2:
        assert await repo.get_person_by_identity(c2, email="new@x.com") is not None


async def test_approve_rejects_bad_id_token(db_pool, monkeypatch):
    monkeypatch.setenv("KEEL_FIREBASE_VERIFIER", "fake")
    async with _client() as c:
        start = await _start(c)
        r = await c.post("/connect/approve",
                         headers={"Authorization": "Bearer garbage"},
                         json={"user_code": start["user_code"]})
    assert r.status_code == 401


async def test_approve_503_when_login_unconfigured(db_pool, monkeypatch):
    monkeypatch.delenv("KEEL_FIREBASE_VERIFIER", raising=False)
    monkeypatch.delenv("KEEL_FIREBASE_AUDIENCE", raising=False)
    monkeypatch.delenv("KEEL_FIREBASE_PROJECT_ID", raising=False)
    async with _client() as c:
        start = await _start(c)
        r = await c.post("/connect/approve",
                         headers={"Authorization": "Bearer fake:u:e@x.com"},
                         json={"user_code": start["user_code"]})
    assert r.status_code == 503
