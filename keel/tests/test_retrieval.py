from keel import repo
from keel.conflict.retrieval import candidates
from keel.llm.embeddings import DeterministicEmbedder


async def _seed(conn, stmt, scope, emb):
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "v", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    row = await repo.insert_decision(conn, project_id=pid, statement=stmt, rationale="r",
                                     scope_tags=scope, owner_person_id=person,
                                     source_participant_id=part, embedding=emb)
    return pid, row


async def test_scope_filter_and_self_exclusion(conn):
    e = DeterministicEmbedder(); emb = await e.embed("cursor pagination")
    pid, a = await _seed(conn, "cursor pagination", ["api:orders"], emb)
    await _seed(conn, "guest checkout", ["ui:checkout"], await e.embed("guest checkout"))
    got = await candidates(conn, pid, ["api:orders"], emb, "offset pagination", 8)
    assert [r["statement"] for r in got] == ["cursor pagination"]
    assert await candidates(conn, pid, ["api:orders"], emb, "x", 8,
                            exclude_decision_id=a["id"]) == []


async def test_keyword_arm_ranks_lexical_match(conn):
    e = DeterministicEmbedder()
    pid, _ = await _seed(conn, "orders pagination uses cursor tokens", ["api:orders"], await e.embed("a"))
    await _seed(conn, "orders unrelated billing matter", ["api:orders"], await e.embed("b"))
    got = await candidates(conn, pid, ["api:orders"], await e.embed("c"),
                           "pagination cursor tokens", 8)
    assert got[0]["statement"] == "orders pagination uses cursor tokens"


async def test_null_embedding_tolerated(conn):
    e = DeterministicEmbedder()
    pid, _ = await _seed(conn, "offset pagination", ["api:orders"], None)
    got = await candidates(conn, pid, ["api:orders"], await e.embed("cursor"), "offset", 8)
    assert len(got) == 1
