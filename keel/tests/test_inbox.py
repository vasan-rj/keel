from keel.principal import Principal
from keel.inbox import build_inbox


async def test_inbox_stable_empty_shape(conn):
    # a registered session with nothing pending still gets the stable empty shape
    from keel import repo
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    await repo.upsert_participant(conn, pid, person, "cc", "deep", "s", [])
    box = await build_inbox(conn, Principal(pid, person, "s"))
    assert box == {"alerts": [], "handoffs": [], "new_lessons": []}


from keel import repo


async def test_inbox_returns_unacked_alerts_with_summary(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor pagination",
                                   rationale="r", scope_tags=["api:orders"],
                                   owner_person_id=person, source_participant_id=part)
    await repo.insert_alert(conn, project_id=pid, target_participant_id=part,
                            target_person_id=person, kind="change", ref_id=d["id"])
    box = await build_inbox(conn, Principal(pid, person, "s1"))
    assert len(box["alerts"]) == 1
    al = box["alerts"][0]
    assert al["kind"] == "change" and "cursor pagination" in al["summary"]
    assert box["handoffs"] == [] and box["new_lessons"] == []


async def test_inbox_empty_for_unregistered_session(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")  # no participant for session s9
    box = await build_inbox(conn, Principal(pid, person, "s9"))
    assert box == {"alerts": [], "handoffs": [], "new_lessons": []}


async def test_inbox_drops_after_ack(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    a = await repo.insert_alert(conn, project_id=pid, target_participant_id=part,
                                target_person_id=person, kind="change", ref_id=d["id"])
    await repo.ack_alert(conn, a["id"], part)
    box = await build_inbox(conn, Principal(pid, person, "s1"))
    assert box["alerts"] == []


async def test_inbox_includes_pending_handoff_for_target(conn):
    pid = await repo.upsert_project(conn, "demo")
    sender = await repo.upsert_person(conn, pid, "vasan", "h")
    spart = await repo.upsert_participant(conn, pid, sender, "cc", "deep", "s1", [])
    receiver = await repo.upsert_person(conn, pid, "mate", "h2")
    await repo.upsert_participant(conn, pid, receiver, "cc", "deep", "s2", [])
    h = await repo.insert_handoff(conn, project_id=pid, from_participant_id=spart,
                                  to_person_id=receiver, to_participant_id=None,
                                  scope_tags=["api:orders"], decision_ids=[], conflict_ids=[],
                                  note="take it")
    box = await build_inbox(conn, Principal(pid, receiver, "s2"))
    assert [x["id"] for x in box["handoffs"]] == [str(h["id"])]
    assert box["handoffs"][0]["note"] == "take it"
    assert box["handoffs"][0]["scope_tags"] == ["api:orders"]
    # the sender (a different person) does not see it in their inbox
    sbox = await build_inbox(conn, Principal(pid, sender, "s1"))
    assert sbox["handoffs"] == []


async def test_inbox_handoff_gone_after_status_change(conn):
    pid = await repo.upsert_project(conn, "demo")
    sender = await repo.upsert_person(conn, pid, "vasan", "h")
    spart = await repo.upsert_participant(conn, pid, sender, "cc", "deep", "s1", [])
    receiver = await repo.upsert_person(conn, pid, "mate", "h2")
    await repo.upsert_participant(conn, pid, receiver, "cc", "deep", "s2", [])
    h = await repo.insert_handoff(conn, project_id=pid, from_participant_id=spart,
                                  to_person_id=receiver, to_participant_id=None,
                                  scope_tags=["api:orders"], decision_ids=[], conflict_ids=[],
                                  note=None)
    await repo.set_handoff_status(conn, h["id"], "declined")
    box = await build_inbox(conn, Principal(pid, receiver, "s2"))
    assert box["handoffs"] == []
