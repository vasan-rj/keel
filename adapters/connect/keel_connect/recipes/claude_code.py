import json
from pathlib import Path


class ClaudeCodeRecipe:
    name = "claude-code"

    def write_config(self, dest, url, token, session) -> list:
        dest = Path(dest)
        written = []
        cfg = {"mcpServers": {"keel": {
            "type": "http", "url": url.rstrip("/") + "/mcp",
            "headers": {"Authorization": "Bearer ${KEEL_TOKEN}", "X-Keel-Session": session}}}}
        mcp = dest / ".mcp.json"
        mcp.write_text(json.dumps(cfg, indent=2))
        written.append(mcp)
        env = dest / ".keel.env"
        env.write_text(f"KEEL_TOKEN={token}")
        written.append(env)
        # best-effort copy of the hook adapter, if present in the repo checkout
        adapter = Path(__file__).resolve().parents[3] / "claude-code"
        if adapter.is_dir():
            import shutil
            for rel in ("settings.hooks.json", ".keel/scopes.example.json"):
                src = adapter / rel
                if src.is_file():
                    out = dest / rel
                    out.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(src, out)
                    written.append(out)
            hooks_src = adapter / "hooks"
            if hooks_src.is_dir():
                shutil.copytree(hooks_src, dest / "hooks", dirs_exist_ok=True)
                written.append(dest / "hooks")
        return written
