import httpx
from keel import repo
from keel.server import app, token_hash


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_list_and_revoke_token(conn, db_pool):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "v", token_hash("owner"))
    agent = await repo.insert_token(conn, project_id=pid, person_id=person,
                                    token_hash=token_hash("agent-1"), kind="agent",
                                    label="laptop", scope="full")
    h = {"Authorization": "Bearer owner"}
    async with _client() as c:
        lst = await c.get("/api/tokens", headers=h)
        assert lst.status_code == 200
        toks = lst.json()["tokens"]
        assert str(agent["id"]) in [t["id"] for t in toks] and "token_hash" not in toks[0]
        rv = await c.post(f"/api/tokens/{agent['id']}/revoke", headers=h)
        assert rv.status_code == 200 and rv.json()["revoked"] is True
    # revoked agent token no longer authenticates
    async with _client() as c:
        r = await c.get("/api/tokens", headers={"Authorization": "Bearer agent-1"})
    assert r.status_code == 401
