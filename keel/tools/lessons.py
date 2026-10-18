from datetime import datetime, timedelta, timezone

from keel.principal import Principal
from keel.authz import require_write
from keel.tools.record_decision import _record


async def record_lesson(pool, principal: Principal, *, statement, rationale, scope_tags,
                        expires_in_days=7) -> dict:
    require_write(principal)
    """Record a reusable lesson (a gotcha / rule learned the hard way). A lesson is a
    decision with kind='lesson' and an expiry; it runs the same conflict checks and is
    delivered via get_context + the inbox."""
    if not isinstance(expires_in_days, int) or expires_in_days <= 0:
        raise ValueError("expires_in_days must be a positive integer")
    expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    out = await _record(pool, principal, statement=statement, rationale=rationale,
                        scope_tags=scope_tags, kind="lesson", expires_at=expires_at)
    return {"lesson_id": out["decision_id"], "kind": "lesson", "status": out["status"],
            "scope_tags": out["scope_tags"], "conflicts": out["conflicts"],
            "expires_at": out["expires_at"], "degraded": out["degraded"],
            "coverage": out["coverage"], "inbox": out["inbox"]}
