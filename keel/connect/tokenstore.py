"""Process-local one-shot store for freshly minted agent tokens.
Plaintext never hits the DB; it lives here only until the device claim reads it.
A server restart drops it -> the claim returns token_unavailable and the human re-approves."""


class _OneShot:
    def __init__(self):
        self._d: dict[str, str] = {}

    def put(self, key: str, value: str) -> None:
        self._d[key] = value

    def pop(self, key: str):
        return self._d.pop(key, None)


ONE_SHOT = _OneShot()
