from keel import repo
from keel.scope import normalize_tags
from keel.inbox import build_inbox
from keel.principal import Principal


def _decision_view(r) -> dict:
    return {
        "id": str(r["id"]),
        "statement": r["statement"],
        "rationale": r["rationale"],
        "scope_tags": list(r["scope_tags"]),
        "owner_person_id": str(r["owner_person_id"]) if r["owner_person_id"] else None,
        "status": r["status"],
        "created_at": r["created_at"].isoformat(),
    }


def _lesson_view(r) -> dict:
    v = _decision_view(r)
    v["expires_at"] = r["expires_at"].isoformat() if r["expires_at"] else None
    return v


async def get_context(pool, principal: Principal, *, scope_tags=None) -> dict:
    tags = normalize_tags(scope_tags) if scope_tags else None
    async with pool.acquire() as conn:
        rows = await repo.active_decisions(conn, principal.project_id, tags)
        lessons = await repo.active_lessons(conn, principal.project_id, tags)
        box = await build_inbox(conn, principal)
    return {"decisions": [_decision_view(r) for r in rows],
            "lessons": [_lesson_view(r) for r in lessons], "inbox": box}
