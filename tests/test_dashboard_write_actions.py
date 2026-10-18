import httpx
from keel import repo
from keel.server import app, token_hash


def _client():
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _seed(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "alice", token_hash("owner"))
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    d = await repo.insert_decision(conn, project_id=pid, statement="cursor pagination",
                                   rationale="scales", scope_tags=["api:orders"],
                                   owner_person_id=person, source_participant_id=part)
    conflict = await repo.insert_conflict(conn, project_id=pid, decision_a_id=d["id"],
                                          subject_type="decision", subject_ref=str(d["id"]),
                                          relation="contradicts", severity="high", explanation="e")
    alert = await repo.insert_alert(conn, project_id=pid, target_participant_id=part,
                                    target_person_id=person, kind="conflict", ref_id=conflict["id"])
    return pid, person, part, d, conflict, alert


async def test_ack_alert_by_person_via_rest(conn, db_pool):
    pid, person, part, d, conflict, alert = await _seed(conn)
    async with _client() as c:
        r = await c.post(f"/api/alerts/{alert['id']}/ack",
                         headers={"Authorization": "Bearer owner"})
    assert r.status_code == 200 and r.json()["acknowledged"] is True
    row = await conn.fetchrow("SELECT acknowledged_at FROM alert WHERE id=$1", alert["id"])
    assert row["acknowledged_at"] is not None


async def test_resolve_conflict_via_rest(conn, db_pool):
    pid, person, part, d, conflict, alert = await _seed(conn)
    async with _client() as c:
        r = await c.post(f"/api/conflicts/{conflict['id']}/resolve",
                         headers={"Authorization": "Bearer owner"},
                         json={"resolution": "keep it", "outcome": "keep_existing"})
    assert r.status_code == 200 and r.json()["resolved"] is True
    assert (await repo.get_conflict(conn, conflict["id"]))["status"] == "resolved"


async def test_resolve_requires_note(conn, db_pool):
    pid, person, part, d, conflict, alert = await _seed(conn)
    async with _client() as c:
        r = await c.post(f"/api/conflicts/{conflict['id']}/resolve",
                         headers={"Authorization": "Bearer owner"}, json={"resolution": ""})
    assert r.status_code == 400


async def test_write_actions_refused_for_read_only(conn, db_pool):
    pid, person, part, d, conflict, alert = await _seed(conn)
    await repo.insert_token(conn, project_id=pid, person_id=person,
                            token_hash=token_hash("ro"), kind="agent", scope="read_only")
    h = {"Authorization": "Bearer ro"}
    async with _client() as c:
        a = await c.post(f"/api/alerts/{alert['id']}/ack", headers=h)
        rc = await c.post(f"/api/conflicts/{conflict['id']}/resolve", headers=h,
                          json={"resolution": "x", "outcome": "keep_existing"})
    assert a.status_code == 403 and rc.status_code == 403
