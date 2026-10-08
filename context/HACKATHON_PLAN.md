# Hackathon Plan — Keel (working name)

**Track:** Future of Work & Enterprise Productivity · **Version:** 1.0 · **Last updated:** 2026-10-05

---

## 1. Demo setup

One harness (Claude Code), three agent instances, two people:

| Participant | Person | Role in demo |
|---|---|---|
| Session A1 | Vasan | Makes the original decision |
| Session A2 | Vasan | Parallel session that drifts (intra-person conflict) |
| Session B1 | Teammate | Different machine; receives the change and adapts (inter-person propagation) |

All three connect to one shared Keel server over MCP, with Claude Code hooks installed.

## 2. Demo script (~3.5 minutes)

| Time | Beat | What the audience sees |
|---|---|---|
| 0:00 | **Problem** | "Every agent session is an island. Here are three of them on one project." |
| 0:20 | **Decision** | A1 decides the orders API uses cursor-based pagination; records it. Dashboard shows the new active decision. |
| 0:50 | **Silent drift catch** | A2, working on another module, writes offset pagination without telling Keel anything. The edit hook reports the change; on A2's next turn Keel flags the conflict with A1's decision, owner, and rationale. A1 (the owner) is alerted too. A2 adapts. |
| 1:30 | **Inter-person propagation** | A1 changes the page size default (supersedes). B1, building the frontend, gets an alert on its next prompt and updates its code. |
| 2:15 | **Handoff** | A1 hands the checkout scope to the teammate. B1 picks it up on its next prompt with the decisions, open conflict, and claim attached, and continues without a briefing. |
| 2:45 | **Trail** | Dashboard: decision history, conflict, alert, acknowledgement, handoff, timestamps. |
| 3:05 | **Vision** | AI is going multiplayer; multiplayer needs a shared source of truth. Same engine extends to other harnesses (Cursor, Codex) and other roles (Notion specs, Figma designs, Slack, CRM). Open source; enterprise edition later. |

**Backup plan:** record a clean run of the full demo in advance in case of network or model issues on stage.

## 3. Scope

**In (P0):**
- Keel server: MCP tools `register_session`, `get_context`, `record_decision`, `check_intent`, `declare_dependency`, `list_alerts`, `ack_alert`, `resolve_conflict`, `create_handoff`, `accept_handoff`.
- Conflict engine: scope filter + retrieval + LLM judgment with evidence.
- Propagation: dependency- and claim-based alerts.
- Claude Code adapter: `SessionStart`, `UserPromptSubmit`, and post-edit hooks, MCP config, skill instructions.
- Silent drift: `report_activity` from the edit hook, scope matching, async check (with a deterministic rule for the pagination key as backup).
- Dashboard: decisions, conflicts, alerts, timeline.

**Stretch goals (only after three clean runs of the core demo):**
1. **Lesson beat (~20s, after the intra-person catch):** Keel drafts a lesson from the resolved pagination conflict ("pagination decisions in `api:orders` affect frontend sessions; check intent before changing"). You approve it; a fresh session in that scope starts with it.
2. **PM in claude.ai (~20s, before the vision slide):** a third participant in claude.ai, connected via a custom connector, records a product decision (e.g., "checkout must support guest users"). The teammate's Claude Code session picks it up on its next prompt. Requires the public HTTPS server and OAuth.

**Out (say it on the roadmap slide instead):**
- Other harnesses, Slack/Notion/Figma/HubSpot adapters, SSO, automatic decision extraction, enterprise features.

## 4. Task split (proposal)

| Workstream | Owner | Deliverable |
|---|---|---|
| Server, data model, MCP tools | TBD | Tools working end to end against Postgres |
| Conflict engine + prompt + small eval set | TBD | Correct flags on the demo scenarios plus 10–20 labeled pairs |
| Claude Code adapter (hooks, skill, install script) | TBD | One-command setup on both laptops |
| Dashboard | TBD | Live view used in the demo |
| Demo app (small orders API + frontend) and script | TBD | Realistic codebase for the agents to work on |
| Pitch deck and recorded backup | TBD | Slides and video |

## 5. Timeline (adjust to event length)

| Phase | Share of time | Exit criteria |
|---|---|---|
| Setup and skeleton | ~15% | Server runs; both laptops connect via MCP |
| Core tools and data model | ~25% | Record and fetch decisions across sessions |
| Conflict engine | ~20% | Demo conflict flagged reliably |
| Hooks and propagation | ~20% | Alert reaches B1 on next prompt; edit-hook drift caught in A2 |
| Dashboard and polish | ~10% | Trail visible end to end |
| Rehearsal and backup recording | ~10% | Three clean full runs |

## 6. Judging alignment

| Theme criterion | How the demo shows it |
|---|---|
| **Productivity** | Rework avoided: drift caught on the first edit, not at review |
| **Knowledge accessibility** | Every session starts with the team's current decisions |
| **Decision-making** | Decisions have owners, rationale, status, and history |
| **Workflow execution** | Changes propagate to dependent agents without meetings or Slack threads; work is handed off with full context |
| **Collaboration** | Multiple people and sessions work from one shared source of truth (multiplayer) |
| **Continuous improvement** (stretch) | A resolved failure becomes an approved lesson that the next session starts with |
| **Reach beyond developers** (stretch) | A PM in claude.ai and developers in Claude Code share the same decisions |

Use numbers from the live run only (e.g., seconds from change to acknowledgement). Do not quote projected productivity gains.

## 7. Demo risks

| Risk | Mitigation |
|---|---|
| LLM misjudges the demo conflict | Tune on the exact scenario; deterministic check as backup for the pagination key |
| Network issues between laptops | Hosted server plus phone hotspot; recorded backup |
| Hooks behave differently than expected | Spike hooks first, in the setup phase |
| Agent doesn't call `record_decision` | Explicit skill instructions; fall back to prompting it on stage |
| OAuth setup for claude.ai fails or takes too long | Time-box to a fixed slot; drop the stretch goal and show it on the vision slide |
| Drafted lesson reads poorly live | Pre-test the lesson prompt on the exact scenario; owner can edit before approving |

## 8. Judge Q&A prep

| Likely question | Answer |
|---|---|
| How is this different from HumanLayer? | HumanLayer is a multiplayer workspace for coding tasks: you move your work into it. Keel is an open-source layer that keeps decisions consistent across tasks, people, tools, and roles, and catches contradictions between them. They can work together. |
| How is this different from Orchestrator.inc or other agent orchestrators? | An orchestrator coordinates one supervisor's fleet. Keel keeps intent consistent between different people's fleets and non-coding roles. We plan an Orchestrator.inc plugin. |
| Isn't this just shared memory? | Memory stores and recalls. Keel detects contradictions, propagates changes to the right sessions, and tracks owners and outcomes. |
| What if the agent never calls Keel? | Silent-drift detection: edit hooks, end-of-turn capture, PR checks, and later gateway and Slack signals. |
| Won't it be noisy? | Scope filter first, evidence on every alert, "possible drift" tier, and alert precision tracked as a core metric. |
| Is the "self-improving" claim real? | Lessons are drafted from real failures, approved by humans, and judged by recurrence rate. No unreviewed self-modification. |