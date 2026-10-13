from keel.conflict.pipeline import detect, Subject
from keel.conflict.judge import get_judge
from keel.config import get_settings


async def check_on_insert(conn, project_id, decision_row, *, judge=None,
                          threshold=None, top_k=None) -> dict:
    s = get_settings()
    judge = judge if judge is not None else get_judge(s)
    subject = Subject(
        text=f"{decision_row['statement']}\n{decision_row['rationale'] or ''}",
        scope_tags=list(decision_row["scope_tags"]),
        embedding=decision_row["embedding"],
        subject_type="decision", subject_ref=str(decision_row["id"]))
    res = await detect(conn, project_id, subject, judge=judge,
                       top_k=top_k if top_k is not None else s.conflict_topk,
                       threshold=threshold if threshold is not None else s.conflict_threshold,
                       persist=True,
                       model=(None if s.llm_provider == "none" else s.llm_model), rrf_k=s.rrf_k,
                       use_cache=s.judgment_cache, settings=s)
    return {"conflicts": [c.__dict__ for c in res.conflicts],
            "degraded": res.degraded, "coverage": res.coverage}
