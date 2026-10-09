import keel.config as config


def test_database_url_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = config.get_settings()
    assert "5433" in s.database_url and s.database_url.endswith("/keel")


def test_database_url_env_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:y@host:1/db")
    assert config.get_settings().database_url == "postgresql://x:y@host:1/db"


def test_llm_defaults(monkeypatch):
    for k in ("KEEL_LLM_PROVIDER", "KEEL_LLM_MODEL", "KEEL_CONFLICT_TOPK", "KEEL_RRF_K"):
        monkeypatch.delenv(k, raising=False)
    s = config.get_settings()
    assert s.llm_provider == "anthropic" and s.llm_model == "anthropic/claude-sonnet-5-5"
    assert s.conflict_topk == 8 and s.rrf_k == 60 and s.judgment_cache is True
