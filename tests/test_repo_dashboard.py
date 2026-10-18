from keel import repo


async def _ctx(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    return pid, person, part


async def test_list_events_newest_first_and_limit(conn):
    from keel.events import append_event
    pid, person, part = await _ctx(conn)
    for i in range(3):
        await append_event(conn, pid, actor="a", action=f"act.{i}", payload={"i": i})
    evs = await repo.list_events(conn, pid, 2)
    assert len(evs) == 2
    assert evs[0]["action"] == "act.2" and evs[1]["action"] == "act.1"


async def test_list_events_cursor_pagination(conn):
    from keel.events import append_event
    pid, person, part = await _ctx(conn)
    for i in range(5):
        await append_event(conn, pid, actor="a", action=f"act.{i}", payload={"i": i})
    p1 = await repo.list_events(conn, pid, 2)
    assert len(p1) == 2
    assert p1[0]["action"] == "act.4" and p1[1]["action"] == "act.3"

    p2 = await repo.list_events(conn, pid, 2, before_id=p1[-1]["id"])
    assert len(p2) == 2
    assert p2[0]["action"] == "act.2" and p2[1]["action"] == "act.1"

    p3 = await repo.list_events(conn, pid, 2, before_id=p2[-1]["id"])
    assert len(p3) == 1
    assert p3[0]["action"] == "act.0"


async def test_open_conflicts_excludes_resolved(conn):
    pid, person, part = await _ctx(conn)
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    c1 = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                    subject_type="decision", subject_ref=str(d["id"]),
                                    relation="contradicts", severity="high", explanation="e1")
    c2 = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                    subject_type="decision", subject_ref=str(d["id"]),
                                    relation="contradicts", severity="low", explanation="e2")
    await repo.resolve_conflict(conn, c2["id"], "keep", person)
    got = [c["id"] for c in await repo.open_conflicts(conn, pid)]
    assert c1["id"] in got and c2["id"] not in got


async def test_project_pending_alerts_and_handoffs(conn):
    pid, person, part = await _ctx(conn)
    d = await repo.insert_decision(conn, project_id=pid, statement="x", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    a = await repo.insert_alert(conn, project_id=pid, target_participant_id=part,
                                target_person_id=person, kind="change", ref_id=d["id"])
    await repo.insert_handoff(conn, project_id=pid, from_participant_id=part,
                              to_person_id=person, to_participant_id=None,
                              scope_tags=["api:orders"], decision_ids=[], conflict_ids=[],
                              note="n")
    assert [x["id"] for x in await repo.project_pending_alerts(conn, pid)] == [a["id"]]
    assert len(await repo.project_pending_handoffs(conn, pid)) == 1
    await repo.ack_alert(conn, a["id"], part)
    assert await repo.project_pending_alerts(conn, pid) == []
