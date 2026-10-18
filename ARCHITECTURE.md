# Keel — Architecture

Keel is a vendor-neutral **intent & decision ledger** for teams and their AI agents,
exposed over the Model Context Protocol (MCP). It captures decisions from agent
sessions, detects contradictions against active decisions with cited evidence, and
propagates changes to the sessions and people affected — before the next action.

This document describes what is actually built. For the roadmap see
[BACKLOG.md](BACKLOG.md); for tool usage see [adapters/agent-skill/SKILL.md](adapters/agent-skill/SKILL.md).

## Design principles (binding)
- **Harness-agnostic core.** The engine knows nothing about Claude Code; hooks and
  harness wiring live under `adapters/`.
- **Fail open.** If Keel is unreachable or the LLM degrades, agent sessions keep
  working. Detection degrades to a logged "coverage: degraded"; hooks exit 0 (allow).
- **Warn, don't block (by default).** Conflicts are surfaced with evidence; humans
  resolve. The one exception is the opt-in PreToolUse "deny-once," which blocks a
  single edit with the decision as the reason — still not a persistent lock.
- **Evidence or silence.** No conflict is emitted without quoting the text of the
  decision it conflicts with (a hard gate in the pipeline).
- **Append-only.** Every state change is an `event` in a per-project hash chain;
  current state is derived. `validate_chain` verifies integrity.
- **Decisions are data, not instructions.** Ledger text injected into an agent's
  context is delimited and framed as data; the judge prompt ignores instructions
  embedded in the compared text.

## Components
```
agent (Claude Code / Codex / …)
  │  MCP tools/call (stateless HTTP, bearer + X-Keel-Session)
  ▼
FastMCP server (keel/keel/server.py)
  ├─ AuthMiddleware        token → Principal(project, person, session); CORS
  ├─ 17 MCP tools          thin wrappers → keel/keel/tools/*
  ├─ /api/state, /api/events   read-only REST for the dashboard
  └─ conflict pipeline     retrieval → LLM judge → evidence gate
        │
        ▼
Postgres 16 + pgvector     keel/keel/db/schema.sql (append-only event log + state)
```
- **MCP server** — `mcp.server.fastmcp.FastMCP("keel", stateless_http=True,
  json_response=True)`. One stateless `tools/call` POST works with no `initialize`
  handshake. Ships server-level `instructions` (the golden rules + workflow).
- **Auth** — `AuthMiddleware` reads `Authorization: Bearer <token>` (sha256 →
  `person`, which carries the project) and `X-Keel-Session` → a `Principal`
  propagated via a contextvar. An unexpanded `${…}` session header is normalized to
  none. CORS allows configured origins (`KEEL_CORS_ORIGINS`, default `*`).
- **Tools (17)** — register_session, get_context, record_decision, check_intent,
  declare_dependency, claim_scope/release_scope, list_alerts/ack_alert,
  resolve_conflict, create_handoff/accept_handoff/decline_handoff, report_activity,
  record_outcome, rate_alert, request_decision. Every response carries an `inbox`.
- **Dashboard** — a separate static app (`dashboard/`) that reads `/api/state` and
  `/api/events` with the bearer token; renders the event timeline + active decisions,
  open conflicts, pending alerts, pending handoffs.

## Data model (keel/keel/db/schema.sql)
- `project`, `person(project_id, token_hash)`, `participant(person, harness, tier,
  session_id, allowed_scopes…)` — identity. A participant ≈ an agent session.
- `decision(kind[decision|lesson], statement, rationale, scope_tags[], status, owner,
  supersedes_id, embedding vector(1536), ts tsvector)` — the ledger. A **lesson** is a
  decision with an expiry (same lifecycle + checks).
- `conflict(decision_a_id, relation, severity, explanation, status, resolution)`.
- `claim(participant, scope_tags[], expires_at)` and
  `dependency(decision_id, dependent_type[participant|artifact], dependent_ref)` —
  drive who gets alerted.
- `alert(target_participant, target_person, kind[conflict|change], ref_id,
  created_at, delivered_at, acknowledged_at)`.
- `handoff(from_participant, to_person, to_participant?, scope_tags[], decision_ids[],
  conflict_ids[], status[pending|accepted|declined])`.
- `event(actor, action, payload_json, prev_hash, hash)` — append-only hash chain.
- `judgment_cache`, `outcome`, `alert_feedback`, `drift_signal`, `decision_request`.

**Scope tags** (`api:orders`, `schema:user`, …) are the join key everywhere; they are
normalized server-side. A scope-tag mismatch is the single silent point of failure.

## Conflict pipeline (keel/keel/conflict/)
`check_on_insert` / `check_intent` run `detect`:
1. **Retrieval** — hybrid: pgvector cosine (`<=>`) + Postgres FTS
   (`websearch_to_tsquery`), fused by Reciprocal Rank Fusion (RRF, k=60), filtered by
   overlapping scope tags.
2. **LLM judge** — per candidate, an `instructor`-structured `Judgment`
   (relation, confidence, explanation, evidence) via litellm. Cached in
   `judgment_cache` keyed by (model, subject, candidate).
3. **Gates** — relation must be a hard relation at/above the confidence threshold,
   AND the evidence must be a verbatim substring of the candidate (evidence-or-silence).
On `record_decision`, detection runs inside a **savepoint** so a detection DB error
degrades detection only; the decision write still commits (fail open). Propagation
runs in the outer transaction, durable with the decision.

Duplicates are informational and are not returned as actionable conflicts.
Supersession suggestions remain visible through MCP but do not trigger an edit
denial. Only a cited contradiction can trigger the optional PreToolUse warning.

`resolve_conflict` requires the existing decision's owner and a human explanation.
Its `outcome` defaults to `keep_existing`, which rejects a distinct conflicting
new decision. `accept_new` requires a recorded new decision and supersedes the
existing decision with it. A planned action cannot be promoted by resolution.
The operation locks the conflict and affected scopes/decisions, refuses closed or
stale conflicts, updates effective decisions, acknowledges that conflict's alerts,
and propagates a change to affected sessions in one transaction. The event records
the outcome and kept/retired IDs; no schema migration is needed.

### Hot path vs cold path
- **Cold path** — `record_decision` / `check_intent` run the full LLM pipeline (seconds).
- **Hot path** — the PreToolUse hook screens an edit with a deterministic, DB-only
  check (`get_context`: does the scope carry active decisions?) and escalates to the
  LLM only on a hit, keeping the common edit imperceptible.

## Propagation, alerts & delivery
- On a recorded decision: `change` alerts to participants with an overlapping active
  claim or a dependency (author's own session excluded; their *other* sessions
  included). On a detected conflict: `conflict` alerts to the candidate owner's
  sessions.
- **Piggyback delivery** — every tool response carries an `inbox`
  (`{alerts, handoffs, new_lessons}`); the light tier receives updates on any call.
- **Deny-once** — the only mid-task channel is a hook denial carrying a reason
  (PreToolUse `permissionDecision: deny`). Externally: "before the next action."
- **Drift (remediation)** — `report_activity` (and the PostToolUse hook) records work
  after it happens, triages it (none/possible/conflict), and leaves a self `change`
  alert to re-check.

## LLM providers
The judge uses litellm + instructor, so the model is a config switch
(`KEEL_LLM_PROVIDER` / `KEEL_LLM_MODEL`):
- **Google AI:** `gemini/gemini-2.0-flash` (AI Studio, `GEMINI_API_KEY`) or
  `vertex_ai/*` (Vertex AI on GCP, ADC — no key). Gemma via Vertex.
- Also Anthropic, OpenAI, and OpenAI-compatible endpoints. `none` disables detection
  (used by the test suite). Embeddings default to a deterministic offline embedder
  (retrieval still works via FTS + pgvector), so there is no provider dimension coupling.
- **Model router (optional).** Set `KEEL_LLM_MODEL_CHEAP` to route each candidate
  judgment to a cheap model, escalating to `KEEL_LLM_MODEL` only when it looks
  substantive — long combined text (> `KEEL_ROUTER_COMPLEXITY_CHARS`, default 600),
  more than two scope tags, or a change cue word (`replace`, `migrate`, `deprecate`,
  `switch`, …). Heuristic and deterministic, so the judgment cache keys on the routed
  model. Unset → routing off (always `KEEL_LLM_MODEL`).

## Identity, tokens & agent onboarding (keel/connect/, adapters/connect/)
Two bearer paths authenticate a call, both `sha256`-hashed at rest:
- **Legacy person token** — a `person.token_hash` seeded at setup; scope `full`.
- **`token` table** — per-person or per-agent tokens with a `scope` (`full` or
  `read_only`) and a `revoked_at`. A `read_only` token is refused by the write
  tools (`authz.require_write`); read tools and `/api/*` GET still work. Revoked
  tokens are rejected at auth.

**Connect flow (device-code, RFC 8628-shaped)** lets a human bring an agent online
without hand-seeding SQL:
1. The `keel_connect` CLI calls `POST /connect/device` (unauthenticated) and shows
   the returned `user_code` + verification URL.
2. The human opens `/connect`, signs in with Google (Firebase ID token verified
   against Google's public certs), enters the code, and approves — `POST
   /connect/approve` mints a scoped **agent token** for that person.
3. The CLI polls `POST /connect/token`; on approval it receives the token once and
   writes the harness config. Device codes and agent tokens are stored hashed; the
   plaintext agent token is returned exactly once (a process-local one-shot store),
   so a human re-approves if the server restarts before the claim. Poll abuse is
   bounded by `slow_down`, a TTL, and a one-shot claim.

A first-time Google identity with no matching person is attached to
`KEEL_DEFAULT_PROJECT_ID` if set, otherwise approval is refused. Firebase config is
optional: unset, `/connect/approve` returns 503 and legacy token auth is unaffected.
Tokens are listed/revoked via `GET /api/tokens` and `POST /api/tokens/{id}/revoke`.
The `keel_connect` CLI ships Claude Code and generic-MCP recipes; the token lands in
a gitignored `.keel.env`, never in tracked config.

## Claude Code adapter (adapters/claude-code/)
Fail-open bash hooks that curl the MCP endpoint:
- `session_start.sh` — register the session + inject active decisions/inbox.
- `user_prompt_submit.sh` — inject the pending inbox before each prompt.
- `pre_tool_use.sh` — deterministic scope screen → `check_intent` → deny-once.
- `post_tool_use.sh` — `report_activity` → inject a re-check note on drift.
Plus `settings.hooks.json`, `.mcp.json`, `.keel/scopes.example.json`, and a `SKILL.md`.
A harness-agnostic skill lives in `adapters/agent-skill/`.

## Deployment (deploy/cloudrun/)
Runs on **Google Cloud Run** backed by **Cloud SQL for PostgreSQL 16 + pgvector**, with
the Gemini key in **Secret Manager**. `./deploy/cloudrun/deploy.sh` is one command; the
schema is applied on first boot (`ensure_schema`). The static dashboard can be served on
Firebase Hosting or any static host. See [deploy/cloudrun/README.md](deploy/cloudrun/README.md).

## Testing
~170 hermetic tests (autouse `KEEL_LLM_PROVIDER=none`, function-scoped Postgres
fixtures). Gated live-LLM tests run against any provider key and assert an eval floor
(f1 ≥ 0.7). Hook tests boot the real server as a subprocess and feed recorded hook JSON.
