import httpx
from keel.server import app


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_connect_page_served_without_auth(db_pool):
    async with _client() as c:
        r = await c.get("/connect")
    assert r.status_code == 200 and "user_code" in r.text.lower().replace("-", "_")
