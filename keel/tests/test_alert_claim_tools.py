import pytest
from keel import repo
from keel.principal import Principal
from keel.tools.alerts import list_alerts, ack_alert
from keel.tools.claims import declare_dependency, claim_scope, release_scope


async def _ctx(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    return pid, person, part


async def test_claim_and_release(conn, db_pool):
    pid, person, part = await _ctx(conn)
    out = await claim_scope(db_pool, Principal(pid, person, "s1"),
                            scope_tags=["API: Orders"], ttl_seconds=3600)
    assert out["scope_tags"] == ["api:orders"] and out["claim_id"]
    got = await repo.participants_with_claim_overlap(conn, pid, ["api:orders"])
    assert [r["id"] for r in got] == [part]
    rel = await release_scope(db_pool, Principal(pid, person, "s1"), scope_tags=["api:orders"])
    assert rel["released"] == 1


async def test_declare_dependency(conn, db_pool):
    pid, person, part = await _ctx(conn)
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    out = await declare_dependency(db_pool, Principal(pid, person, "s1"), decision_id=str(d["id"]))
    assert out["dependency_id"]
    assert [r["id"] for r in await repo.participants_with_dependency(conn, [d["id"]])] == [part]


async def test_list_and_ack_alert(conn, db_pool):
    pid, person, part = await _ctx(conn)
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    a = await repo.insert_alert(conn, project_id=pid, target_participant_id=part,
                                target_person_id=person, kind="change", ref_id=d["id"])
    listed = await list_alerts(db_pool, Principal(pid, person, "s1"))
    assert len(listed["alerts"]) == 1
    acked = await ack_alert(db_pool, Principal(pid, person, "s1"), alert_id=str(a["id"]))
    assert acked["acknowledged"] is True
    assert (await list_alerts(db_pool, Principal(pid, person, "s1")))["alerts"] == []


async def test_ack_other_participants_alert_fails(conn, db_pool):
    pid, person, part = await _ctx(conn)
    other = await repo.upsert_person(conn, pid, "teammate", "h2")
    opart = await repo.upsert_participant(conn, pid, other, "cc", "deep", "s2", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    a = await repo.insert_alert(conn, project_id=pid, target_participant_id=opart,
                                target_person_id=other, kind="change", ref_id=d["id"])
    out = await ack_alert(db_pool, Principal(pid, person, "s1"), alert_id=str(a["id"]))
    assert out["acknowledged"] is False  # not the caller's alert
    assert len(await repo.pending_alerts_for_participant(conn, opart)) == 1


async def test_ack_alert_malformed_id_no_crash(conn, db_pool):
    pid, person, part = await _ctx(conn)
    out = await ack_alert(db_pool, Principal(pid, person, "s1"), alert_id="not-a-uuid")
    assert out["acknowledged"] is False  # clean, not a DataError


async def test_declare_dependency_malformed_id_errors(conn, db_pool):
    pid, person, part = await _ctx(conn)
    with pytest.raises(ValueError):
        await declare_dependency(db_pool, Principal(pid, person, "s1"), decision_id="not-a-uuid")


async def test_declare_dependency_foreign_decision_errors(conn, db_pool):
    pid, person, part = await _ctx(conn)
    other = await repo.upsert_project(conn, "other")
    operson = await repo.upsert_person(conn, other, "x", "h3")
    opart = await repo.upsert_participant(conn, other, operson, "cc", "deep", "os", [])
    foreign = await repo.insert_decision(conn, project_id=other, statement="f", rationale="r",
                                         scope_tags=["api:orders"], owner_person_id=operson,
                                         source_participant_id=opart)
    with pytest.raises(ValueError):
        await declare_dependency(db_pool, Principal(pid, person, "s1"),
                                 decision_id=str(foreign["id"]))
