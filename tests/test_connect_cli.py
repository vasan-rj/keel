import sys
import pathlib
import json
import urllib.request

sys.path.insert(0, str(pathlib.Path("adapters/connect").resolve()))
from keel_connect import client                            # noqa: E402
from keel_connect.recipes.generic import GenericRecipe     # noqa: E402
from tests.conftest_connect_server import connect_server   # noqa: F401,E402


def _approve(base, user_code):
    req = urllib.request.Request(
        base + "/connect/approve", method="POST",
        data=json.dumps({"user_code": user_code, "scope": "full"}).encode(),
        headers={"Authorization": "Bearer fake:uid-cli:cli@x.com",
                 "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5)


def test_full_device_flow(connect_server):
    base = connect_server
    start = client.start_device(base, "generic", "laptop")
    _approve(base, start["user_code"])
    claim = client.poll_until_claimed(base, start["device_code"], interval=0)
    assert claim["token"] and claim["scope"] == "full"


def test_generic_recipe_writes_config(tmp_path):
    files = GenericRecipe().write_config(tmp_path, "http://h:8000", "tok-123", "s1")
    content = (tmp_path / "keel.mcp.json").read_text()
    assert "http://h:8000" in content and "tok-123" not in content  # token via env, not inlined
    assert any(f.name == "keel.mcp.json" for f in files)
