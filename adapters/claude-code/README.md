# Keel — Claude Code adapter

Wire a Claude Code project to a running Keel server. The hooks inject the team's
active decisions and pending alerts at session start and before each prompt, and
the MCP connector lets the session record decisions and check intent.

## Prerequisites
- A running Keel server (see the repo README). Its URL and a bearer token
  (one token = one person in one project).
- `curl` and `jq` on your PATH. If either is missing, the hooks silently no-op
  (fail open) — Keel never blocks your session.

## Install
1. Copy the hooks into your repo and make them executable:
   ```bash
   cp -r adapters/claude-code/hooks ~/your-repo/.claude/hooks/keel
   chmod +x ~/your-repo/.claude/hooks/keel/*.sh
   ```
2. Merge `adapters/claude-code/settings.hooks.json` into your repo's
   `.claude/settings.json` (the `hooks` block).
3. Merge `adapters/claude-code/.mcp.json` into your project's MCP config and set
   `url` to your Keel server's `/mcp` endpoint.
4. Export the environment the hooks read:
   ```bash
   export KEEL_URL=https://keel.example.com/mcp   # defaults to http://localhost:8000/mcp
   export KEEL_TOKEN=<your token>
   ```
5. (Optional) Install the skill in `SKILL.md` so Claude knows when to call the tools.

### Session identity for the MCP connector
The `keel` connector authenticates with `Authorization: Bearer ${KEEL_TOKEN}` (expanded
from your shell env at launch). Claude Code does **not** auto-populate a session id into
the MCP connector's headers, so the connector's direct tool calls are not per-session by
default — the server treats them as session-less (reads work project-wide; session-scoped
writes say "not registered"). **Per-session identity comes from the deep-tier hooks**
(`session_start.sh` registers the real `session_id` Claude Code passes to hooks), which is
the guaranteed path. If you want the *connector's* tool calls scoped to a session too,
export a unique id and add the header back to `.mcp.json`:
```bash
export CLAUDE_SESSION_ID=$(uuidgen)   # per shell/session
# in .mcp.json headers: "X-Keel-Session": "${CLAUDE_SESSION_ID}"
```
The server ignores an unexpanded `${CLAUDE_SESSION_ID}` (it won't create a bogus participant).

### Enabling conflict detection (LLM)
Detection is LLM-backed. With `KEEL_LLM_PROVIDER=none` the server records decisions but
`check_intent`/`record_decision` report `coverage:"degraded"` and flag no semantic
conflicts. Set a provider + key to turn it on, e.g. OpenAI-compatible RouterPlus:
```bash
KEEL_LLM_PROVIDER=openai OPENAI_API_KEY=<routerplus key> \
  OPENAI_API_BASE=https://api.routerplus.com/v1 KEEL_LLM_MODEL=openai/gpt-4.1-mini \
  python -m keel.server
```

## What the hooks do
- **SessionStart** — registers this session and injects the active team decisions
  plus any pending alerts/handoffs as context.
- **UserPromptSubmit** — injects any pending alerts/handoffs before each prompt
  ("before the next action").

## PreToolUse deny-once (optional)
Create `.keel/scopes.json` in your repo (copy `adapters/claude-code/.keel/scopes.example.json`)
mapping file-path regexes to scope tags. On an `Edit`/`Write`/`MultiEdit` whose file maps to a
scope that carries active decisions, Keel checks the edit and — if it contradicts one — **denies
the tool once** with the decision as the reason, so you re-plan. It is NOT a lock and changes no
code. Most edits skip the LLM: the hook first does a cheap decision-free screen and only escalates
when the scope actually carries decisions. Skipped (edit allowed) when `.keel/scopes.json` is
absent, nothing matches, Keel is unreachable, or no LLM is configured.

Only `contradicts` results deny an edit; duplicates and proposed supersessions do
not. The hook remembers a warning for the **exact tool input, session, server,
project path, and decision context** for 15 minutes. Re-plan after a warning, or
retry the identical edit to proceed knowingly. A changed edit, another session,
or changed decision context gets a fresh check and warning. Retries still contact
Keel; the marker does not bypass detection. This is advisory acknowledgment, not
proof that the edit is compliant.

Warning markers contain only SHA-256 fingerprints and live under
`${XDG_STATE_HOME:-$HOME/.local/state}/keel/deny-once/`. The hook also requires
`sha256sum` or `shasum`; if hashing or marker storage fails it allows the edit.
Marker directories may be removed after the session; their removal only causes
another warning.

## PostToolUse drift (optional)
With the same `.keel/scopes.json`, after an edit on a mapped scope that carries active
decisions, Keel records the activity (`report_activity`) and — if it drifts — injects a
re-check note and leaves a `change` alert in your inbox. This is the remediation counterpart
to the PreToolUse deny-once prevention. Skipped (silent) when the map is absent, nothing
matches, or Keel is unreachable.

## Session contract
Keel authenticates every call by bearer token (one person/project); `X-Keel-Session`
identifies the session. **Read tools** (`get_context`, the dashboard `/api/*`) work even
without a valid session header — they return project-wide data and an empty inbox.
**Session-scoped write/registration tools** (`record_decision`, `accept_handoff`,
`ack_alert`, …) require a registered participant and fail with a clear "session not
registered; call register_session first" if the session is missing or unregistered. The
SessionStart hook registers the session, so in normal use this is automatic. An
unexpanded `${CLAUDE_SESSION_ID}` header is treated as no session (never a bogus participant).

## Fail-open guarantee
Every hook exits `0` on any error (server down, bad token, missing `jq`/`curl`,
malformed input). A Keel outage never blocks or interrupts your session.
