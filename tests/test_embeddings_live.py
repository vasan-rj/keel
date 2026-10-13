import math
import os

import pytest

pytestmark = [pytest.mark.llm,
              pytest.mark.skipif(
                  not (os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")),
                  reason="no embedding provider key (GEMINI_API_KEY / OPENAI_API_KEY)")]


def _cos(x, y):
    dot = sum(a * b for a, b in zip(x, y))
    nx = math.sqrt(sum(a * a for a in x)) or 1.0
    ny = math.sqrt(sum(b * b for b in y)) or 1.0
    return dot / (nx * ny)


async def test_real_embeddings_are_semantic_and_1536():
    from keel.llm.embeddings import ProviderEmbedder
    model = ("gemini/gemini-embedding-001" if os.environ.get("GEMINI_API_KEY")
             else "openai/text-embedding-3-small")
    e = ProviderEmbedder(model=model, dim=1536)
    a = (await e.embed("the orders API uses cursor-based pagination")).to_list()
    b = (await e.embed("paginate the orders endpoint with an opaque cursor")).to_list()
    c = (await e.embed("the weather in Paris is sunny this afternoon")).to_list()
    assert len(a) == 1536
    # a related sentence must be closer than an unrelated one
    assert _cos(a, b) > _cos(a, c)
