from keel import repo
from keel.principal import Principal
from keel.events import validate_chain
from keel.tools.record_decision import record_decision
import keel.conflict as conflict_pkg
from tests.fakes import ScriptedJudge


async def _person_session(conn, pid, name, session):
    person = await repo.upsert_person(conn, pid, name, name + "-tok")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", session, [])
    return person, part


async def test_change_alert_to_overlapping_claimer_excludes_author(conn, db_pool):
    from datetime import datetime, timedelta, timezone
    pid = await repo.upsert_project(conn, "demo")
    author_person, author_part = await _person_session(conn, pid, "vasan", "s1")
    other_person, other_part = await _person_session(conn, pid, "teammate", "s2")
    fut = datetime.now(timezone.utc) + timedelta(hours=1)
    # both the author's session and the teammate claim api:orders
    await repo.insert_claim(conn, pid, author_part, ["api:orders"], fut)
    await repo.insert_claim(conn, pid, other_part, ["api:orders"], fut)
    out = await record_decision(db_pool, Principal(pid, author_person, "s1"),
                                statement="orders API uses cursor pagination", rationale="r",
                                scope_tags=["api:orders"])
    assert out["conflicts"] == []  # provider=none -> no detection
    # teammate (other_part) alerted; author's own session (author_part) NOT
    teammate_alerts = await repo.pending_alerts_for_participant(conn, other_part)
    author_alerts = await repo.pending_alerts_for_participant(conn, author_part)
    assert len(teammate_alerts) == 1 and teammate_alerts[0]["kind"] == "change"
    assert author_alerts == []
    assert await validate_chain(conn, pid) is True


async def test_no_alert_for_nonoverlapping_or_expired_claim(conn, db_pool):
    from datetime import datetime, timedelta, timezone
    pid = await repo.upsert_project(conn, "demo")
    author_person, author_part = await _person_session(conn, pid, "vasan", "s1")
    other_person, other_part = await _person_session(conn, pid, "teammate", "s2")
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    fut = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.insert_claim(conn, pid, other_part, ["ui:checkout"], fut)   # wrong scope
    _, exp_part = await _person_session(conn, pid, "exp", "s3")
    await repo.insert_claim(conn, pid, exp_part, ["api:orders"], past)     # expired
    await record_decision(db_pool, Principal(pid, author_person, "s1"),
                          statement="orders API uses cursor pagination", rationale="r",
                          scope_tags=["api:orders"])
    assert await repo.pending_alerts_for_participant(conn, other_part) == []
    assert await repo.pending_alerts_for_participant(conn, exp_part) == []


async def test_supersede_alerts_dependent(conn, db_pool):
    pid = await repo.upsert_project(conn, "demo")
    author_person, author_part = await _person_session(conn, pid, "vasan", "s1")
    dep_person, dep_part = await _person_session(conn, pid, "teammate", "s2")
    first = await record_decision(db_pool, Principal(pid, author_person, "s1"),
                                  statement="page size is 20", rationale="r",
                                  scope_tags=["api:orders"])
    await repo.insert_dependency(conn, first["decision_id"], dep_part)
    await record_decision(db_pool, Principal(pid, author_person, "s1"),
                          statement="page size is 50", rationale="r",
                          scope_tags=["api:orders"], supersedes=first["decision_id"])
    alerts = await repo.pending_alerts_for_participant(conn, dep_part)
    assert len(alerts) == 1 and alerts[0]["kind"] == "change"


async def test_conflict_alert_to_candidate_owner(conn, db_pool, monkeypatch):
    monkeypatch.setattr(conflict_pkg, "get_judge", lambda settings=None: ScriptedJudge())
    pid = await repo.upsert_project(conn, "demo")
    owner_person, owner_part = await _person_session(conn, pid, "owner", "s1")
    # owner records cursor; a SECOND session of the owner will receive the conflict alert
    _, owner_part2 = await _person_session(conn, pid, "owner", "s2")
    await record_decision(db_pool, Principal(pid, owner_person, "s1"),
                          statement="orders API uses cursor-based pagination", rationale="r",
                          scope_tags=["api:orders"])
    # a different author records the contradicting offset decision
    author2_person, _ = await _person_session(conn, pid, "vasan2", "s3")
    out = await record_decision(db_pool, Principal(pid, author2_person, "s3"),
                                statement="orders API should use offset pagination", rationale="r",
                                scope_tags=["api:orders"])
    assert len(out["conflicts"]) == 1
    owner_alerts = await repo.pending_alerts_for_participant(conn, owner_part)
    assert any(a["kind"] == "conflict" for a in owner_alerts)
