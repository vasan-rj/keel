import asyncio
import os
from keel import repo
from keel.db import pool as db
from keel.config import get_settings
from keel.server import token_hash


async def seed(pool, *, dev_token: str, teammate_token: str) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            pid = await repo.upsert_project(conn, "demo")
            await repo.upsert_person(conn, pid, "vasan", token_hash(dev_token))
            await repo.upsert_person(conn, pid, "teammate", token_hash(teammate_token))


async def _main() -> None:
    pool = await db.init_pool(get_settings().database_url)
    try:
        await seed(pool,
                   dev_token=os.environ.get("KEEL_DEV_TOKEN", "dev-token"),
                   teammate_token=os.environ.get("KEEL_TEAMMATE_TOKEN", "teammate-token"))
    finally:
        await db.close_pool()


if __name__ == "__main__":
    asyncio.run(_main())
