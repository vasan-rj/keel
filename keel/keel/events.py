import hashlib
import json
from datetime import datetime, timezone

import asyncpg


def _canonical(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def event_hash(prev_hash, project_id, actor, action, payload: dict, created_at: datetime) -> str:
    material = "\n".join([
        prev_hash or "",
        str(project_id),
        actor,
        action,
        _canonical(payload),
        created_at.astimezone(timezone.utc).isoformat(),
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _lock_key(project_id) -> int:
    # stable 32-bit key for the per-project event chain lock
    return int.from_bytes(
        hashlib.sha256(("event:" + str(project_id)).encode()).digest()[:4], "big", signed=True
    )


async def append_event(conn: asyncpg.Connection, project_id, actor, action,
                       payload: dict, created_at: datetime | None = None) -> asyncpg.Record:
    created_at = created_at or datetime.now(timezone.utc)
    await conn.execute("SELECT pg_advisory_xact_lock($1)", _lock_key(project_id))
    prev_hash = await conn.fetchval(
        "SELECT hash FROM event WHERE project_id = $1 ORDER BY id DESC LIMIT 1", project_id
    )
    h = event_hash(prev_hash, project_id, actor, action, payload, created_at)
    return await conn.fetchrow(
        """INSERT INTO event (project_id, actor, action, payload_json, prev_hash, hash, created_at)
           VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
        project_id, actor, action, _canonical(payload), prev_hash, h, created_at,
    )


async def validate_chain(conn: asyncpg.Connection, project_id) -> bool:
    rows = await conn.fetch(
        "SELECT * FROM event WHERE project_id = $1 ORDER BY id ASC", project_id
    )
    prev = None
    for r in rows:
        payload = json.loads(r["payload_json"])
        expected = event_hash(prev, project_id, r["actor"], r["action"], payload, r["created_at"])
        if expected != r["hash"] or r["prev_hash"] != prev:
            return False
        prev = r["hash"]
    return True
