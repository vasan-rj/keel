import pytest
from keel import repo
from keel.llm.embeddings import ProviderEmbedder, DeterministicEmbedder, get_embedder
from keel.config import get_settings


async def test_provider_embedder_forwards_dimensions(monkeypatch):
    captured = {}

    async def fake_aembedding(model, input, dimensions=None, **kw):
        from types import SimpleNamespace
        captured["model"] = model
        captured["dimensions"] = dimensions
        return SimpleNamespace(data=[{"embedding": [0.01] * dimensions}])

    litellm = pytest.importorskip("litellm")  # optional [llm] dep; skip when absent (CI runs .[dev])
    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)
    e = ProviderEmbedder(model="gemini/gemini-embedding-001", dim=1536)
    vec = await e.embed("hello")
    assert captured["model"] == "gemini/gemini-embedding-001"
    assert captured["dimensions"] == 1536
    assert len(vec.to_list()) == 1536


async def test_provider_embedder_dim_mismatch_raises():
    async def fake(text):
        return [0.1] * 8
    e = ProviderEmbedder(model="m", aembed=fake, dim=16)
    with pytest.raises(ValueError):
        await e.embed("x")


def test_get_embedder_selects_provider_and_dim(monkeypatch):
    monkeypatch.setenv("KEEL_EMBEDDING_PROVIDER", "gemini")
    monkeypatch.setenv("KEEL_EMBEDDING_MODEL", "gemini/gemini-embedding-001")
    monkeypatch.setenv("KEEL_EMBEDDING_DIM", "1536")
    e = get_embedder(get_settings())
    assert isinstance(e, ProviderEmbedder)
    assert e.model == "gemini/gemini-embedding-001" and e.dim == 1536


def test_get_embedder_deterministic_default(monkeypatch):
    monkeypatch.setenv("KEEL_EMBEDDING_PROVIDER", "deterministic")
    assert isinstance(get_embedder(get_settings()), DeterministicEmbedder)


async def test_reembed_backfills_null_embeddings(conn, db_pool):
    from keel.scripts.reembed import reembed
    pid = await repo.upsert_project(conn, "demo")
    person = await repo.upsert_person(conn, pid, "vasan", "h")
    part = await repo.upsert_participant(conn, pid, person, "cc", "deep", "s1", [])
    # a decision stored WITHOUT an embedding (e.g. recorded while the embedder was down)
    d = await repo.insert_decision(conn, project_id=pid, statement="orders use cursor pagination",
                                   rationale="scales", scope_tags=["api:orders"],
                                   owner_person_id=person, source_participant_id=part,
                                   embedding=None)
    assert (await repo.get_decision(conn, d["id"]))["embedding"] is None
    n = await reembed(db_pool, project_id=pid, embedder=DeterministicEmbedder())
    assert n == 1
    assert (await repo.get_decision(conn, d["id"]))["embedding"] is not None
