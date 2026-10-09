from keel.db import pool as db


async def test_ensure_schema_recreates_missing_tables(db_pool):
    async with db_pool.acquire() as c:
        await c.execute("DROP TABLE IF EXISTS project CASCADE")
        gone = await c.fetchrow(
            "SELECT 1 FROM information_schema.tables WHERE table_name='project'"
        )
        assert gone is None
    await db.ensure_schema(db_pool)
    async with db_pool.acquire() as c:
        back = await c.fetchrow(
            "SELECT 1 FROM information_schema.tables WHERE table_name='project'"
        )
    assert back is not None
