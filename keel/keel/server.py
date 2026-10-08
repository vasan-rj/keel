import contextlib
import contextvars
import hashlib
import os

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from keel.db import pool as db
from keel.config import get_settings
from keel.principal import Principal
from keel import repo
from keel.tools.register_session import register_session as _register_session
from keel.tools.get_context import get_context as _get_context
from keel.tools.record_decision import record_decision as _record_decision

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


async def _resolve_principal(token: str, session_id: str | None) -> Principal | None:
    pool = db.get_pool()
    async with pool.acquire() as conn:
        person = await repo.get_person_by_token(conn, token_hash(token))
    if person is None:
        return None
    return Principal(project_id=person["project_id"], person_id=person["id"],
                     session_id=session_id)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        auth = request.headers.get("authorization", "")
        session = request.headers.get("x-keel-session")
        token = auth[7:] if auth.lower().startswith("bearer ") else None
        if not token:
            return JSONResponse({"error": "missing bearer token"}, status_code=401)
        principal = await _resolve_principal(token, session)
        if principal is None:
            return JSONResponse({"error": "invalid token"}, status_code=401)
        tok = _principal_var.set(principal)
        try:
            return await call_next(request)
        finally:
            _principal_var.reset(tok)


mcp = FastMCP("keel", stateless_http=True, json_response=True)


@mcp.tool()
async def register_session(harness: str, tier: str, session_id: str,
                           allowed_scopes: list[str] | None = None) -> dict:
    return await _register_session(db.get_pool(), current_principal(),
                                   harness=harness, tier=tier, session_id=session_id,
                                   allowed_scopes=allowed_scopes)


@mcp.tool()
async def get_context(scope_tags: list[str] | None = None) -> dict:
    return await _get_context(db.get_pool(), current_principal(), scope_tags=scope_tags)


@mcp.tool()
async def record_decision(statement: str, rationale: str, scope_tags: list[str],
                          supersedes: str | None = None) -> dict:
    return await _record_decision(db.get_pool(), current_principal(), statement=statement,
                                  rationale=rationale, scope_tags=scope_tags, supersedes=supersedes)


# Test-only helper: run the real auth resolution + dispatch without MCP framing.
_HANDLERS = {
    "register_session": lambda p, a: _register_session(db.get_pool(), p, **a),
    "get_context": lambda p, a: _get_context(db.get_pool(), p, **a),
    "record_decision": lambda p, a: _record_decision(db.get_pool(), p, **a),
}


async def call_tool_for_test(token: str, session: str, tool: str, args: dict) -> dict:
    principal = await _resolve_principal(token, session)
    if principal is None:
        raise PermissionError("invalid token")
    return await _HANDLERS[tool](principal, args)


def _build_app():
    mcp_app = mcp.streamable_http_app()   # Starlette app, MCP route at /mcp
    mcp_app.add_middleware(AuthMiddleware)

    # starlette 1.x has no add_event_handler; wrap FastMCP's lifespan so the
    # pool is initialized/closed around the MCP session manager's own lifespan.
    original_lifespan = mcp_app.router.lifespan_context

    @contextlib.asynccontextmanager
    async def lifespan(app):
        await db.init_pool(get_settings().database_url)
        try:
            async with original_lifespan(app):
                yield
        finally:
            await db.close_pool()

    mcp_app.router.lifespan_context = lifespan
    return mcp_app


app = _build_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
