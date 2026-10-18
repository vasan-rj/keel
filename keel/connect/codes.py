import secrets

_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_device_code() -> str:
    return secrets.token_urlsafe(32)


def new_user_code() -> str:
    pick = lambda n: "".join(secrets.choice(_ALPHABET) for _ in range(n))
    return f"{pick(4)}-{pick(4)}"
