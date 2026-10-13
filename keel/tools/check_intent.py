import logging
from keel.scope import normalize_tags
from keel.inbox import build_inbox
from keel.llm.embeddings import get_embedder
from keel.conflict.judge import get_judge
from keel.conflict.pipeline import detect, Subject
from keel.config import get_settings
from keel.principal import Principal

log = logging.getLogger("keel.tools")


async def check_intent(pool, principal: Principal, *, planned_action, scope_tags) -> dict:
    tags = normalize_tags(scope_tags)  # raises ValueError on empty
    s = get_settings()
    async with pool.acquire() as conn:
        try:
            embedding = await get_embedder(s).embed(planned_action)
            subject = Subject(planned_action, tags, embedding, "planned_action", "planned")
            res = await detect(conn, principal.project_id, subject, judge=get_judge(s),
                               top_k=s.conflict_topk, threshold=s.conflict_threshold, persist=False,
                               model=(None if s.llm_provider == "none" else s.llm_model),
                               rrf_k=s.rrf_k, use_cache=s.judgment_cache, settings=s)
            out = {"conflicts": [c.__dict__ for c in res.conflicts], "degraded": res.degraded,
                   "coverage": res.coverage}
        except Exception as exc:
            log.warning("check_intent detection failed; degrading: %s", exc)
            out = {"conflicts": [], "degraded": True, "coverage": "degraded"}
        out["inbox"] = await build_inbox(conn, principal)
    return out
