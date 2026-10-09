"""Embedders for decision subjects and stored decisions.

DeterministicEmbedder is the offline default: stable (same text -> same vector)
and 1536-dim, but NOT semantic. ProviderEmbedder calls litellm lazily; litellm
is imported only when no injected ``aembed`` callable is supplied.
"""

from __future__ import annotations

import hashlib
import math
import random
from typing import Awaitable, Callable, Optional, Protocol

from pgvector import Vector

from keel.config import Settings, get_settings

DIM = 1536


class Embedder(Protocol):
    dim: int

    async def embed(self, text: str) -> Vector: ...


class DeterministicEmbedder:
    """sha256(text)-seeded RNG -> 1536 floats in [-1, 1], L2-normalized."""

    dim = DIM

    async def embed(self, text: str) -> Vector:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest(), "big")
        rng = random.Random(seed)
        vec = [rng.uniform(-1.0, 1.0) for _ in range(self.dim)]
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return Vector([x / norm for x in vec])


class ProviderEmbedder:
    """Embedding via litellm.aembedding (lazy import) or an injected ``aembed``."""

    def __init__(
        self,
        model: str,
        aembed: Optional[Callable[[str], Awaitable[list[float]]]] = None,
        dim: int = DIM,
    ) -> None:
        if not model:
            raise ValueError("ProviderEmbedder requires a non-empty embedding model")
        self.model = model
        self.dim = dim
        self._aembed = aembed

    async def _call(self, text: str) -> list[float]:
        if self._aembed is not None:
            return await self._aembed(text)
        import litellm  # lazy: optional [llm] extra

        resp = await litellm.aembedding(model=self.model, input=[text])
        return list(resp.data[0]["embedding"])

    async def embed(self, text: str) -> Vector:
        vec = await self._call(text)
        if len(vec) != self.dim:
            raise ValueError(
                f"embedding model {self.model!r} returned dim {len(vec)}, expected {self.dim}"
            )
        return Vector(vec)


def get_embedder(settings: Optional[Settings] = None) -> Embedder:
    settings = settings or get_settings()
    if settings.embedding_provider == "deterministic":
        return DeterministicEmbedder()
    return ProviderEmbedder(model=settings.embedding_model or "")
