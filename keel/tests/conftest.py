import os
import pytest
import pytest_asyncio
from keel.db import pool as db


def _test_dsn() -> str:
    return os.environ.get(
        "KEEL_TEST_DATABASE_URL",
        "postgresql://keel:keel@localhost:5433/keel_test",
    )


_ALL_TABLES = [
    "alert_feedback", "alert", "drift_signal", "decision_request", "outcome",
    "handoff", "conflict", "claim", "dependency", "event", "decision",
    "goal", "participant", "person", "project",
]


@pytest_asyncio.fixture
async def db_pool():
    # Function-scoped: a session-scoped async pool binds to a different event
    # loop than the function-scoped tests, raising "attached to a different
    # loop" under pytest-asyncio 1.x. Fresh pool per test keeps one loop.
    pool = await db.init_pool(_test_dsn())
    async with pool.acquire() as conn:
        await db.apply_schema(conn)
    yield pool
    await db.close_pool()


@pytest_asyncio.fixture
async def conn(db_pool):
    async with db_pool.acquire() as c:
        await c.execute("TRUNCATE " + ", ".join(_ALL_TABLES) + " RESTART IDENTITY CASCADE")
        yield c
