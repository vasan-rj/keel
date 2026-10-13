import pytest
from keel import repo
from keel.config import Settings
from keel.conflict.judge import select_model, Judgment
from keel.conflict.pipeline import detect, Subject
from keel.llm.embeddings import DeterministicEmbedder


def _s(**kw):
    return Settings(database_url="x", llm_model="strong-m", **kw)


# --- select_model heuristic ---

def test_router_off_without_cheap_model():
    assert select_model("anything", "candidate", ["api:orders"], _s()) == "strong-m"


def test_router_simple_uses_cheap():
    s = _s(llm_model_cheap="cheap-m")
    assert select_model("short subject", "short candidate", ["api:orders"], s) == "cheap-m"


def test_router_complex_uses_strong():
    s = _s(llm_model_cheap="cheap-m")
    # cue word
    assert select_model("we should replace the pagination approach", "x", ["api:orders"], s) == "strong-m"
    # many scope tags (>2)
    assert select_model("a", "b", ["a:1", "b:2", "c:3"], s) == "strong-m"
    # long combined text
    assert select_model("x" * 400, "y" * 400, [], s) == "strong-m"


# --- detect keys the cache on the ROUTED model (the coupling fix) ---

class _CapturingJudge:
    def __init__(self):
        self.models = []

    async def judge(self, subject_text, candidate, model=None):
        self.models.append(model)
        return Judgment(relation="contradicts", confidence=0.9, explanation="e",
                        evidence=candidate["statement"])


async def test_detect_routes_and_keys_cache_on_routed_model(conn):
    e = DeterministicEmbedder()
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "v", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    await repo.insert_decision(conn, project_id=pid, statement="orders API uses cursor pagination",
                               rationale="r", scope_tags=["api:orders"], owner_person_id=person,
                               source_participant_id=part, embedding=await e.embed("cursor"))
    # "switch" is a cue word -> complex -> strong model
    subj = Subject("switch the orders API to offset pagination", ["api:orders"],
                   await e.embed("offset"), "decision", "00000000-0000-0000-0000-0000000000aa")
    judge = _CapturingJudge()
    s = _s(llm_model_cheap="cheap-m")
    res = await detect(conn, pid, subj, judge=judge, top_k=8, threshold=0.6, persist=False,
                       settings=s)
    assert len(res.conflicts) == 1
    assert judge.models == ["strong-m"]  # judge called with the routed model
    assert await conn.fetchval("SELECT model FROM judgment_cache LIMIT 1") == "strong-m"


async def test_detect_backcompat_without_settings(conn):
    # settings=None -> uses the model param, as before (routing disabled path)
    e = DeterministicEmbedder()
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "v", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    await repo.insert_decision(conn, project_id=pid, statement="orders API uses cursor pagination",
                               rationale="r", scope_tags=["api:orders"], owner_person_id=person,
                               source_participant_id=part, embedding=await e.embed("cursor"))
    subj = Subject("switch the orders API to offset pagination", ["api:orders"],
                   await e.embed("offset"), "decision", "00000000-0000-0000-0000-0000000000bb")
    judge = _CapturingJudge()
    await detect(conn, pid, subj, judge=judge, top_k=8, threshold=0.6, persist=False, model="m1")
    assert judge.models == ["m1"]
    assert await conn.fetchval("SELECT model FROM judgment_cache LIMIT 1") == "m1"
