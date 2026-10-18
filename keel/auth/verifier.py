from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VerifiedIdentity:
    uid: str
    email: str | None


class Verifier(Protocol):
    def verify(self, id_token: str) -> VerifiedIdentity: ...


class FakeVerifier:
    """Test-only. Token format: 'fake:<uid>:<email>'."""
    def verify(self, id_token: str) -> VerifiedIdentity:
        parts = id_token.split(":")
        if len(parts) != 3 or parts[0] != "fake" or not parts[1]:
            raise ValueError("invalid fake id token")
        return VerifiedIdentity(uid=parts[1], email=parts[2] or None)


class GoogleVerifier:
    def __init__(self, audience: str):
        self._audience = audience

    def verify(self, id_token: str) -> VerifiedIdentity:
        from google.oauth2 import id_token as google_id_token
        from google.auth.transport import requests as google_requests
        try:
            claims = google_id_token.verify_oauth2_token(
                id_token, google_requests.Request(), self._audience)
        except Exception as e:  # ValueError / GoogleAuthError
            raise ValueError(f"invalid google id token: {e}") from e
        return VerifiedIdentity(uid=claims["sub"], email=claims.get("email"))


def get_verifier(settings) -> Verifier | None:
    if settings.firebase_verifier == "fake":
        return FakeVerifier()
    aud = settings.firebase_audience or settings.firebase_project_id
    if aud:
        return GoogleVerifier(aud)
    return None
