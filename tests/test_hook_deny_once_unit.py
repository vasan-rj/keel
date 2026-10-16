"""Exercise the real Bash hook against controlled MCP HTTP responses, without a DB."""
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import shutil
import threading
import time

import pytest

HOOK = Path(__file__).resolve().parents[1] / "adapters/claude-code/hooks/pre_tool_use.sh"


@pytest.fixture
def hook_endpoint():
    state = {"statement": "use cursor pagination", "evidence": "cursor", "relation": "contradicts"}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if request["params"]["name"] == "get_context":
                response = {"decisions": [{"id": "decision-1", "statement": state["statement"], "rationale": "scales"}]}
            else:
                response = {"conflicts": [{"candidate_id": "decision-1", "relation": state["relation"],
                                           "evidence": state["evidence"], "explanation": "different pagination"}]}
            payload = json.dumps({"result": {"content": [{"type": "text", "text": json.dumps(response)}]}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp", state
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def run_hook(tmp_path, endpoint, *, session="s1", old="old", new="use offset", state_home=None):
    mapping = tmp_path / ".keel"
    mapping.mkdir(exist_ok=True)
    (mapping / "scopes.json").write_text(json.dumps([{"pattern": "orders", "scope_tags": ["api:orders"]}]))
    payload = {"session_id": session, "cwd": tmp_path.as_posix(), "tool_name": "Edit",
               "tool_input": {"file_path": "src/orders.py", "old_string": old, "new_string": new}}
    result = subprocess.run(
        [shutil.which("bash") or "bash", HOOK.as_posix()], input=json.dumps(payload), capture_output=True, text=True,
        env={**os.environ, "KEEL_URL": endpoint, "KEEL_TOKEN": "test-only",
             "XDG_STATE_HOME": (state_home or (tmp_path / "state")).as_posix(),
             "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"},
        timeout=60 if os.name == "nt" else 15)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout) if result.stdout.strip() else None


def test_identical_retry_allows_but_changed_action_or_session_warns(tmp_path, hook_endpoint):
    endpoint, state = hook_endpoint
    assert run_hook(tmp_path, endpoint)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert run_hook(tmp_path, endpoint) is None
    assert run_hook(tmp_path, endpoint, old="different")["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert run_hook(tmp_path, endpoint, session="s2")["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_quote_changes_do_not_reset_warning_but_decision_changes_do(tmp_path, hook_endpoint):
    endpoint, state = hook_endpoint
    assert run_hook(tmp_path, endpoint) is not None
    state["evidence"] = "pagination"
    assert run_hook(tmp_path, endpoint) is None
    state["statement"] = "always use cursor pagination"
    assert run_hook(tmp_path, endpoint) is not None


def test_expired_warning_warns_again(tmp_path, hook_endpoint):
    endpoint, state = hook_endpoint
    assert run_hook(tmp_path, endpoint) is not None
    markers = list((tmp_path / "state/keel/deny-once").iterdir())
    assert len(markers) == 1 and len(markers[0].name) == 64
    assert list(markers[0].iterdir()) == []
    old = time.time() - 16 * 60
    os.utime(markers[0], (old, old))
    assert run_hook(tmp_path, endpoint) is not None


@pytest.mark.parametrize("relation", ["duplicates", "supersedes"])
def test_informational_relations_never_deny(tmp_path, hook_endpoint, relation):
    endpoint, state = hook_endpoint
    state["relation"] = relation
    assert run_hook(tmp_path, endpoint) is None


def test_unwritable_state_fails_open(tmp_path, hook_endpoint):
    endpoint, state = hook_endpoint
    state_home = tmp_path / "not-a-directory"
    state_home.write_text("file")
    assert run_hook(tmp_path, endpoint, state_home=state_home) is None


def test_full_edit_fingerprint_includes_text_after_truncation(tmp_path, hook_endpoint):
    endpoint, state = hook_endpoint
    assert run_hook(tmp_path, endpoint, new="x" * 2100 + "first") is not None
    assert run_hook(tmp_path, endpoint, new="x" * 2100 + "second") is not None
