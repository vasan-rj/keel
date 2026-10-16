import logging
from dataclasses import dataclass
from pgvector import Vector
from keel import repo
from keel.events import append_event
from keel.conflict.retrieval import candidates
from keel.conflict.cache import cache_key, get_cached, put_cached

log = logging.getLogger("keel.conflict")
_HARD = {"contradicts", "supersedes"}


@dataclass
class Subject:
    text: str; scope_tags: list; embedding: Vector; subject_type: str; subject_ref: str


@dataclass
class Conflict:
    candidate_id: str; relation: str; severity: str
    explanation: str; evidence: str; confidence: float
    conflict_id: str | None = None


@dataclass
class DetectionResult:
    conflicts: list; degraded: bool; coverage: str


def _severity(c: float) -> str:
    return "high" if c >= 0.85 else "medium" if c >= 0.6 else "low"


async def detect(conn, project_id, subject, *, judge, top_k, threshold, persist,
                 model=None, use_cache=True, rrf_k=60) -> DetectionResult:
    if judge is None:
        return DetectionResult([], False, "disabled")
    exclude = subject.subject_ref if subject.subject_type == "decision" else None
    rows = await candidates(conn, project_id, subject.scope_tags, subject.embedding,
                            subject.text, top_k, exclude_decision_id=exclude, rrf_k=rrf_k)
    model = model or "default"
    conflicts, degraded = [], False
    for cand in rows:
        candidate = {"statement": cand["statement"], "rationale": cand["rationale"]}
        cand_text = f"{candidate['statement']}\n{candidate['rationale'] or ''}"
        key = cache_key(model, subject.text, cand_text) if use_cache else None
        j = await get_cached(conn, key) if key else None
        if j is None:
            try:
                j = await judge.judge(subject.text, candidate)
            except Exception as e:  # fail open: skip this candidate
                log.warning("judge failed for candidate %s: %s", cand["id"], e)
                degraded = True
                continue
            if key:
                await put_cached(conn, key, model, j)
        if j.relation not in _HARD or j.confidence < threshold:
            continue
        if not j.evidence or j.evidence not in cand_text:
            continue
        sev = _severity(j.confidence)
        conflict = Conflict(str(cand["id"]), j.relation, sev, j.explanation,
                            j.evidence, j.confidence)
        if persist:
            crow = await repo.insert_conflict(
                conn, project_id=project_id, decision_a_id=cand["id"],
                subject_type=subject.subject_type, subject_ref=subject.subject_ref,
                relation=j.relation, severity=sev, explanation=j.explanation)
            conflict.conflict_id = str(crow["id"])
        conflicts.append(conflict)
    coverage = "degraded" if degraded else "full"
    if persist and conflicts:
        await append_event(conn, project_id, actor="conflict-engine",
                           action="conflicts.detected",
                           payload={"subject_ref": subject.subject_ref,
                                    "count": len(conflicts), "coverage": coverage})
    return DetectionResult(conflicts, degraded, coverage)
