import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest_asyncio

from keel.db import pool as db
from keel import repo


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _test_dsn() -> str:
    return os.environ.get("KEEL_TEST_DATABASE_URL",
                          "postgresql://keel:keel@localhost:5433/keel_test")


@pytest_asyncio.fixture
async def connect_server():
    """Launch the real Keel server with the fake Firebase verifier and a default
    project, so the full connect flow (device -> approve -> claim) runs end to end.
    Yields the http root (no /mcp)."""
    port = _free_port()
    dsn = _test_dsn()
    pool = await db.init_pool(dsn)
    async with pool.acquire() as c:
        await db.apply_schema(c)
        pid = await repo.upsert_project(c, "connect-demo")
    await db.close_pool()
    env = {**os.environ, "DATABASE_URL": dsn, "KEEL_LLM_PROVIDER": "none",
           "KEEL_FIREBASE_VERIFIER": "fake", "KEEL_DEFAULT_PROJECT_ID": str(pid),
           "PORT": str(port)}
    proc = subprocess.Popen([sys.executable, "-m", "keel.server"], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    up = False
    for _ in range(100):
        try:
            urllib.request.urlopen(base + "/mcp", data=b"{}", timeout=0.5)
        except urllib.error.HTTPError:
            up = True
            break
        except Exception:
            time.sleep(0.1)
    if not up:
        proc.terminate()
        raise RuntimeError("connect_server did not start")
    try:
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
