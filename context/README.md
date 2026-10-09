# Keel (working name)

> Every AI-native company needs a brain. Keel keeps it consistent.
>
> One living source of intent that every person's AI agent builds from — and that flags when anyone drifts.

**Status:** v1.0 (final draft for team review) for team review · **Date:** 2026-10-05 · **Name:** placeholder, see `OPEN_QUESTIONS.md`

---

## The problem in one paragraph

AI agents have made *building* cheap and fast for individuals and small teams. *Coordinating* has not gotten faster. Every person on a project now works through one or more agents (Claude Code, Cursor, ChatGPT, Copilot, and others), and every agent session holds its own private context. Decisions made in one session never reach the next session, the teammate's agent, or the PM's spec. The result is silent drift: duplicated work, contradictory assumptions, and rework discovered late. The bottleneck has moved from writing code to keeping intent aligned.

## What Keel is

An open-source, vendor-neutral **intent and decision ledger** for teams and their agents.

- **Captures decisions as they are made**, directly from agent sessions over MCP.
- **Detects contradictions** between a new decision or planned action and the team's active decisions.
- **Pushes changes to affected agents and people**, so drift is caught before it ships.
- **Catches silent drift** from what agents *do* (edits, commits, tool calls), not only from what they report.
- **Works at every scope:** two sessions of the same person (intra-harness), teammates on the same tool, different tools, and eventually different roles (PM, design, sales, legal).

## Where Keel fits in multiplayer AI

AI work is going multiplayer: teams will share live agent sessions to watch, redirect, and hand off work. Live sessions solve collaboration *inside* one session. Teams will still run many sessions across tools and functions, and nothing keeps those sessions consistent *with each other*. Google Docs won because everyone worked on one shared document, not because of live cursors. **Keel is the shared source of truth underneath multiplayer AI:** neutral across harnesses, with first-class handoff between people and sessions.

## What Keel is not

- Not another memory store. It can sit on top of one (Mem0, Postgres, or a knowledge-graph store).
- Not a wiki or knowledge-base hygiene tool. It works on live agent work, not published documents.
- Not a coding-agent orchestrator or file-lock tool. It operates on *intent*, not files.
- Not a live shared-session runtime. Harness vendors are best placed to build that; Keel works across all of them.
- Not an agent workspace, IDE, or fleet orchestrator (e.g., HumanLayer, Orchestrator.inc). Keel is a layer those tools can plug into: they run the work; Keel keeps intent consistent across people, tasks, and tools.

## Analogy

Spec-driven development made the spec the source of truth for code. Keel extends that idea to the whole project and every role's agent. Git versions code; Keel versions intent.

Coding agents reached production first because compilers and tests give them automatic feedback. Knowledge work has no compiler. **Keel acts as the compiler for team intent:** it checks every new decision and planned action against what the team has already agreed, and learns from outcomes which decisions drift.

## Documents in this folder

| File | Purpose |
|---|---|
| `PRD.md` | Product requirements: users, primitives, functional and non-functional requirements |
| `BUSINESS.md` | Business perspective: market, landscape, positioning, open-core model, risks |
| `ARCHITECTURE.md` | System design, data model, MCP tools, Claude Code hooks, conflict pipeline |
| `HACKATHON_PLAN.md` | Demo scope, script, task split, judging alignment |
| `OPEN_QUESTIONS.md` | Decisions the team needs to make; please add gaps here |

## How to review

Add comments inline or append to `OPEN_QUESTIONS.md`. Mark anything you disagree with as `[CHALLENGE]` and anything missing as `[GAP]`.