"""Regression for the db_pool-only test-isolation hazard (review finding #2).

Tests that use only `db_pool` (not `conn`) must still start from a clean DB.
`test_a_pollutes` writes a row; `test_b_starts_empty` must see zero regardless,
because db_pool truncates on setup. Before the fix (db_pool not truncating),
test_b saw test_a's row and failed.
"""


async def test_a_pollutes(db_pool):
    async with db_pool.acquire() as c:
        await c.execute("INSERT INTO project (name) VALUES ('pollution')")


async def test_b_starts_empty(db_pool):
    async with db_pool.acquire() as c:
        n = await c.fetchval("SELECT count(*) FROM project")
    assert n == 0
