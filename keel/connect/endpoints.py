import json
from datetime import datetime, timezone

from starlette.responses import JSONResponse

from keel.db import pool as db
from keel import repo
from keel.config import get_settings
from keel.connect import codes
from keel.connect.tokenstore import ONE_SHOT
from keel.auth.verifier import get_verifier
from keel.events import append_event


def _token_hash(t: str) -> str:
    from keel.server import token_hash
    return token_hash(t)


async def _body(request):
    try:
        return json.loads(await request.body() or b"{}")
    except ValueError:
        return {}


async def start_device(request):
    data = await _body(request)
    harness = (data.get("harness") or "").strip()
    if not harness:
        return JSONResponse({"error": "harness is required"}, status_code=400)
    s = get_settings()
    device_code = codes.new_device_code()
    from datetime import timedelta
    expires = datetime.now(timezone.utc) + timedelta(seconds=s.device_code_ttl_s)
    pool = db.get_pool()
    async with pool.acquire() as conn:
        g = None
        for _ in range(5):  # retry on the (vanishingly rare) user_code collision
            try:
                g = await repo.insert_device_grant(
                    conn, device_code_hash=_token_hash(device_code),
                    user_code=codes.new_user_code(), harness=harness,
                    label=data.get("label"), expires_at=expires)
                break
            except Exception:
                continue
        if g is None:
            return JSONResponse({"error": "could not allocate code"}, status_code=500)
    base = str(request.base_url).rstrip("/")
    return JSONResponse({"device_code": device_code, "user_code": g["user_code"],
                         "verification_uri": f"{base}/connect",
                         "interval": s.device_poll_interval_s,
                         "expires_in": s.device_code_ttl_s})


async def poll_token(request):
    data = await _body(request)
    device_code = data.get("device_code") or ""
    s = get_settings()
    pool = db.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            g = await conn.fetchrow(
                "SELECT * FROM device_grant WHERE device_code_hash=$1 FOR UPDATE",
                _token_hash(device_code))
            if g is None:
                return JSONResponse({"error": "invalid_grant"}, status_code=404)
            now = datetime.now(timezone.utc)
            # Expiry takes precedence over everything while not yet claimed.
            if g["status"] in ("pending", "approved") and g["expires_at"] <= now:
                await repo.update_device_grant(conn, g["id"], status="expired")
                return JSONResponse({"error": "expired_token"}, status_code=410)
            # Terminal states ignore poll rate.
            if g["status"] == "denied":
                return JSONResponse({"error": "access_denied"}, status_code=403)
            if g["status"] in ("expired", "claimed"):
                return JSONResponse({"error": "expired_token"}, status_code=410)
            if g["status"] == "pending":
                # slow_down only applies while the client is legitimately waiting.
                if g["last_polled_at"] and (now - g["last_polled_at"]).total_seconds() < s.device_poll_interval_s:
                    await repo.update_device_grant(conn, g["id"], last_polled_at=now)
                    return JSONResponse({"error": "slow_down"}, status_code=429)
                await repo.update_device_grant(conn, g["id"], last_polled_at=now)
                return JSONResponse({"error": "authorization_pending"}, status_code=428)
            if g["status"] == "approved":
                plaintext = ONE_SHOT.pop(str(g["id"]))
                await repo.update_device_grant(conn, g["id"], status="claimed")
                if plaintext is None:
                    return JSONResponse({"error": "token_unavailable"}, status_code=410)
                token_row = await repo.get_token(conn, g["token_id"])
                return JSONResponse({"token": plaintext, "project": str(token_row["project_id"]),
                                     "person": str(g["person_id"]), "scope": g["scope"]})
    return JSONResponse({"error": "invalid_grant"}, status_code=404)


def _row_token(r):
    return {"id": str(r["id"]), "kind": r["kind"], "label": r["label"], "scope": r["scope"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "revoked_at": r["revoked_at"].isoformat() if r["revoked_at"] else None}


async def list_tokens_handler(request):
    from keel.server import current_principal
    p = current_principal()
    pool = db.get_pool()
    async with pool.acquire() as conn:
        rows = await repo.list_tokens(conn, p.project_id, p.person_id)
    return JSONResponse({"tokens": [_row_token(r) for r in rows]})


async def revoke_token_handler(request):
    from keel.server import current_principal
    from keel.ids import as_uuid
    p = current_principal()
    try:
        tid = as_uuid(request.path_params["token_id"])
    except ValueError:
        return JSONResponse({"error": "bad token id"}, status_code=400)
    pool = db.get_pool()
    async with pool.acquire() as conn:
        ok = await repo.revoke_token(conn, tid, p.person_id)
    return JSONResponse({"revoked": ok})


async def approve(request):
    data = await _body(request)
    auth = request.headers.get("authorization", "")
    id_token = auth[7:] if auth.lower().startswith("bearer ") else None
    user_code = (data.get("user_code") or "").strip().upper()
    scope = data.get("scope") or "full"
    if scope not in ("full", "read_only"):
        return JSONResponse({"error": "scope must be full or read_only"}, status_code=400)
    if not id_token:
        return JSONResponse({"error": "missing id token"}, status_code=401)
    settings = get_settings()
    verifier = get_verifier(settings)
    if verifier is None:
        return JSONResponse({"error": "login not configured"}, status_code=503)
    try:
        identity = verifier.verify(id_token)
    except ValueError:
        return JSONResponse({"error": "invalid id token"}, status_code=401)

    pool = db.get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            person = await repo.get_person_by_identity(conn, uid=identity.uid, email=identity.email)
            if person is None:
                if not settings.default_project_id:
                    return JSONResponse({"error": "no_project_for_identity"}, status_code=403)
                person = await repo.create_person_identity(
                    conn, settings.default_project_id, identity.email, identity.uid)
            elif person["firebase_uid"] is None:
                await repo.set_person_firebase_uid(conn, person["id"], identity.uid)

            g = await conn.fetchrow(
                "SELECT * FROM device_grant WHERE user_code=$1 AND status='pending' FOR UPDATE",
                user_code)
            if g is None:
                return JSONResponse({"error": "unknown or already-used code"}, status_code=404)
            if g["expires_at"] <= datetime.now(timezone.utc):
                await repo.update_device_grant(conn, g["id"], status="expired")
                return JSONResponse({"error": "expired_token"}, status_code=410)

            plaintext = codes.new_device_code()
            tok = await repo.insert_token(
                conn, project_id=person["project_id"], person_id=person["id"],
                token_hash=_token_hash(plaintext), kind="agent", label=g["harness"], scope=scope)
            await repo.update_device_grant(
                conn, g["id"], status="approved", scope=scope, person_id=person["id"],
                token_id=tok["id"], approved_at=datetime.now(timezone.utc))
            await append_event(conn, person["project_id"],
                               actor=f"person:{person['id']}", action="agent.connected",
                               payload={"grant_id": str(g["id"]), "harness": g["harness"],
                                        "scope": scope, "token_id": str(tok["id"])})
    ONE_SHOT.put(str(g["id"]), plaintext)
    return JSONResponse({"approved": True,
                         "agent": {"person": str(person["id"]), "scope": scope,
                                   "harness": g["harness"]}})
