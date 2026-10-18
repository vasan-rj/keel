# Keel

**The shared source of truth underneath multiplayer AI.** An open-source, vendor-neutral **intent & decision ledger** for teams and their AI agents — it captures decisions from agent sessions over MCP, detects contradictions with active decisions, and propagates changes to the sessions and people affected *before the next action*.

<p>
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-blue">
  <img alt="Built on MCP" src="https://img.shields.io/badge/protocol-MCP%20(streamable%20HTTP)-5A45FF">
  <img alt="Postgres 16 + pgvector" src="https://img.shields.io/badge/store-Postgres%2016%20%2B%20pgvector-336791">
  <img alt="License: Apache-2.0 (proposed)" src="https://img.shields.io/badge/license-Apache--2.0%20(proposed)-lightgrey">
  <img alt="Status: pre-v1" src="https://img.shields.io/badge/status-pre--v1%20%2F%20hackathon-orange">
</p>

---

## The problem

AI agents made *building* cheap. *Coordinating* did not get faster. Every person on a project now works through one or more agents (Claude Code, Cursor, ChatGPT, Copilot), and every session holds its own private context. A decision made in one session never reaches the next session, the teammate's agent, or the PM's spec. The result is **silent drift** — duplicated work, contradictory assumptions, rework found late. The bottleneck moved from writing code to keeping intent aligned.

Coding agents reached production first because compilers and tests give automatic feedback. Knowledge work has no compiler. **Keel is the compiler for team intent:** it checks every new decision and planned action against what the team already agreed, and learns from outcomes which decisions drift.

## What it does

- **Captures decisions as they are made** — directly from agent sessions over MCP (`record_decision`).
- **Detects contradictions** between a new decision (or a planned action) and the team's active decisions, with an **evidence-or-silence** rule: no conflict is emitted without quoting the decision it conflicts with.
- **Propagates changes** to affected sessions and people, including the author's *other* sessions (the intra-person beat).
- **Catches drift from what agents** ***do*** (edits, commits, tool calls via Claude Code hooks), not only what they report.
- **Works across scopes** — two sessions of one person, teammates on the same tool, different tools, and eventually different roles.

## What it is not

- Not a general-purpose memory store (it can sit on top of one).
- Not a wiki / KB-hygiene tool — it works on live agent work, not published docs.
- Not a file-lock, merge-conflict, or coding-agent orchestrator — it operates on *intent*, not files.
- Not a live shared-session runtime, and it never auto-overwrites a decision or code. **Humans resolve; Keel flags.**

## How it works

Decisions and lessons are the same append-only row (`proposed → active → superseded/rejected`). **Scope tags** (`api:orders`, `schema:user`) are the primary filter everywhere — conflict candidates, claims, propagation targets, handoffs. Two integration tiers share one server and data model: a **deep tier** (Claude Code hooks, guaranteed delivery) and a **light tier** (web apps as remote MCP connectors, best-effort via a **piggyback inbox** — every tool response carries pending alerts, handoffs, and new lessons).

```mermaid
flowchart LR
  A[Agent session] -- record_decision / check_intent --> K[Keel MCP server]
  K --> P[Conflict pipeline\nscope → retrieval → deterministic → LLM judge → evidence gate]
  P -- active decision --> L[(Ledger\nPostgres + pgvector)]
  P -- conflict / change --> PR[Propagation\ndependency + claim]
  PR -- piggyback inbox --> B[Affected sessions & people]
```

The conflict check runs **transactionally with the insert, serialized per scope tag** — concurrent records on one scope otherwise both pass and produce two contradictory active decisions. Design principles (harness-agnostic core, determinism where cheap, **fail open**, append-only hash chain) live in the architecture doc, §1.

## MCP tools

| Tool | Purpose |
|---|---|
| `register_session` | Register a session (harness, tier, session id) against a principal. |
| `get_context` | Fetch active decisions for given scope tags. |
| `record_decision` | Record a decision/lesson; runs the conflict pipeline on insert. |
| `check_intent` | Check a *planned* action against active decisions (warns, never blocks). |
| `declare_dependency` | Mark a session as dependent on a decision (drives propagation). |
| `claim_scope` / `release_scope` | Claim/release overlapping scope with a TTL. |
| `list_alerts` / `ack_alert` | Read and acknowledge pending alerts. |
| `resolve_conflict` | Record a human resolution for a conflict. |
| `create_handoff` / `accept_handoff` / `decline_handoff` | Receiver-only transfer of scope between people. |

Every response also carries the piggyback `inbox` block.

## Quickstart (dev)

```bash
docker compose up -d db          # Postgres 16 + pgvector on host port 5433
pip install -e ".[dev]"          # or: uv pip install -e ".[dev]"
cp .env.example .env
python -m keel.scripts.seed
python -m keel.server            # MCP streamable HTTP on :8000 (route /mcp)
```

Optional extras: `pip install -e ".[llm]"` for real-LLM judging (needs `ANTHROPIC_API_KEY`). Key env vars: `DATABASE_URL`, `KEEL_LLM_MODEL`, `KEEL_EMBEDDING_PROVIDER`, `KEEL_CONFLICT_CONFIDENCE_THRESHOLD` (see [`config.py`](keel/config.py)).

## Test

```bash
docker compose up -d db          # must be running; creates keel + keel_test
export KEEL_TEST_DATABASE_URL=postgresql://keel:keel@localhost:5433/keel_test
pytest                           # LLM-live tests are marked; skipped without a key
```

### Two-session smoke test

1. `python -m keel.server` (listens on :8000, MCP at `/mcp`).
2. Session A (token `dev-token`, header `X-Keel-Session: A`): `register_session` → `record_decision`
   `{statement: "orders API uses cursor pagination", rationale: "...", scope_tags: ["api:orders"]}`.
3. Session B (token `teammate-token`, `X-Keel-Session: B`): `register_session` → `get_context`
   `{scope_tags: ["api:orders"]}` returns A's decision. Cross-session fetch confirmed.

## Project layout

```
keel/
├── keel/
│   ├── server.py            # MCP server + tool registry
│   ├── tools/               # one module per MCP tool
│   ├── conflict/            # pipeline, retrieval, judge, cache
│   ├── propagation.py       # dependency + claim → who gets alerted
│   ├── inbox.py             # piggyback delivery block
│   ├── repo.py / events.py  # append-only ledger + hash chain
│   └── db/schema.sql        # Postgres + pgvector schema
├── tests/                   # pytest suite (unit + pipeline + transport)
├── docker-compose.yml       # db + api
└── pyproject.toml
```

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) — components, data model, conflict pipeline, delivery, providers, deploy.
- [adapters/agent-skill/SKILL.md](adapters/agent-skill/SKILL.md) — how any MCP agent uses the 17 tools.
- [deploy/cloudrun/README.md](deploy/cloudrun/README.md) — deploy on Google Cloud Run (Gemini + Cloud SQL/pgvector).
- [BACKLOG.md](BACKLOG.md) — roadmap as issue-ready items.
- [CONTRIBUTING.md](CONTRIBUTING.md) · [SECURITY.md](SECURITY.md) · [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

(The longer design docs — `PRD`, `BUSINESS`, `HACKATHON_PLAN`, `OPEN_QUESTIONS` — are kept alongside the repo, outside the published tree.)

## Status & roadmap

Pre-v1. Implemented: the MCP server with **17 tools**, the hybrid conflict pipeline
(retrieval → LLM judge → evidence gate, validated on a real LLM), propagation/alerts,
handoff, the Claude Code adapter (SessionStart / UserPromptSubmit / PreToolUse
deny-once / PostToolUse drift), a read-only dashboard, and a Cloud Run deploy — with a
~170-test pytest suite. Next steps and open items are tracked in [BACKLOG.md](BACKLOG.md),
gated **P0 / P1 / P2**.

## Where Keel fits

AI work is going multiplayer. Live shared sessions solve collaboration *inside* one session; teams still run many sessions across tools and roles, and nothing keeps those consistent *with each other*. Agent workspaces and fleet orchestrators (e.g. HumanLayer, Orchestrator.inc, both neutral and factual references) run and supervise the work. **Keel is a layer those tools plug into:** they run the work; Keel keeps intent consistent across people, tasks, and tools. Git versions code; Keel versions intent.

## License

[Apache-2.0](LICENSE). ("Keel" is the project's confirmed working name — see
`OPEN_QUESTIONS` #1.)
