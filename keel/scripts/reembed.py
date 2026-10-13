"""Re-embed active decisions + lessons with the current embedder.

Run once after switching KEEL_EMBEDDING_PROVIDER (e.g. deterministic -> gemini), so the
vector arm of retrieval doesn't mix random (deterministic) and semantic embeddings.

    python -m keel.scripts.reembed            # all projects, current provider
"""
import asyncio
import logging

from keel import repo
from keel.config import get_settings
from keel.db import pool as db
from keel.llm.embeddings import get_embedder

log = logging.getLogger("keel.reembed")


async def reembed(pool, project_id=None, embedder=None) -> int:
    """Re-embed active decisions/lessons; returns the count updated. A per-row embed
    failure is logged and skipped (the row keeps its old embedding)."""
    embedder = embedder or get_embedder()
    updated = 0
    async with pool.acquire() as conn:
        rows = await repo.active_records_for_reembed(conn, project_id)
        for r in rows:
            try:
                vec = await embedder.embed(f"{r['statement']}\n{r['rationale'] or ''}")
            except Exception as exc:  # fail-soft: keep the old embedding
                log.warning("reembed skipped %s: %s", r["id"], exc)
                continue
            await repo.update_embedding(conn, r["id"], vec)
            updated += 1
    return updated


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    s = get_settings()
    pool = await db.init_pool(s.database_url)
    try:
        n = await reembed(pool)
    finally:
        await db.close_pool()
    print(f"re-embedded {n} active records with "
          f"provider={s.embedding_provider} model={s.embedding_model or '(deterministic)'}")


if __name__ == "__main__":
    asyncio.run(_main())
