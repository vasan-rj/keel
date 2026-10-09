import hashlib, json


def cache_key(model: str, subject_text: str, candidate_text: str) -> str:
    return hashlib.sha256(f"{model}\x00{subject_text}\x00{candidate_text}".encode()).hexdigest()


async def get_cached(conn, key: str):
    from keel.conflict.judge import Judgment
    row = await conn.fetchrow("SELECT judgment FROM judgment_cache WHERE key=$1", key)
    return Judgment(**json.loads(row["judgment"])) if row else None


async def put_cached(conn, key: str, model: str, judgment) -> None:
    await conn.execute(
        "INSERT INTO judgment_cache (key, model, judgment) VALUES ($1,$2,$3) "
        "ON CONFLICT (key) DO NOTHING", key, model, judgment.model_dump_json())
