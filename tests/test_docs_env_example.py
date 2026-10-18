from pathlib import Path


def test_env_example_lists_connect_vars():
    txt = Path(".env.example").read_text()
    for var in ("KEEL_FIREBASE_PROJECT_ID", "KEEL_FIREBASE_AUDIENCE",
                "KEEL_DEFAULT_PROJECT_ID", "KEEL_DEVICE_CODE_TTL_SECONDS"):
        assert var in txt


def test_architecture_documents_connect():
    txt = Path("ARCHITECTURE.md").read_text().lower()
    assert "device" in txt and "agent token" in txt
