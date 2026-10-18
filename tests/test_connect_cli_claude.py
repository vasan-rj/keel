import sys
import pathlib

sys.path.insert(0, str(pathlib.Path("adapters/connect").resolve()))
from keel_connect.recipes.claude_code import ClaudeCodeRecipe  # noqa: E402


def test_claude_recipe_writes_mcp_and_env(tmp_path):
    files = ClaudeCodeRecipe().write_config(tmp_path, "http://h:8000", "tok-abc", "alice")
    mcp = (tmp_path / ".mcp.json").read_text()
    assert '"X-Keel-Session": "alice"' in mcp
    assert "${KEEL_TOKEN}" in mcp and "tok-abc" not in mcp
    assert (tmp_path / ".keel.env").read_text().strip() == "KEEL_TOKEN=tok-abc"
    assert any(f.name == ".mcp.json" for f in files)
