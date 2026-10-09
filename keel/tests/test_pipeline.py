from keel import repo
from keel.llm.embeddings import DeterministicEmbedder
from keel.conflict.pipeline import detect, Subject
from keel.conflict.judge import Judgment
from tests.fakes import ScriptedJudge, ErroringJudge, CountingJudge


async def _ctx(conn):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "v", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    return pid, person, part


async def _active(conn, pid, person, part, stmt, scope, emb):
    return await repo.insert_decision(conn, project_id=pid, statement=stmt, rationale="r",
                                      scope_tags=scope, owner_person_id=person,
                                      source_participant_id=part, embedding=emb)


async def test_disabled_when_judge_none(conn):
    e = DeterministicEmbedder(); pid, person, part = await _ctx(conn)
    await _active(conn, pid, person, part, "cursor pagination", ["api:orders"], await e.embed("cursor"))
    res = await detect(conn, pid, Subject("offset pagination", ["api:orders"],
                       await e.embed("offset"), "decision", "00000000-0000-0000-0000-0000000000aa"),
                       judge=None, top_k=8, threshold=0.6, persist=True)
    assert res.coverage == "disabled" and res.conflicts == []
    assert await conn.fetchval("SELECT count(*) FROM conflict WHERE project_id=$1", pid) == 0


async def test_persists_contradiction(conn):
    e = DeterministicEmbedder(); pid, person, part = await _ctx(conn)
    await _active(conn, pid, person, part, "orders API uses cursor pagination",
                 ["api:orders"], await e.embed("cursor"))
    res = await detect(conn, pid, Subject("use offset pagination for orders", ["api:orders"],
                       await e.embed("offset"), "decision", "00000000-0000-0000-0000-0000000000aa"),
                       judge=ScriptedJudge(), top_k=8, threshold=0.6, persist=True, model="m1")
    assert len(res.conflicts) == 1 and res.conflicts[0].relation == "contradicts"
    assert res.conflicts[0].severity == "high" and res.coverage == "full" and res.degraded is False
    assert await conn.fetchval("SELECT count(*) FROM conflict WHERE project_id=$1", pid) == 1


async def test_no_persist(conn):
    e = DeterministicEmbedder(); pid, person, part = await _ctx(conn)
    await _active(conn, pid, person, part, "orders API uses cursor pagination",
                 ["api:orders"], await e.embed("cursor"))
    res = await detect(conn, pid, Subject("offset pagination", ["api:orders"],
                       await e.embed("offset"), "planned_action", "planned"),
                       judge=ScriptedJudge(), top_k=8, threshold=0.6, persist=False, model="m1")
    assert len(res.conflicts) == 1
    assert await conn.fetchval("SELECT count(*) FROM conflict WHERE project_id=$1", pid) == 0


async def test_evidence_gate_drops_noncited(conn):
    e = DeterministicEmbedder(); pid, person, part = await _ctx(conn)
    await _active(conn, pid, person, part, "orders API uses cursor pagination",
                 ["api:orders"], await e.embed("cursor"))
    class Lying:
        async def judge(self, s, c): return Judgment(relation="contradicts", confidence=0.9,
                                                     explanation="x", evidence="NOT PRESENT")
    res = await detect(conn, pid, Subject("offset", ["api:orders"], await e.embed("offset"),
                       "decision", "00000000-0000-0000-0000-0000000000aa"), judge=Lying(), top_k=8, threshold=0.6, persist=False)
    assert res.conflicts == []


async def test_fail_open_degraded(conn):
    e = DeterministicEmbedder(); pid, person, part = await _ctx(conn)
    await _active(conn, pid, person, part, "orders API uses cursor pagination",
                 ["api:orders"], await e.embed("cursor"))
    res = await detect(conn, pid, Subject("offset", ["api:orders"], await e.embed("offset"),
                       "decision", "00000000-0000-0000-0000-0000000000aa"), judge=ErroringJudge(), top_k=8, threshold=0.6, persist=False)
    assert res.degraded is True and res.coverage == "degraded" and res.conflicts == []


async def test_cache_avoids_second_call(conn):
    e = DeterministicEmbedder(); pid, person, part = await _ctx(conn)
    await _active(conn, pid, person, part, "orders API uses cursor pagination",
                 ["api:orders"], await e.embed("cursor"))
    j = CountingJudge()
    subj = Subject("offset pagination", ["api:orders"], await e.embed("offset"), "decision", "00000000-0000-0000-0000-0000000000aa")
    await detect(conn, pid, subj, judge=j, top_k=8, threshold=0.6, persist=False, model="m1")
    await detect(conn, pid, subj, judge=j, top_k=8, threshold=0.6, persist=False, model="m1")
    assert j.n == 1
