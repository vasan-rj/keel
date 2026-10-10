import pytest
from keel import repo
from keel.principal import Principal
from keel.events import validate_chain
from keel.tools.handoff import create_handoff, accept_handoff, decline_handoff
from keel.tools.record_decision import record_decision


async def _session(conn, pid, name, session):
    person = await repo.upsert_person(conn, pid, name, name + "-tok")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", session, [])
    return person, part


async def _project_with_decision(conn):
    pid = await repo.upsert_project(conn, "demo")
    sender, spart = await _session(conn, pid, "vasan", "s1")
    receiver, rpart = await _session(conn, pid, "mate", "s2")
    d = await repo.insert_decision(conn, project_id=pid, statement="orders use cursor",
                                   rationale="r", scope_tags=["api:orders"],
                                   owner_person_id=sender, source_participant_id=spart)
    return pid, sender, spart, receiver, rpart, d


async def test_create_handoff_snapshots_scope(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    c = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                   subject_type="decision", subject_ref=str(d["id"]),
                                   relation="contradicts", severity="high", explanation="e")
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["API: Orders"], note="yours now")
    assert out["status"] == "pending" and out["scope_tags"] == ["api:orders"]
    assert str(d["id"]) in out["decision_ids"] and str(c["id"]) in out["conflict_ids"]
    assert await validate_chain(conn, pid) is True


async def test_create_handoff_unknown_recipient_errors(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    with pytest.raises(LookupError):
        await create_handoff(db_pool, Principal(pid, sender, "s1"),
                             to_person="ghost", scope_tags=["api:orders"])


async def test_create_handoff_empty_scope_errors(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    with pytest.raises(ValueError):
        await create_handoff(db_pool, Principal(pid, sender, "s1"),
                             to_person="mate", scope_tags=["   "])


async def test_accept_handoff_transfers_claim_and_deps(conn, db_pool):
    from datetime import datetime, timedelta, timezone
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    # sender holds a claim on the scope
    fut = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.insert_claim(conn, pid, spart, ["api:orders"], fut)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"], note="n")
    acc = await accept_handoff(db_pool, Principal(pid, receiver, "s2"),
                               handoff_id=out["handoff_id"])
    assert acc["status"] == "accepted" and acc["dependencies"] == 1
    # receiver now claims the scope; sender's claim released
    claimers = {r["id"] for r in await repo.participants_with_claim_overlap(conn, pid, ["api:orders"])}
    assert rpart in claimers and spart not in claimers
    # receiver has a dependency on the snapshotted decision
    deps = {r["id"] for r in await repo.participants_with_dependency(conn, [d["id"]])}
    assert rpart in deps
    assert (await repo.get_handoff(conn, out["handoff_id"]))["status"] == "accepted"


async def test_accepted_handoff_rewires_propagation_to_receiver(conn, db_pool):
    # end-to-end: after transfer, a new decision on the scope by a third party
    # alerts the receiver (via the transferred claim).
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"], note="n")
    await accept_handoff(db_pool, Principal(pid, receiver, "s2"), handoff_id=out["handoff_id"])
    third, tpart = await _session(conn, pid, "third", "s3")
    await record_decision(db_pool, Principal(pid, third, "s3"),
                          statement="orders use offset", rationale="r", scope_tags=["api:orders"])
    recv_alerts = await repo.pending_alerts_for_participant(conn, rpart)
    assert any(a["kind"] == "change" for a in recv_alerts)


async def test_non_receiver_cannot_accept_or_decline(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"])
    with pytest.raises(PermissionError):
        await accept_handoff(db_pool, Principal(pid, sender, "s1"), handoff_id=out["handoff_id"])
    with pytest.raises(PermissionError):
        await decline_handoff(db_pool, Principal(pid, sender, "s1"), handoff_id=out["handoff_id"])
    assert (await repo.get_handoff(conn, out["handoff_id"]))["status"] == "pending"


async def test_double_accept_errors(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"])
    await accept_handoff(db_pool, Principal(pid, receiver, "s2"), handoff_id=out["handoff_id"])
    with pytest.raises(ValueError):
        await accept_handoff(db_pool, Principal(pid, receiver, "s2"), handoff_id=out["handoff_id"])


async def test_decline_handoff(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"])
    dec = await decline_handoff(db_pool, Principal(pid, receiver, "s2"),
                                handoff_id=out["handoff_id"])
    assert dec["status"] == "declined"
    # no claim created for receiver
    assert await repo.participants_with_claim_overlap(conn, pid, ["api:orders"]) == []


async def test_accept_malformed_id_errors_cleanly(conn, db_pool):
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    with pytest.raises(LookupError):
        await accept_handoff(db_pool, Principal(pid, receiver, "s2"), handoff_id="not-a-uuid")


async def test_accept_unregistered_session_errors(conn, db_pool):
    # receiver person exists but the accepting session has no participant row
    pid, sender, spart, receiver, rpart, d = await _project_with_decision(conn)
    out = await create_handoff(db_pool, Principal(pid, sender, "s1"),
                               to_person="mate", scope_tags=["api:orders"])
    with pytest.raises(LookupError):
        await accept_handoff(db_pool, Principal(pid, receiver, "s-unregistered"),
                             handoff_id=out["handoff_id"])
