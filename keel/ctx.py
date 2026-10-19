"""Request-scoped principal context, in a neutral module.

Running the server as `python -m keel.server` loads it as `__main__`, while
`from keel.server import ...` loads it again as `keel.server` — two module objects
with independent module-level state. If the principal ContextVar lived in that
module, AuthMiddleware (in `__main__`) and a handler that imports from
`keel.server` would use different vars, and the handler would see no principal.
Keeping it here means every importer shares one ContextVar.
"""
import contextvars
import hashlib

from keel.principal import Principal

_principal_var: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "keel_principal", default=None
)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_principal() -> Principal:
    p = _principal_var.get()
    if p is None:
        raise PermissionError("no authenticated principal in context")
    return p
