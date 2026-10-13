import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    llm_provider: str = "anthropic"
    llm_model: str = "anthropic/claude-sonnet-5-5"
    embedding_provider: str = "deterministic"
    embedding_model: str | None = None
    embedding_dim: int = 1536
    conflict_threshold: float = 0.6
    conflict_topk: int = 8
    llm_timeout_s: float = 20.0
    judgment_cache: bool = True
    rrf_k: int = 60
    scope_fuzzy_threshold: float = 0.8


# Dev default points at the docker-compose db (host port 5433). Override with
# DATABASE_URL for any other environment (prod/GCP sets it explicitly).
_DEFAULT_DATABASE_URL = "postgresql://keel:keel@localhost:5433/keel"


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL", _DEFAULT_DATABASE_URL),
        llm_provider=os.environ.get("KEEL_LLM_PROVIDER", "anthropic"),
        llm_model=os.environ.get("KEEL_LLM_MODEL", "anthropic/claude-sonnet-5-5"),
        embedding_provider=os.environ.get("KEEL_EMBEDDING_PROVIDER", "deterministic"),
        embedding_model=os.environ.get("KEEL_EMBEDDING_MODEL"),
        embedding_dim=int(os.environ.get("KEEL_EMBEDDING_DIM", "1536")),
        conflict_threshold=float(os.environ.get("KEEL_CONFLICT_CONFIDENCE_THRESHOLD", "0.6")),
        conflict_topk=int(os.environ.get("KEEL_CONFLICT_TOPK", "8")),
        llm_timeout_s=float(os.environ.get("KEEL_LLM_TIMEOUT_S", "20")),
        judgment_cache=os.environ.get("KEEL_JUDGMENT_CACHE", "on") != "off",
        rrf_k=int(os.environ.get("KEEL_RRF_K", "60")),
        scope_fuzzy_threshold=float(os.environ.get("KEEL_SCOPE_FUZZY_THRESHOLD", "0.8")),
    )
