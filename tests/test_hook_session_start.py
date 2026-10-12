import hashlib
import os
import subprocess

from keel import repo
from tests.conftest_hookserver import hook_server  # noqa: F401

HOOK = os.path.join(os.path.dirname(__file__), "..", "adapters", "claude-code",
                    "hooks", "session_start.sh")


def _run(stdin: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", HOOK], input=stdin, text=True,
                          capture_output=True, env={**os.environ, **env})


async def test_session_start_registers_and_injects(conn, db_pool, hook_server):
    base_url, token = hook_server
    pid = await repo.upsert_project(conn, "demo")
    owner = await repo.upsert_person(conn, pid, "vasan", hashlib.sha256(b"dev-token").hexdigest())
    part = await repo.upsert_participant(conn, pid, owner, "cc", "deep", "seed", [])
    await repo.insert_decision(conn, project_id=pid, statement="orders use cursor pagination",
                               rationale="scales", scope_tags=["api:orders"],
                               owner_person_id=owner, source_participant_id=part)
    res = _run('{"session_id":"hooksess","cwd":"/x","hook_event_name":"SessionStart","source":"startup"}',
               {"KEEL_URL": base_url, "KEEL_TOKEN": token})
    assert res.returncode == 0
    assert "orders use cursor pagination" in res.stdout
    assert "data" in res.stdout.lower()  # framed as data, not instructions
    # the hook registered the participant for this session
    assert await repo.get_participant(conn, pid, owner, "hooksess") is not None


def test_session_start_fails_open_when_server_down():
    res = _run('{"session_id":"s1"}',
               {"KEEL_URL": "http://127.0.0.1:1/mcp", "KEEL_TOKEN": "dev-token"})
    assert res.returncode == 0 and res.stdout.strip() == ""


def test_session_start_no_session_id_no_output():
    res = _run('{"cwd":"/x"}', {"KEEL_URL": "http://127.0.0.1:1/mcp", "KEEL_TOKEN": "t"})
    assert res.returncode == 0 and res.stdout.strip() == ""


async def test_session_start_injects_lessons(conn, db_pool, hook_server):
    from datetime import datetime, timedelta, timezone
    base_url, token = hook_server
    pid = await repo.upsert_project(conn, "demo")
    owner = await repo.upsert_person(conn, pid, "vasan", hashlib.sha256(b"dev-token").hexdigest())
    part = await repo.upsert_participant(conn, pid, owner, "cc", "deep", "seed", [])
    fut = datetime.now(timezone.utc) + timedelta(days=7)
    await repo.insert_decision(conn, project_id=pid, statement="never log PII in the orders API",
                               rationale="compliance", scope_tags=["api:orders"],
                               owner_person_id=owner, source_participant_id=part,
                               kind="lesson", expires_at=fut)
    res = _run('{"session_id":"hooksess2","cwd":"/x","hook_event_name":"SessionStart","source":"startup"}',
               {"KEEL_URL": base_url, "KEEL_TOKEN": token})
    assert res.returncode == 0
    assert "team lessons" in res.stdout.lower()
    assert "never log PII in the orders API" in res.stdout
