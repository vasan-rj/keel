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


async def insert_conflict(conn, *, project_id, decision_a_id, subject_type, subject_ref,
                          relation, severity, explanation) -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO conflict (project_id, decision_a_id, subject_type, subject_ref,
             relation, severity, explanation, status)
           VALUES ($1,$2,$3,$4,$5,$6,$7,'open') RETURNING *""",
        project_id, decision_a_id, subject_type, subject_ref, relation, severity, explanation)


# --- Propagation: claims, dependencies, alerts, participants, conflict resolve ---

async def insert_claim(conn, project_id, participant_id, scope_tags, expires_at) -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO claim (project_id, participant_id, scope_tags, expires_at)
           VALUES ($1,$2,$3,$4) RETURNING *""",
        project_id, participant_id, scope_tags, expires_at)


async def release_claims(conn, participant_id, scope_tags=None) -> int:
    """Release claims for a participant. With scope_tags, remove only the named tags
    from each overlapping claim (preserving the other tags in a multi-tag claim) and
    delete rows that become empty; returns the number of claims affected. Without
    scope_tags, delete all the participant's claims."""
    if scope_tags:
        # subtract the named tags from each overlapping claim (keeps coexisting tags)
        res = await conn.execute(
            """UPDATE claim
               SET scope_tags = ARRAY(SELECT unnest(scope_tags) EXCEPT SELECT unnest($2::text[]))
               WHERE participant_id=$1 AND scope_tags && $2::text[]""",
            participant_id, scope_tags)
        await conn.execute(
            "DELETE FROM claim WHERE participant_id=$1 AND scope_tags = '{}'::text[]",
            participant_id)
        return int(res.split()[-1])  # "UPDATE <n>" — claims touched
    res = await conn.execute("DELETE FROM claim WHERE participant_id=$1", participant_id)
    return int(res.split()[-1])  # "DELETE <n>"


async def participants_with_claim_overlap(conn, project_id, scope_tags) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT DISTINCT p.* FROM participant p
           JOIN claim c ON c.participant_id = p.id
           WHERE c.project_id=$1 AND p.status='active'
             AND c.scope_tags && $2::text[]
             AND (c.expires_at IS NULL OR c.expires_at > now())""",
        project_id, scope_tags)


async def insert_dependency(conn, decision_id, participant_id) -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO dependency (decision_id, dependent_type, dependent_ref)
           VALUES ($1,'participant',$2) RETURNING *""",
        decision_id, str(participant_id))


async def participants_with_dependency(conn, decision_ids: list) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT DISTINCT p.* FROM participant p
           JOIN dependency d ON d.dependent_type='participant' AND d.dependent_ref = p.id::text
           WHERE d.decision_id = ANY($1::uuid[]) AND p.status='active'""",
        decision_ids)


async def participants_of_person(conn, project_id, person_id) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM participant WHERE project_id=$1 AND person_id=$2 AND status='active'",
        project_id, person_id)


async def insert_alert(conn, *, project_id, target_participant_id, target_person_id,
                       kind, ref_id) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """INSERT INTO alert (project_id, target_participant_id, target_person_id, kind, ref_id)
           VALUES ($1,$2,$3,$4,$5)
           ON CONFLICT (target_participant_id, ref_id) WHERE kind='change' AND acknowledged_at IS NULL
           DO NOTHING
           RETURNING *""",
        project_id, target_participant_id, target_person_id, kind, ref_id)


async def pending_alerts_for_participant(conn, participant_id) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT * FROM alert WHERE target_participant_id=$1 AND acknowledged_at IS NULL
           ORDER BY created_at DESC, id DESC""",
        participant_id)


async def unacked_change_alert_exists(conn, participant_id, ref_id) -> bool:
    return bool(await conn.fetchval(
        """SELECT 1 FROM alert WHERE target_participant_id=$1 AND ref_id=$2
           AND kind='change' AND acknowledged_at IS NULL LIMIT 1""",
        participant_id, ref_id))


async def mark_alert_delivered(conn, alert_id) -> None:
    await conn.execute(
        "UPDATE alert SET delivered_at=now() WHERE id=$1 AND delivered_at IS NULL", alert_id)


async def ack_alert(conn, alert_id, participant_id) -> bool:
    res = await conn.execute(
        """UPDATE alert SET acknowledged_at=now()
           WHERE id=$1 AND target_participant_id=$2 AND acknowledged_at IS NULL""",
        alert_id, participant_id)
    return res.split()[-1] == "1"


async def get_conflict(conn, conflict_id) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM conflict WHERE id=$1", conflict_id)


async def resolve_conflict(conn, conflict_id, resolution, resolved_by) -> None:
    await conn.execute(
        "UPDATE conflict SET status='resolved', resolution=$2, resolved_by=$3 WHERE id=$1",
        conflict_id, resolution, resolved_by)


# --- Handoff ---

async def get_person_by_name(conn, project_id, display_name) -> asyncpg.Record | None:
    return await conn.fetchrow(
        "SELECT * FROM person WHERE project_id=$1 AND display_name=$2",
        project_id, display_name)


async def insert_handoff(conn, *, project_id, from_participant_id, to_person_id,
                         to_participant_id, scope_tags, decision_ids, conflict_ids,
                         note) -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO handoff (project_id, from_participant_id, to_person_id,
             to_participant_id, scope_tags, decision_ids, conflict_ids, note)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
        project_id, from_participant_id, to_person_id, to_participant_id,
        scope_tags, decision_ids, conflict_ids, note)


async def get_handoff(conn, handoff_id) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM handoff WHERE id=$1", handoff_id)


async def pending_handoffs_for_person(conn, project_id, to_person_id) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT * FROM handoff
           WHERE project_id=$1 AND to_person_id=$2 AND status='pending'
           ORDER BY created_at DESC""",
        project_id, to_person_id)


async def open_conflicts_in_scope(conn, project_id, scope_tags) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT c.* FROM conflict c
           JOIN decision d ON d.id = c.decision_a_id
           WHERE c.project_id=$1 AND c.status='open' AND d.scope_tags && $2::text[]
           ORDER BY c.created_at DESC""",
        project_id, scope_tags)


async def set_handoff_status(conn, handoff_id, status, *, accepted_at=None,
                             to_participant_id=None) -> None:
    await conn.execute(
        """UPDATE handoff
           SET status=$2,
               accepted_at=COALESCE($3, accepted_at),
               to_participant_id=COALESCE($4, to_participant_id)
           WHERE id=$1""",
        handoff_id, status, accepted_at, to_participant_id)


# --- Dashboard reads (read-only) ---

async def list_events(conn, project_id, limit: int, before_id: int | None = None) -> list[asyncpg.Record]:
    if before_id is not None:
        return await conn.fetch(
            "SELECT * FROM event WHERE project_id=$1 AND id < $2 ORDER BY id DESC LIMIT $3",
            project_id, before_id, limit)
    return await conn.fetch(
        "SELECT * FROM event WHERE project_id=$1 ORDER BY id DESC LIMIT $2",
        project_id, limit)


async def open_conflicts(conn, project_id) -> list[asyncpg.Record]:
    return await conn.fetch(
        "SELECT * FROM conflict WHERE project_id=$1 AND status='open' ORDER BY created_at DESC",
        project_id)


async def project_pending_alerts(conn, project_id) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT * FROM alert WHERE project_id=$1 AND acknowledged_at IS NULL
           ORDER BY created_at DESC, id DESC""",
        project_id)


async def project_pending_handoffs(conn, project_id) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT * FROM handoff WHERE project_id=$1 AND status='pending'
           ORDER BY created_at DESC""",
        project_id)


# --- Drift ---

async def insert_drift_signal(conn, *, project_id, participant_id, source, scope_tags,
                              summary, file_paths, ref, confidence, result) -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO drift_signal
             (project_id, participant_id, source, scope_tags, summary, file_paths,
              ref, confidence, result)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
        project_id, participant_id, source, scope_tags, summary, file_paths or [],
        ref, confidence, result)


# --- P1 tools: outcome, alert feedback, decision request ---

async def insert_outcome(conn, *, decision_id, result, evidence_ref, source,
                         confirmed_by) -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO outcome (decision_id, result, evidence_ref, source, confirmed_by)
           VALUES ($1,$2,$3,$4,$5) RETURNING *""",
        decision_id, result, evidence_ref, source, confirmed_by)


async def get_alert(conn, alert_id) -> asyncpg.Record | None:
    return await conn.fetchrow("SELECT * FROM alert WHERE id=$1", alert_id)


async def insert_alert_feedback(conn, *, alert_id, verdict, note) -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO alert_feedback (alert_id, verdict, note)
           VALUES ($1,$2,$3) RETURNING *""",
        alert_id, verdict, note)


async def insert_decision_request(conn, *, project_id, requester_participant_id,
                                  owner_person_id, question, options, scope_tags) -> asyncpg.Record:
    return await conn.fetchrow(
        """INSERT INTO decision_request
             (project_id, requester_participant_id, owner_person_id, question, options, scope_tags)
           VALUES ($1,$2,$3,$4,$5,$6) RETURNING *""",
        project_id, requester_participant_id, owner_person_id, question,
        options or [], scope_tags or [])
