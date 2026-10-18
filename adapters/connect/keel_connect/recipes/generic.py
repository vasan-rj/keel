import json
from pathlib import Path


class GenericRecipe:
    name = "generic"

    def write_config(self, dest, url, token, session) -> list:
        dest = Path(dest)
        cfg = {"mcpServers": {"keel": {
            "type": "http", "url": url.rstrip("/") + "/mcp",
            "headers": {"Authorization": "Bearer ${KEEL_TOKEN}", "X-Keel-Session": session}}}}
        out = dest / "keel.mcp.json"
        out.write_text(json.dumps(cfg, indent=2))
        env = dest / ".keel.env"
        env.write_text(f"KEEL_TOKEN={token}\n")
        return [out, env]
