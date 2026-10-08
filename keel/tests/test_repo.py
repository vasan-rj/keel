from keel import repo


async def test_upsert_project_idempotent(conn):
    a = await repo.upsert_project(conn, "demo")
    b = await repo.upsert_project(conn, "demo")
    assert a == b


async def test_person_token_roundtrip(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "hash1")
    found = await repo.get_person_by_token(conn, "hash1")
    assert found["id"] == person


async def test_active_decisions_scope_filter(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "claude-code", "deep", "s1", [])
    await repo.insert_decision(conn, project_id=pid, statement="cursor pagination",
                               rationale="r", scope_tags=["api:orders"],
                               owner_person_id=person, source_participant_id=part)
    await repo.insert_decision(conn, project_id=pid, statement="guest checkout",
                               rationale="r", scope_tags=["ui:checkout"],
                               owner_person_id=person, source_participant_id=part)
    only = await repo.active_decisions(conn, pid, ["api:orders"])
    assert len(only) == 1 and only[0]["statement"] == "cursor pagination"
    alld = await repo.active_decisions(conn, pid, None)
    assert len(alld) == 2


async def test_mark_superseded(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "claude-code", "deep", "s1", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="old", rationale="r",
                                   scope_tags=["api:orders"], owner_person_id=person,
                                   source_participant_id=part)
    await repo.mark_superseded(conn, d["id"])
    assert (await repo.get_decision(conn, d["id"]))["status"] == "superseded"
