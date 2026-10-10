from datetime import datetime, timedelta, timezone
from keel import repo


async def _p(conn, name, session):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, name, name + "-tok")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", session, [])
    return pid, person, part


async def test_claim_overlap_active_only(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    await repo.insert_claim(conn, pid, part, ["api:orders"], future)
    got = await repo.participants_with_claim_overlap(conn, pid, ["api:orders"])
    assert [r["id"] for r in got] == [part]
    assert await repo.participants_with_claim_overlap(conn, pid, ["ui:checkout"]) == []
    # expired claim excluded
    _, _, part2 = await _p(conn, "t", "s2")
    await repo.insert_claim(conn, pid, part2, ["api:orders"], past)
    ids = {r["id"] for r in await repo.participants_with_claim_overlap(conn, pid, ["api:orders"])}
    assert part2 not in ids and part in ids


async def test_release_claims(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.insert_claim(conn, pid, part, ["api:orders"], future)
    await repo.insert_claim(conn, pid, part, ["ui:checkout"], future)
    assert await repo.release_claims(conn, part, ["api:orders"]) == 1
    left = await repo.participants_with_claim_overlap(conn, pid, ["ui:checkout"])
    assert len(left) == 1
    assert await repo.release_claims(conn, part) == 1  # the rest


async def test_release_claims_preserves_other_tags_in_same_row(conn):
    # Releasing one tag of a multi-tag claim must NOT drop coverage of the others.
    pid, person, part = await _p(conn, "vasan", "s1")
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.insert_claim(conn, pid, part, ["api:orders", "schema:user"], future)
    released = await repo.release_claims(conn, part, ["api:orders"])
    assert released == 1
    # schema:user still claimed by this participant
    assert [r["id"] for r in await repo.participants_with_claim_overlap(conn, pid, ["schema:user"])] == [part]
    # api:orders no longer claimed
    assert await repo.participants_with_claim_overlap(conn, pid, ["api:orders"]) == []


async def test_dependency_targets(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    await repo.insert_dependency(conn, d["id"], part)
    got = await repo.participants_with_dependency(conn, [d["id"]])
    assert [r["id"] for r in got] == [part]


async def test_alert_insert_pending_deliver_ack(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    a = await repo.insert_alert(conn, project_id=pid, target_participant_id=part,
                                target_person_id=person, kind="change", ref_id=d["id"])
    pend = await repo.pending_alerts_for_participant(conn, part)
    assert [r["id"] for r in pend] == [a["id"]]
    await repo.mark_alert_delivered(conn, a["id"])
    assert (await repo.get_conflict(conn, d["id"])) is None  # unrelated id -> None
    assert await repo.ack_alert(conn, a["id"], part) is True
    assert await repo.pending_alerts_for_participant(conn, part) == []
    assert await repo.ack_alert(conn, a["id"], part) is False  # already acked


async def test_resolve_conflict(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    c = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                   subject_type="decision", subject_ref=str(d["id"]),
                                   relation="contradicts", severity="high", explanation="e")
    await repo.resolve_conflict(conn, c["id"], "keep", person)
    got = await repo.get_conflict(conn, c["id"])
    assert got["status"] == "resolved" and got["resolution"] == "keep" and got["resolved_by"] == person
