import keel.config as config


def test_database_url_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    s = config.get_settings()
    assert "5433" in s.database_url and s.database_url.endswith("/keel")


def test_database_url_env_overrides(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:y@host:1/db")
    assert config.get_settings().database_url == "postgresql://x:y@host:1/db"
