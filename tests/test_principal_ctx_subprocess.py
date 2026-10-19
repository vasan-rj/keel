import os
import asyncio
import hashlib
import urllib.request

from tests.conftest_connect_server import connect_server  # noqa: F401
from keel.db import pool as db
from keel import repo


def _dsn():
    return os.environ.get("KEEL_TEST_DATABASE_URL",
                          "postgresql://keel:keel@localhost:5433/keel_test")


async def _seed_person_token(dsn):
    pool = await db.init_pool(dsn)
    async with pool.acquire() as c:
        pid = await repo.upsert_project(c, "connect-demo")
        await repo.upsert_person(c, pid, "ctxalice", hashlib.sha256(b"ctx-ptok").hexdigest())
    await db.close_pool()


def test_api_tokens_works_under_real_server(connect_server):
    # Reproduces the __main__/keel.server contextvar split: the auth'd token
    # handlers must see the principal AuthMiddleware set when run via `-m keel.server`.
    asyncio.run(_seed_person_token(_dsn()))
    req = urllib.request.Request(connect_server + "/api/tokens",
                                 headers={"Authorization": "Bearer ctx-ptok"})
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 200
