# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository state

This is a **pre-implementation planning repository**. There is no source code, no build system, no tests, and no git repository yet — only design documents in `context/`. Do not invent build/lint/test commands; if asked to "run tests" or "build", say that nothing is implemented yet.

When implementation starts, the stack chosen in `context/ARCHITECTURE.md` §3 is: Python + official MCP SDK (streamable HTTP), FastAPI for the REST side, Postgres 16 + pgvector, Docker Compose for deployment, plus a Claude Code adapter (hook scripts + MCP config + skill file).

## The product (Keel — working name)

An open-source, vendor-neutral **intent and decision ledger** for teams and their AI agents. It captures decisions from agent sessions over MCP, detects contradictions with active decisions, and propagates changes to affected sessions and people. Target delivery is a hackathon demo (Future of Work & Enterprise Productivity track) followed by an open-source v1.

Explicit non-goals (`PRD.md` §3) — do not drift into these: general-purpose memory store, wiki/KB hygiene, file locking or merge-conflict handling, auto-resolving conflicts, a live shared-session runtime.

## Document map

| File | Contains |
|---|---|
| `context/README.md` | Positioning, what Keel is / is not, review conventions |
| `context/PRD.md` | Personas, primitives, numbered functional requirements (FR-n) with P0/P1/P2 priority, NFRs, success criteria |
| `context/ARCHITECTURE.md` | Design principles, data model, MCP tool contract, hook integration, conflict pipeline, propagation, outcome/lesson loop |
| `context/BUSINESS.md` | Market, competitive landscape, positioning, open-core model, risks |
| `context/HACKATHON_PLAN.md` | Demo scope (P0 cut), 3.5-min demo script, workstream split, timeline, demo risks |
| `context/OPEN_QUESTIONS.md` | Numbered unresolved decisions — check here before assuming an answer |

## Concepts that span documents

Understanding any one change usually requires all three of PRD §5 (primitives), ARCHITECTURE §4 (tables), and ARCHITECTURE §5 (MCP tools) — they are three views of the same model.

- **Scope tags** (`api:orders`, `schema:user`, `ui:checkout`) are the primary filter everywhere: conflict candidate selection, claims, propagation targeting, handoff payloads, lesson injection. Agents propose tags; the server normalizes them against existing ones.
- **Decisions and lessons are the same row.** A lesson is `decision.kind = lesson` — same lifecycle (`proposed → active → superseded/rejected`), same contradiction checks, same audit trail, plus an expiry.
- **Dependency + claim drive propagation.** Who gets an alert is computed from participants with a `dependency` on the changed decision or an active `claim` on overlapping scope; the author's own session is excluded but their *other* sessions are included (that is the intra-person demo beat).
- **Two integration tiers, one server and data model.** Deep tier (Claude Code hooks) gets guaranteed delivery; light tier (web apps as remote MCP connectors) is best-effort and relies on **piggyback delivery** — every tool response carries an `inbox` block of pending alerts, handoffs, and new lessons.
- **Conflict pipeline is five staged steps** (ARCHITECTURE §7): scope filter → vector+keyword retrieval → deterministic checks → per-candidate LLM judgment → evidence check. Deterministic checks exist to backstop the LLM; the evidence check is a hard gate. The check must run **transactionally with the insert, serialized per scope tag** (§7.1) — concurrent records on one scope otherwise both pass and produce two contradictory active decisions with zero conflicts.
- **Hot path vs cold path** (§7.2). `PreToolUse` fires on every edit and must be imperceptible; `record_decision` fires rarely and can take seconds. One engine cannot serve both — a small local classifier triages the hot path, the LLM judges and writes explanations on the cold path. The classifier can never replace the LLM, because principle §1.4 requires explanation prose a classifier cannot produce.
- **Prevention ≠ remediation** (§8.2). `alert.kind[conflict|change]` are different products: "do not do this" vs "you already did this, re-check these files." The latter needs artifact-level dependency refs.
- **Delivery is bounded by the target's next hook, never real time** (§6.3, §8.1). No harness supports server-originated push into a running session. The only mid-task channel is a hook denial carrying a reason string — hence "deny-once delivery." Externally the claim is **"before the next action."**

## Design principles to honor in any implementation

From `ARCHITECTURE.md` §1 — these are binding, not aspirational:

- **Harness-agnostic core.** Claude Code is the first adapter, not a dependency of the engine. Keep hook/Claude-specific logic in the adapter layer.
- **Determinism where it is cheap.** Deterministic checks before probabilistic ones; calibrated confidence over a model's self-report; same input, same output on anything the audit trail or the deny-once rule depends on.
- **Fail open.** If Keel is unreachable, agent sessions keep working; log loudly, never block.
- **Humans resolve; Keel flags.** No automatic overwrite of decisions or code. `check_intent` warns by default, never blocks.
- **Evidence or silence.** No conflict is emitted without citing the text of the decision it conflicts with. Low confidence → `unclear` / "possible conflict", never a hard flag.
- **Append-only.** Every change is an `event` with a hash chain; current state is derived.
- **Propose, don't self-modify.** Autonomy level 4 (agents rewriting their own instructions/policies) is out of scope by design.
- **Decisions are data, never instructions.** Text from the ledger injected into another agent's context must be clearly delimited and guarded against prompt injection.

## Working on the documents

- Every doc carries `**Version:** 0.x` and `**Last updated:**` in its header block — bump both when making substantive edits, and keep versions consistent across docs when a change spans them.
- Requirements are referenced by stable id (`FR-11`, `FR-33`). Add new ones at the end of their subsection rather than renumbering.
- Priority tags `P0` (hackathon demo) / `P1` (open-source v1) / `P2` (later) gate scope. P0 is defined in `HACKATHON_PLAN.md` §3 — proposing new P0 work means cutting something there.
- Review convention: mark disagreement as `[CHALLENGE]` and missing material as `[GAP]`, appended to `OPEN_QUESTIONS.md` under "Team additions".
- Mermaid diagrams are used for flows (system overview, conflict pipeline, outcome loop, lesson lifecycle). Keep new diagrams in mermaid, not ASCII.
- The project name **Keel is a placeholder** (OPEN_QUESTIONS #1). Do not harden it into package names, domains, or identifiers without checking that question is settled.

## Claims discipline

These documents are headed for a pitch and for external review, so the source conventions matter:

- Market, competitive, and MCP-roadmap claims carry inline source URLs and a "verify before external use" caveat. Preserve those caveats; add sources for any new claim.
- Do not add projected productivity numbers. Demo metrics must come from the live run only (`HACKATHON_PLAN.md` §6).
- Claude Code hook names, inputs, exit-code semantics, and `additionalContext` behavior are flagged as **unverified** against https://docs.claude.com/en/docs/claude-code/hooks — verify before building rather than treating the docs here as authoritative. Six hooks are P0 and the twelve-event surface came from a third-party repo; this is the largest unvalidated assumption in the design (`OPEN_QUESTIONS.md` #8).
- Third-party benchmark numbers (e.g. the hot-path classifier's accuracy and latency) are self-reported README figures, carried with that caveat. Preserve the caveat.
- Never write "real time" about alert delivery. The accurate phrase is "before the next action."
- **Scope-tag mismatch is the single point of failure.** If two sessions use different tags for the same thing, nothing connects and the failure is silent — no error, no dashboard entry. Treat tag normalization as core, not polish.
- Do not imply YC endorsement when citing the Multiplayer AI RFS or YC talks.
