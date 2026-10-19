import httpx
from keel.server import app


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_healthz_ok_without_auth(db_pool):
    async with _client() as c:
        r = await c.get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"
