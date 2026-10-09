from keel.scope import normalize_tags
from keel.inbox import build_inbox
from keel.llm.embeddings import get_embedder
from keel.conflict.judge import get_judge
from keel.conflict.pipeline import detect, Subject
from keel.config import get_settings
from keel.principal import Principal


async def check_intent(pool, principal: Principal, *, planned_action, scope_tags) -> dict:
    tags = normalize_tags(scope_tags)  # raises ValueError on empty
    s = get_settings()
    embedding = await get_embedder(s).embed(planned_action)
    subject = Subject(planned_action, tags, embedding, "planned_action", "planned")
    async with pool.acquire() as conn:
        res = await detect(conn, principal.project_id, subject, judge=get_judge(s),
                           top_k=s.conflict_topk, threshold=s.conflict_threshold, persist=False,
                           model=(None if s.llm_provider == "none" else s.llm_model), rrf_k=s.rrf_k)
        box = await build_inbox(conn, principal)
    return {"conflicts": [c.__dict__ for c in res.conflicts], "degraded": res.degraded,
            "coverage": res.coverage, "inbox": box}
