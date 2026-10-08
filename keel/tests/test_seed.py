import hashlib
from keel import repo
from keel.scripts.seed import seed


async def test_seed_creates_demo_project_and_people(db_pool):
    await seed(db_pool, dev_token="dev-token", teammate_token="teammate-token")
    async with db_pool.acquire() as conn:
        p = await repo.get_person_by_token(conn, hashlib.sha256(b"dev-token").hexdigest())
        t = await repo.get_person_by_token(conn, hashlib.sha256(b"teammate-token").hexdigest())
    assert p["display_name"] == "vasan"
    assert t["display_name"] == "teammate"
