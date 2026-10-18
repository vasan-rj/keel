import pytest
from keel.auth.verifier import FakeVerifier, get_verifier
from keel.config import Settings


def test_fake_verifier_parses_identity():
    ident = FakeVerifier().verify("fake:uid123:a@b.com")
    assert ident.uid == "uid123" and ident.email == "a@b.com"


def test_fake_verifier_rejects_garbage():
    with pytest.raises(ValueError):
        FakeVerifier().verify("not-a-fake-token")


def test_get_verifier_selects_fake():
    s = Settings(database_url="x", firebase_verifier="fake")
    assert isinstance(get_verifier(s), FakeVerifier)


def test_get_verifier_none_when_unconfigured():
    assert get_verifier(Settings(database_url="x")) is None
