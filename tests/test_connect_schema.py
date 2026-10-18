async def test_connect_schema_columns_and_tables(db_pool):
    async with db_pool.acquire() as c:
        cols = {r["column_name"] for r in await c.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name='person'")}
        assert {"email", "firebase_uid"} <= cols
        for t in ("token", "device_grant"):
            assert await c.fetchval(
                "SELECT to_regclass($1)", f"public.{t}") is not None


async def test_apply_schema_is_idempotent(db_pool):
    from keel.db import pool as db
    async with db_pool.acquire() as c:
        await db.apply_schema(c)   # second apply must not raise
        await db.apply_schema(c)
