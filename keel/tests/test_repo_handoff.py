from keel import repo


async def _p(conn, name, session):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, name, name + "-tok")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", session, [])
    return pid, person, part


async def test_get_person_by_name(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    got = await repo.get_person_by_name(conn, pid, "vasan")
    assert got["id"] == person
    assert await repo.get_person_by_name(conn, pid, "nobody") is None


async def test_handoff_insert_get_pending_status(conn):
    pid, sender, spart = await _p(conn, "vasan", "s1")
    receiver = await repo.upsert_person(conn, pid, "mate", "mate-tok")
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=sender,
                                   source_participant_id=spart)
    h = await repo.insert_handoff(conn, project_id=pid, from_participant_id=spart,
                                  to_person_id=receiver, to_participant_id=None,
                                  scope_tags=["api:orders"], decision_ids=[d["id"]],
                                  conflict_ids=[], note="take this")
    assert h["status"] == "pending" and h["note"] == "take this"
    assert list(h["decision_ids"]) == [d["id"]]
    got = await repo.get_handoff(conn, h["id"])
    assert got["id"] == h["id"]
    pend = await repo.pending_handoffs_for_person(conn, pid, receiver)
    assert [r["id"] for r in pend] == [h["id"]]
    # sender is not a recipient
    assert await repo.pending_handoffs_for_person(conn, pid, sender) == []


async def test_set_handoff_status_accept(conn):
    from datetime import datetime, timezone
    pid, sender, spart = await _p(conn, "vasan", "s1")
    receiver = await repo.upsert_person(conn, pid, "mate", "mate-tok")
    rpart = await repo.upsert_participant(conn, pid, receiver, "cc", "deep", "s2", [])
    h = await repo.insert_handoff(conn, project_id=pid, from_participant_id=spart,
                                  to_person_id=receiver, to_participant_id=None,
                                  scope_tags=["api:orders"], decision_ids=[], conflict_ids=[],
                                  note=None)
    await repo.set_handoff_status(conn, h["id"], "accepted",
                                  accepted_at=datetime.now(timezone.utc), to_participant_id=rpart)
    got = await repo.get_handoff(conn, h["id"])
    assert got["status"] == "accepted" and got["to_participant_id"] == rpart
    assert got["accepted_at"] is not None
    assert await repo.pending_handoffs_for_person(conn, pid, receiver) == []


async def test_open_conflicts_in_scope(conn):
    pid, person, part = await _p(conn, "vasan", "s1")
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    other = await repo.insert_decision(conn, project_id=pid, statement="ui", rationale="r",
                                       scope_tags=["ui:checkout"], owner_person_id=person,
                                       source_participant_id=part)
    c = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                   subject_type="decision", subject_ref=str(d["id"]),
                                   relation="contradicts", severity="high", explanation="e")
    await repo.insert_conflict(conn, project_id=pid, decision_a_id=other["id"],
                               subject_type="decision", subject_ref=str(other["id"]),
                               relation="contradicts", severity="low", explanation="e2")
    got = await repo.open_conflicts_in_scope(conn, pid, ["api:orders"])
    assert [r["id"] for r in got] == [c["id"]]  # only the api:orders conflict
