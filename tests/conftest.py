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
    "judgment_cache", "alert_feedback", "alert", "drift_signal", "decision_request", "outcome",
    "handoff", "conflict", "claim", "dependency", "event", "decision",
    "goal", "participant", "device_grant", "token", "person", "project",
]


async def _truncate_all(c) -> None:
    await c.execute("TRUNCATE " + ", ".join(_ALL_TABLES) + " RESTART IDENTITY CASCADE")


@pytest_asyncio.fixture
async def db_pool():
    # Function-scoped: a session-scoped async pool binds to a different event
    # loop than the function-scoped tests, raising "attached to a different
    # loop" under pytest-asyncio 1.x. Fresh pool per test keeps one loop.
    # Truncate on setup so tests that use ONLY db_pool (no `conn` fixture) start
    # from a clean DB — otherwise their correctness depends on file order and on
    # the global token_hash uniqueness constraint never colliding.
    pool = await db.init_pool(_test_dsn())
    async with pool.acquire() as c:
        await db.apply_schema(c)
        await _truncate_all(c)
    yield pool
    await db.close_pool()


@pytest_asyncio.fixture
async def conn(db_pool):
    async with db_pool.acquire() as c:
        await _truncate_all(c)
        yield c


@pytest.fixture(autouse=True)
def _deterministic_llm(monkeypatch):
    monkeypatch.setenv("KEEL_LLM_PROVIDER", "none")
    monkeypatch.setenv("KEEL_EMBEDDING_PROVIDER", "deterministic")
