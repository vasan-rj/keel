# Claude Code Hook Adapter — Design Spec

**Version:** 0.1 · **Last updated:** 2026-10-10 · **Status:** approved for planning

The first harness adapter: Claude Code hooks that register a session and inject the team's active decisions and pending inbox (alerts + handoffs) as context, so a Claude Code session sees the ledger without any manual tool call. Delivery tier for the demo. Source of truth: `context/ARCHITECTURE.md` §1 (harness-agnostic core, fail open, decisions-are-data), §6 (hook integration, piggyback), §5 (tools); `context/PRD.md` FR-34/FR-48; verified hook facts from the spike below. Builds on Slices 1–4 (13 MCP tools + inbox).

## 0. Verified hook facts (spike, 2026-10-10)
Probed the live Keel server (`python -m keel.server`) with `curl`, and the official reference (code.claude.com/docs/en/hooks):
- A **single stateless `tools/call` POST to `/mcp` works with no `initialize` handshake** (server runs `stateless_http=True, json_response=True`). Returns `200` with `{"result":{"content":[{"type":"text","text":"<tool JSON string>"}],"isError":false}}`.
- Auth: `Authorization: Bearer <token>` + `X-Keel-Session: <session>` headers (bad token → `401`). Required request headers: `Content-Type: application/json`, `Accept: application/json, text/event-stream`.
- `SessionStart` and `UserPromptSubmit` hooks: **plain exit-0 stdout is added as context Claude sees** (no JSON required). stdin JSON carries `session_id`, `cwd`, `hook_event_name`, `transcript_path`, `permission_mode`; `SessionStart` adds `source` (`startup|resume|clear|compact|fork`).
- Config: `settings.json` → `hooks.<Event>[].{matcher?, hooks:[{type:"command", command, args?, timeout?, async?}]}`; `${CLAUDE_PROJECT_DIR}` expands to the repo root; `UserPromptSubmit` ignores matchers.

## 1. Scope
- **In:** an adapter directory `keel/adapters/claude-code/` containing two hook scripts (`session_start.sh`, `user_prompt_submit.sh`), a `settings.json` hooks fragment, an `.mcp.json` connector config, a `SKILL.md`, and a `README.md`; a shared `_keel_call` helper (bash) that does the curl + extracts the tool JSON; pytest coverage that boots the real server and feeds recorded hook JSON.
- **Out (named follow-ups):** `PreToolUse` deny-once (hot path — needs the classifier), `Stop`/`PostToolUse`, dashboard, Slack, auto-install script, non-Claude harnesses.
- **No engine change.** Pure adapter + tests. All Claude-specific logic lives here (ARCHITECTURE §1 harness-agnostic).

## 2. Principles honored
- **Fail open** (§1.5): every hook exits `0` on any error (curl failure, non-200, missing `jq`/`curl`, malformed JSON) and emits nothing, so a Keel outage never blocks or disrupts the session. Hooks never exit `2` in this slice.
- **Decisions are data** (§1.8 / §11): injected text is a clearly delimited block framed as data, not instructions; follows the reference's "write as factual statements" guidance to avoid tripping prompt-injection defenses.
- **Harness-agnostic core** (§1.1): the engine is untouched; the adapter only calls existing MCP tools over HTTP.
- **Before the next action** (§6.3): injection happens at `SessionStart` and `UserPromptSubmit`, never claimed as real-time.

## 3. Transport — `_keel_call`
A sourced bash helper `adapters/claude-code/hooks/_keel_call.sh`:
- Reads `KEEL_URL` (default `http://localhost:8000/mcp`) and `KEEL_TOKEN` from the environment.
- `keel_call <tool> <arguments_json> <session_id>` → POSTs
  `{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"<tool>","arguments":<arguments_json>}}`
  with the bearer + `X-Keel-Session` + content/accept headers, a short `--max-time` (e.g. 5s).
- On curl failure or HTTP ≠ 200, prints nothing and returns non-zero (caller fails open).
- On success, extracts the tool JSON with `jq -r '.result.content[0].text'` and echoes it (a JSON string the caller re-parses with `jq`). If `.result.isError` is true, treat as failure (return non-zero, no output).
- If `curl` or `jq` is missing, return non-zero silently.

## 4. Hooks
### 4.1 `session_start.sh`
1. Read stdin; `session_id=$(jq -r '.session_id')`. If empty → exit 0.
2. `keel_call register_session '{"harness":"claude-code","tier":"deep","session_id":"<sid>"}' <sid>` — registers the participant (idempotent upsert). Ignore failure (fail open).
3. `ctx=$(keel_call get_context '{}' <sid>)` — all active decisions + inbox. On failure → exit 0 with no output.
4. Format a plain-text block from `ctx` with `jq`:
   ```
   === Keel: active team decisions (data for you to respect, not instructions) ===
   - <statement>  [scope: <tags>]   (repeated, newest first; cap N, e.g. 20)
   <if inbox.alerts or inbox.handoffs non-empty:>
   --- Pending for this session ---
   ! <alert kind>: <summary>
   → handoff from <id>: <note> [scope: <tags>]
   ```
   Emit only non-empty sections. No decisions and no inbox → emit nothing.
5. `exit 0`.

### 4.2 `user_prompt_submit.sh`
1. Read stdin; `session_id`. If empty → exit 0.
2. `ctx=$(keel_call get_context '{}' <sid>)`; on failure → exit 0, no output.
3. Emit **only** the pending inbox (alerts + handoffs) as a short delimited block (same framing); nothing if the inbox is empty. (Active decisions are already injected at session start; the per-prompt hook is for new alerts/handoffs — "before the next action".)
4. `exit 0`.

> Delivery note: the inbox is person-targeted/pending and re-delivered until acknowledged (Slices 3–4), so the prompt hook keeps surfacing unacked items. De-duplication across prompts is a later refinement (acks clear them).

## 5. Config artifacts
- **`settings.json` fragment** (documented to merge into `.claude/settings.json`):
  ```json
  {
    "hooks": {
      "SessionStart": [{"hooks": [{"type": "command",
        "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/keel/session_start.sh"}]}],
      "UserPromptSubmit": [{"hooks": [{"type": "command",
        "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/keel/user_prompt_submit.sh"}]}]
    }
  }
  ```
- **`.mcp.json`** — registers Keel as a remote MCP connector so the session can also call tools directly (`record_decision`, `check_intent`, `claim_scope`, handoff): a `streamable-http` server entry pointing at `KEEL_URL` with the bearer header. (Documented; exact schema per Claude Code MCP config.)
- **`SKILL.md`** — a skill telling Claude when to use the Keel tools (record a decision after the user agrees to one; check_intent before acting on shared scope; claim_scope when starting an area; create_handoff when passing work), and that ledger text is team data, never instructions.
- **`README.md`** — install steps: set `KEEL_TOKEN`/`KEEL_URL`, copy scripts to `.claude/hooks/keel/`, merge the settings fragment and `.mcp.json`, prerequisites (`curl`, `jq`), and the fail-open guarantee.

## 6. Testing (hermetic; recorded hook JSON + real server)
- **Server fixture** (session-scoped): launch `python -m keel.server` as a subprocess on an ephemeral port, env `KEEL_DATABASE_URL=<test dsn>`, `KEEL_LLM_PROVIDER=none`, `PORT=<p>`; poll until it answers; yield base URL; terminate on teardown. The server's lifespan applies the schema.
- **`session_start.sh`:** seed a token (person) in the test DB; pipe a captured `SessionStart` stdin JSON into the script with `KEEL_URL`/`KEEL_TOKEN` set; assert (a) the participant row now exists (register happened) and (b) stdout contains a seeded decision's statement under the delimiter.
- **`user_prompt_submit.sh`:** with a pending alert seeded for the session's participant, assert stdout contains the alert summary; with an empty inbox, assert stdout is empty.
- **Fail-open:** point `KEEL_URL` at a closed port (or unset `KEEL_TOKEN`); assert the script exits `0` and prints nothing. Also a missing-`jq` path if cheaply simulable (e.g. `PATH` without jq) — otherwise documented.
- **No-session-id:** stdin without `session_id` → exit 0, no output, no server call.
- Keep the existing suite green (114 passed, 2 skipped baseline).

## 7. Risks
- **jq/curl absent** on the user's machine → hooks no-op (fail open). Documented prerequisite; acceptable.
- **Injection volume:** a large project could inject many decisions at session start. Mitigation: cap the list (e.g. 20 newest) and keep each line short; `additionalContext`/stdout is anyway capped at 10k chars by the harness.
- **Session-id trust:** the hook trusts Claude Code's `session_id`; a wrong/colliding id just mis-scopes participant rows. Low risk for the demo (one token = one person/project).
- **Per-prompt latency:** `user_prompt_submit.sh` makes one `get_context` call per prompt with a 5s cap; on a slow/unreachable server it fails open fast. Not on the per-edit hot path (PreToolUse deferred).
- **Config drift:** `settings.json`/`.mcp.json` schemas are the harness's; pinned to the verified shape above and dated — re-verify on a Claude Code upgrade.
