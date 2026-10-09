import pytest
from pgvector import Vector
from keel.llm.embeddings import DeterministicEmbedder, ProviderEmbedder, get_embedder


async def test_deterministic_stable_1536():
    e = DeterministicEmbedder(); a = await e.embed("cursor"); b = await e.embed("cursor")
    assert isinstance(a, Vector) and len(a.to_list()) == 1536 and a.to_list() == b.to_list()

async def test_deterministic_differs():
    e = DeterministicEmbedder()
    assert (await e.embed("cursor")).to_list() != (await e.embed("offset")).to_list()

async def test_default_deterministic():
    assert isinstance(get_embedder(), DeterministicEmbedder)

def test_provider_requires_model():
    with pytest.raises(ValueError): ProviderEmbedder(model="")

async def test_provider_wrong_dim():
    async def fake(_): return [0.0, 1.0]
    with pytest.raises(ValueError):
        await ProviderEmbedder(model="openai/text-embedding-3-small", aembed=fake).embed("x")
