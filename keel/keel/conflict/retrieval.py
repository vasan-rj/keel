"""Hybrid candidate retrieval: pgvector cosine + Postgres FTS, fused with RRF."""


async def candidates(conn, project_id, scope_tags, embedding, query_text, top_k,
                     exclude_decision_id=None, rrf_k=60):
    return await conn.fetch(
        """
        WITH scoped AS (
          SELECT *, (embedding <=> $3) AS vdist
          FROM decision
          WHERE project_id=$1 AND status='active' AND scope_tags && $2::text[]
            AND ($5::uuid IS NULL OR id <> $5)
        ),
        vec AS (SELECT id, row_number() OVER (ORDER BY vdist ASC NULLS LAST) AS rn FROM scoped),
        kw AS (
          SELECT id, row_number() OVER (
                   ORDER BY ts_rank(ts, websearch_to_tsquery('english', $4)) DESC) AS rn
          FROM scoped
          WHERE $4 <> '' AND ts @@ websearch_to_tsquery('english', $4)
        )
        SELECT s.*,
               COALESCE(1.0/($6 + vec.rn), 0) + COALESCE(1.0/($6 + kw.rn), 0) AS rrf
        FROM scoped s
        LEFT JOIN vec ON vec.id = s.id
        LEFT JOIN kw  ON kw.id  = s.id
        ORDER BY rrf DESC, s.created_at, s.id
        LIMIT $7
        """,
        project_id, scope_tags, embedding, query_text or "", exclude_decision_id, rrf_k, top_k)
