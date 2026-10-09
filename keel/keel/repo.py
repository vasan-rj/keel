import asyncpg


async def upsert_project(conn, name: str):
    return await conn.fetchval(
        """INSERT INTO project (name) VALUES ($1)
           ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
           RETURNING id""",
        name,
    )


async def upsert_person(conn, project_id, display_name, token_hash):
    return await conn.fetchval(
        """INSERT INTO person (project_id, display_name, token_hash) VALUES ($1,$2,$3)
           ON CONFLICT (project_id, display_name)
           DO UPDATE SET token_hash = EXCLUDED.token_hash
           RETURNING id""",
        project_id, display_name, token_hash,
    )


async def get_person_by_token(conn, token_hash) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM person WHERE token_hash = $1", token_hash)


async def upsert_participant(conn, project_id, person_id, harness, tier, session_id, allowed_scopes):
    return await conn.fetchval(
        """INSERT INTO participant (project_id, person_id, harness, tier, session_id, allowed_scopes)
           VALUES ($1,$2,$3,$4,$5,$6)
           ON CONFLICT (project_id, person_id, session_id)
           DO UPDATE SET last_seen_at = now(), harness = EXCLUDED.harness,
                         tier = EXCLUDED.tier, allowed_scopes = EXCLUDED.allowed_scopes
           RETURNING id""",
        project_id, person_id, harness, tier, session_id, allowed_scopes,
    )


async def get_participant(conn, project_id, person_id, session_id) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM participant WHERE project_id=$1 AND person_id=$2 AND session_id=$3",
        project_id, person_id, session_id,
    )


async def insert_decision(conn, *, project_id, statement, rationale, scope_tags,
                          owner_person_id, source_participant_id, supersedes_id=None,
                          status="active", embedding=None) -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO decision
             (project_id, statement, rationale, scope_tags, owner_person_id,
              source_participant_id, supersedes_id, status, embedding)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
        project_id, statement, rationale, scope_tags, owner_person_id,
        source_participant_id, supersedes_id, status, embedding,
    )


async def mark_superseded(conn, decision_id) -> None:
    await conn.execute(
        "UPDATE decision SET status='superseded', updated_at=now() WHERE id=$1", decision_id
    )


async def get_decision(conn, decision_id) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM decision WHERE id=$1", decision_id)


async def active_decisions(conn, project_id, scope_tags) -> list[asyncpg.Record]:
    if scope_tags:
        return await conn.fetch(
            """SELECT * FROM decision
               WHERE project_id=$1 AND status='active' AND scope_tags && $2::text[]
               ORDER BY created_at DESC""",
            project_id, scope_tags,
        )
    return await conn.fetch(
        "SELECT * FROM decision WHERE project_id=$1 AND status='active' ORDER BY created_at DESC",
        project_id,
    )
