# keel_connect — agent onboarding CLI

Brings an agent online against a Keel server using the device-code flow, so you
never hand-edit SQL or paste raw tokens.

## Usage

```bash
# from the repo root (adapters/connect must be on PYTHONPATH)
PYTHONPATH=adapters/connect python -m keel_connect <harness> --url http://localhost:8000

# harness is one of: claude-code, generic
```

Flow:
1. The CLI prints a `user_code` and a verification URL (and opens your browser).
2. Open the URL, sign in with Google, enter the code, choose **Full** or
   **Read-only**, and approve.
3. The CLI receives a scoped agent token once and writes the harness config.

Flags: `--label` (names the token), `--dest` (where to write config, default `.`),
`--session` (the `X-Keel-Session` value, default `agent`), `--no-open` (don't open
the browser).

## What gets written

- **claude-code:** `.mcp.json` (url + `Authorization: Bearer ${KEEL_TOKEN}` + a
  literal `X-Keel-Session`), plus the hook adapter (`settings.hooks.json`, `hooks/`,
  `.keel/scopes.example.json`) copied from `adapters/claude-code/` when present.
- **generic:** `keel.mcp.json` with the MCP server block.

In both cases the token itself is written only to **`.keel.env`** (gitignored) as
`KEEL_TOKEN=...` — never inlined into tracked config. Load it before starting your
agent:

```bash
source .keel.env   # or: export KEEL_TOKEN=...
```

## Revoking

A connected agent's token is listed and revocable from the dashboard's **Your
tokens** panel, or via `POST /api/tokens/{id}/revoke`. A revoked token stops
authenticating immediately.
