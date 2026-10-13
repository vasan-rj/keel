import logging
import keel.conflict as conflict_pkg
from keel import repo
from keel.scope import normalize_tags
from keel.events import append_event
from keel.inbox import build_inbox
from keel.config import get_settings
from keel.llm.embeddings import get_embedder
from keel.conflict.pipeline import detect, Subject
from keel.principal import Principal

log = logging.getLogger("keel.tools")
_SOURCES = {"edit", "turn", "commit", "pr", "gateway", "slack"}


async def report_activity(pool, principal: Principal, *, source, scope_tags=None,
                          summary=None, file_paths=None, ref=None) -> dict:
    if source not in _SOURCES:
        raise ValueError(f"source must be one of {sorted(_SOURCES)}")
    tags = normalize_tags(scope_tags) if scope_tags else []
    s = get_settings()
    async with pool.acquire() as conn:
        participant = await repo.get_participant(conn, principal.project_id,
                                                 principal.person_id, principal.session_id)
        if participant is None:
            raise LookupError("session not registered; call register_session first")

        result, conflicts, confidence, related, alert_ref = "none", [], None, [], None
        if tags:
            active = await repo.active_decisions(conn, principal.project_id, tags)
            related = [str(d["id"]) for d in active]
            if active:
                result = "possible"
                alert_ref = active[0]["id"]
                subject_text = summary or ("activity on " + ", ".join(tags))
                try:
                    embedding = await get_embedder(s).embed(subject_text)
                    subject = Subject(subject_text, tags, embedding, "planned_action", "planned")
                    res = await detect(conn, principal.project_id, subject,
                                       judge=conflict_pkg.get_judge(s), top_k=s.conflict_topk,
                                       threshold=s.conflict_threshold, persist=False,
                                       model=(None if s.llm_provider == "none" else s.llm_model),
                                       rrf_k=s.rrf_k, use_cache=s.judgment_cache, settings=s)
                    if res.conflicts:
                        result = "conflict"
                        conflicts = [c.__dict__ for c in res.conflicts]
                        confidence = max(c.confidence for c in res.conflicts)
                        alert_ref = res.conflicts[0].candidate_id
                except Exception as exc:  # fail open -> stay "possible"
                    log.warning("report_activity triage degraded: %s", exc)

        async with conn.transaction():
            sig = await repo.insert_drift_signal(
                conn, project_id=principal.project_id, participant_id=participant["id"],
                source=source, scope_tags=tags, summary=summary, file_paths=file_paths or [],
                ref=ref, confidence=confidence, result=result)
            alert_id = None
            if (result in ("possible", "conflict") and alert_ref is not None
                    and not await repo.unacked_change_alert_exists(
                        conn, participant["id"], alert_ref)):
                # dedupe: don't pile up self change-alerts for the same decision
                a = await repo.insert_alert(conn, project_id=principal.project_id,
                                            target_participant_id=participant["id"],
                                            target_person_id=principal.person_id,
                                            kind="change", ref_id=alert_ref)
                if a is not None:
                    alert_id = str(a["id"])
            await append_event(conn, principal.project_id,
                               actor=f"person:{principal.person_id}/session:{principal.session_id}",
                               action="activity.reported",
                               payload={"signal_id": str(sig["id"]), "source": source,
                                        "result": result})
            box = await build_inbox(conn, principal)
    return {"signal_id": str(sig["id"]), "result": result, "related_decisions": related,
            "conflicts": conflicts, "alert_id": alert_id, "inbox": box}
