from datetime import datetime, timedelta, timezone

import pytest
from keel import repo
from keel.principal import Principal
from keel.events import validate_chain
from keel.tools.record_decision import record_decision
from keel.tools.lessons import record_lesson
from keel.tools.get_context import get_context
from keel.inbox import build_inbox
import keel.conflict as conflict_pkg
from tests.fakes import ScriptedJudge


async def _ctx(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    return pid, person


async def test_record_lesson_creates_kind_lesson_with_expiry(conn, db_pool):
    pid, person = await _ctx(conn)
    out = await record_lesson(db_pool, Principal(pid, person, "s1"),
                              statement="prefer idempotent handlers for webhooks",
                              rationale="retries are common", scope_tags=["api:webhooks"],
                              expires_in_days=7)
    assert out["lesson_id"] and out["kind"] == "lesson" and out["expires_at"]
    row = await repo.get_decision(conn, out["lesson_id"])
    assert row["kind"] == "lesson" and row["status"] == "active" and row["expires_at"] is not None
    assert await validate_chain(conn, pid) is True


async def test_lesson_shows_in_get_context_lessons_not_decisions(conn, db_pool):
    pid, person = await _ctx(conn)
    await record_decision(db_pool, Principal(pid, person, "s1"),
                          statement="orders API uses cursor pagination", rationale="scales",
                          scope_tags=["api:orders"])
    await record_lesson(db_pool, Principal(pid, person, "s1"),
                        statement="always paginate list endpoints", rationale="perf",
                        scope_tags=["api:orders"])
    ctx = await get_context(db_pool, Principal(pid, person, "s1"), scope_tags=["api:orders"])
    dec_statements = [d["statement"] for d in ctx["decisions"]]
    les_statements = [l["statement"] for l in ctx["lessons"]]
    assert "orders API uses cursor pagination" in dec_statements
    assert "always paginate list endpoints" in les_statements
    # the lesson must NOT leak into decisions, and vice versa
    assert "always paginate list endpoints" not in dec_statements
    assert "orders API uses cursor pagination" not in les_statements
    assert ctx["lessons"][0]["expires_at"]  # lesson view carries expiry


async def test_expired_lesson_excluded(conn, db_pool):
    pid, person = await _ctx(conn)
    part = await repo.get_participant(conn, pid, person, "s1")
    past = datetime.now(timezone.utc) - timedelta(days=1)
    fut = datetime.now(timezone.utc) + timedelta(days=1)
    await repo.insert_decision(conn, project_id=pid, statement="expired lesson", rationale="r",
                               scope_tags=["api:orders"], owner_person_id=person,
                               source_participant_id=part["id"], kind="lesson", expires_at=past)
    await repo.insert_decision(conn, project_id=pid, statement="live lesson", rationale="r",
                               scope_tags=["api:orders"], owner_person_id=person,
                               source_participant_id=part["id"], kind="lesson", expires_at=fut)
    active = [r["statement"] for r in await repo.active_lessons(conn, pid, None)]
    assert "live lesson" in active and "expired lesson" not in active
    ctx = await get_context(db_pool, Principal(pid, person, "s1"))
    assert [l["statement"] for l in ctx["lessons"]] == ["live lesson"]


async def test_inbox_new_lessons_populated(conn, db_pool):
    pid, person = await _ctx(conn)
    await record_lesson(db_pool, Principal(pid, person, "s1"),
                        statement="rate-limit external calls", rationale="avoid bans",
                        scope_tags=["api:orders"])
    box = await build_inbox(conn, Principal(pid, person, "s1"))
    assert len(box["new_lessons"]) == 1
    assert box["new_lessons"][0]["statement"] == "rate-limit external calls"


async def test_record_lesson_runs_conflict_check(conn, db_pool, monkeypatch):
    monkeypatch.setattr(conflict_pkg, "get_judge", lambda settings=None: ScriptedJudge())
    pid, person = await _ctx(conn)
    await record_decision(db_pool, Principal(pid, person, "s1"),
                          statement="orders API uses cursor-based pagination", rationale="scales",
                          scope_tags=["api:orders"])
    out = await record_lesson(db_pool, Principal(pid, person, "s1"),
                              statement="orders API should use offset pagination",
                              rationale="simpler", scope_tags=["api:orders"])
    assert len(out["conflicts"]) == 1 and out["conflicts"][0]["relation"] == "contradicts"


async def test_record_lesson_rejects_bad_expiry(conn, db_pool):
    pid, person = await _ctx(conn)
    with pytest.raises(ValueError):
        await record_lesson(db_pool, Principal(pid, person, "s1"),
                            statement="x", rationale="y", scope_tags=["api:orders"],
                            expires_in_days=0)
