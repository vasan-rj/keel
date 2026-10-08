from pathlib import Path
import asyncpg

_pool: asyncpg.Pool | None = None
_SCHEMA = Path(__file__).parent / "schema.sql"


async def init_pool(dsn: str) -> asyncpg.Pool:
    global _pool
    _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=10)
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("pool not initialized; call init_pool first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def apply_schema(conn: asyncpg.Connection) -> None:
    await conn.execute(_SCHEMA.read_text())
