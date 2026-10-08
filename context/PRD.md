# Product Requirements — Keel (working name)

**Version:** 1.0 (final draft for team review) · **Owner:** TBD · **Last updated:** 2026-10-05

---

## 1. Problem statement

Teams that use AI agents heavily lose time *between* agents, not within them.

| Scope | Example of drift |
|---|---|
| Same person, parallel sessions | Session 1 decides on cursor pagination; session 2 writes offset pagination. |
| Same person, over time | Yesterday's decision is lost after a session ends or context is compacted. |
| Teammates, same tool | Two developers on Claude Code hold contradictory assumptions about an API contract. |
| Teammates, different tools | A Cursor user and a Claude Code user build against different versions of a schema. |
| Silent drift | A session changes an assumption in code without ever stating it as a decision; nobody is told. This is the most common case. |
| Autonomous agents | An internal agent (sales, support, procurement) acts on an outdated decision with no clear human owner. |
| Different roles (roadmap) | Sales promises a feature that is not in the PM spec; design changes a flow and marketing copy goes stale. |

Today this is resolved through meetings, Slack threads, and late-stage rework. Agents make it worse because they act confidently on whatever context they have.

## 2. Goals

1. Make the team's **current intent** (active decisions, contracts, constraints, owners) available to every agent session at start and during work.
2. **Detect contradictions** between new decisions or planned actions and active decisions, with evidence.
3. **Propagate changes** to the sessions and people who depend on a decision.
4. Be **harness-agnostic and open source**, with Claude Code as the first adapter.
5. Keep humans in control: Keel flags and routes; owners resolve.
6. **Make handoff first-class:** a person or session can hand a scope to another person's session with full context attached.
7. **Close the loop:** learn from decision outcomes (held, reversed, caused rework) so the system improves over time.
8. **Prevent repeat failures:** turn past failures into human-approved lessons that future sessions start with.
9. **Reach every role:** support AI web apps (Claude, ChatGPT, Gemini, Copilot) as a light integration tier, alongside deep harness integrations.
10. **Catch silent drift:** detect drift from what agents do (edits, commits, tool calls, Slack threads), not only from what they report.
11. **Treat agents as first-class participants:** autonomous agents get their own identity and a human sponsor for accountability.

## 3. Non-goals (v1)

- Replacing Jira, Linear, Notion, or Confluence.
- Storing full chat transcripts or general-purpose memory.
- Auto-resolving conflicts or editing code on its own.
- File locking or merge-conflict handling (existing tools cover this).
- Non-developer role integrations (roadmap, not v1).
- Agents rewriting their own instructions or policies without human approval.
- Live shared agent sessions (multiple humans in one running session). Keel integrates with harnesses that offer this rather than building its own runtime.

## 4. Users and personas

| Persona | Need | Phase |
|---|---|---|
| **Solo AI builder** running parallel agent sessions | Sessions stay consistent with each other and with past decisions | v1 (single-player hook) |
| **Small dev team** (2–10) using coding agents | Teammates' agents share one source of intent; drift is flagged | v1 |
| **Cross-functional startup team** (PM, design, eng, sales) | Decisions in specs, designs, and CRM stay consistent with what is being built | v2 |
| **Teams running autonomous internal agents** (sales, support, procurement) | Agents act on current decisions; every agent action is attributable to a sponsor | v2 |
| **Users of agent workspaces and orchestrators** (HumanLayer, Orchestrator.inc, IDEs) | Consistency across tasks and people that their workspace doesn't track | v1 via adapters |
| **Enterprise platform / engineering leadership** | Governed, auditable, permissioned intent layer across many teams and tools | Enterprise edition |

## 5. Core concepts (primitives)

| Primitive | Definition | Key fields |
|---|---|---|
| **Project** | Unit of shared intent (not tied to one repo) | id, name, members |
| **Participant** | An agent instance acting for a person, or an autonomous agent with its own identity | principal type (person session / agent), person or sponsor, harness, tier, session_id, status |
| **Goal** | The shared end outcome a group of sessions works toward | statement, owner, linked scopes, linked participants |
| **Decision category** | What kind of intent a decision captures | product, architecture, contract, policy, lesson |
| **Drift signal** | An observed action (edit, commit, tool call, thread message) that may conflict with intent | source, participant, scope, summary, confidence |
| **Decision request** | An agent asks a scope owner to decide instead of guessing | question, options, scope, requester, owner, status |
| **Decision** | A statement of intent the team should act on | statement, rationale, scope tags, owner, status, source session, supersedes |
| **Decision status** | Lifecycle | `proposed` → `active` → `superseded` / `rejected` |
| **Dependency** | A participant or artifact relies on a decision | decision_id, dependent (participant/artifact), created_by |
| **Claim** | A participant is working in a scope | scope, participant, expires_at |
| **Conflict** | Detected contradiction with evidence | decision_a, decision_or_action_b, type, severity, evidence, status |
| **Alert** | Notification to an affected participant or person | target, conflict_or_change, delivered_at, acknowledged_at |
| **Event** | Append-only record of every change | actor, action, payload, timestamp, hash |
| **Handoff** | Transfer of a scope from one participant to another person or session, with context attached | from, to, scope tags, decisions, open conflicts, claims, note, status |
| **Lesson** | A decision of kind `lesson`: what went wrong in a scope and what to do differently, derived from past failures | statement, scope tags, evidence refs (conflicts, outcomes), owner, status, expires_at |
| **Outcome** | What happened to a decision after it was made | decision_id, result (held / reversed / caused rework), evidence, recorded_by |

## 6. Functional requirements

Priority: **P0** = hackathon demo, **P1** = open-source v1, **P2** = later.

### 6.1 Session and identity
- **FR-1 (P0):** A session registers as a participant on start (person + harness + session id).
- **FR-2 (P0):** Participants authenticate with a project-scoped token.
- **FR-3 (P1):** Stale participants expire after inactivity.

### 6.2 Context injection
- **FR-4 (P0):** On session start, the agent receives the project's active decisions relevant to its scope.
- **FR-5 (P0):** On each user prompt, the agent receives any unacknowledged alerts.
- **FR-6 (P1):** Before context compaction, open decisions from the session are captured so they are not lost.

### 6.3 Decision capture
- **FR-7 (P0):** An agent can record a decision with statement, rationale, and scope tags via an MCP tool.
- **FR-8 (P0):** New decisions are `active` by default in a solo project and `proposed` when they touch a scope owned by someone else (configurable).
- **FR-9 (P1):** A decision can supersede another; the superseded decision keeps its history.
- **FR-10 (P2):** Suggested decisions are extracted automatically from session activity, for human confirmation.

### 6.4 Contradiction detection
- **FR-11 (P0):** Recording a decision triggers a check against active decisions in overlapping scope.
- **FR-12 (P0):** An agent can call `check_intent` with a planned action before acting and receive any conflicts.
- **FR-13 (P0):** Each conflict includes the conflicting decision, owner, rationale, and a short explanation.
- **FR-14 (P1):** Conflicts are classified: `contradicts`, `duplicates`, `supersedes`, `unclear`.
- **FR-15 (P1):** Deterministic checks run before the LLM check for structured fields (same key, different value).

### 6.5 Propagation and resolution
- **FR-16 (P0):** When a decision changes, alerts go to participants with a dependency or active claim in that scope.
- **FR-17 (P0):** The decision owner can resolve a conflict: keep, supersede, or reject.
- **FR-18 (P1):** Alerts can also go to Slack.
- **FR-19 (P1):** An agent acknowledges an alert after acting on it.

### 6.6 Visibility
- **FR-20 (P0):** A dashboard shows active decisions, open conflicts, participants, and the event timeline.
- **FR-21 (P1):** Full decision history with diffs and lineage.
- **FR-22 (P1):** Basic metrics: conflicts caught, time from change to acknowledgement, decisions per scope.

### 6.7 Handoff and live visibility (multiplayer)
- **FR-33 (P0):** A participant can hand off a scope to another person (or a specific session) via `create_handoff`, attaching the relevant active decisions, open conflicts, claims, and a note.
- **FR-34 (P0):** On the receiving person's next session start or prompt, the pending handoff is injected as context. Accepting it transfers the claim and declares dependencies on the attached decisions.
- **FR-35 (P0):** The handoff appears in the event timeline with sender, receiver, and what was transferred.
- **FR-36 (P1):** Live activity feed on the dashboard: which participants are active, in which scopes, against which decisions ("watch").
- **FR-37 (P1):** "Redirect": an owner superseding a decision is highlighted as a redirect to every running session in that scope.
- **FR-38 (P2):** Integrate with harnesses that support shared live sessions, so each shared session registers as one participant with multiple human members.

### 6.8 Outcome loop
- **FR-23 (P1):** A decision owner or agent can record an outcome: `held`, `reversed`, or `caused_rework`, with evidence (e.g., a PR or commit link).
- **FR-24 (P1):** Keel infers likely outcomes automatically: a superseded decision within N days is a candidate `reversed`; an acknowledged conflict followed by code changes is a candidate `caused_rework`. Owners confirm.
- **FR-25 (P1):** Drift analytics: which scopes and decision types are reversed or contradicted most often.
- **FR-26 (P2):** Keel uses outcome history to adjust behavior: raise severity in high-drift scopes, suggest review for decision types that are frequently reversed, and tune conflict thresholds per project.
- **FR-27 (P2):** Conflict-engine feedback: every dismissed or acknowledged alert becomes a labeled example for evaluating and improving the engine.

### 6.9 Lessons (self-improvement)
- **FR-39 (P1):** When a conflict is resolved, a decision is reversed, or rework is recorded, Keel drafts a candidate lesson with evidence links.
- **FR-40 (P1):** Lessons follow the decision lifecycle: `proposed` until an owner approves, then `active`; they can be superseded, are checked for contradictions, and carry an expiry date.
- **FR-41 (P1):** Active lessons in scope are injected at session start and returned by `get_context`, limited to the few most relevant (context budget).
- **FR-42 (P1):** Keel requires a minimum evidence count before drafting a lesson for a pattern (single-incident lessons only when an owner requests them).
- **FR-43 (P1):** Lesson effectiveness is tracked: recurrence of the same failure type in the same scope before vs. after the lesson became active.
- **FR-44 (P2):** Keel proposes process changes (e.g., require review in a high-drift scope, auto-link dependent sessions) for owner approval. Approved changes are versioned and reversible.
- **FR-45 (P0, stretch):** Demo version: draft a lesson from a resolved conflict, approve it, and inject it into a new session.

**Autonomy levels (product boundary):**

| Level | What Keel does | Human role | Phase |
|---|---|---|---|
| 1 | Tunes its own conflict checks and thresholds | Can override | P1 |
| 2 | Drafts lessons from failures; injects approved lessons | Approves each lesson | P1 |
| 3 | Proposes process and policy changes | Approves each change | P2 |
| 4 | Rewrites agent instructions or policies on its own | — | Not planned |

### 6.10 Silent drift detection
- **FR-53 (P0):** *Edit observation (deep tier):* after file edits, a hook sends a short change summary with file paths to Keel; Keel checks it asynchronously against active decisions in matching scopes. Alerts arrive on the next turn; the agent is never blocked.
- **FR-54 (P1):** *End-of-turn capture:* at the end of each turn, Keel extracts implicit decisions from what the session did ("switched to offset pagination") and checks them as drift signals.
- **FR-55 (P1):** *Commit / pull request check:* a CLI command and GitHub Action check diffs against active decisions (especially `architecture` and `contract` categories) and comment on the PR. Works for every tool, including ones without a Keel integration.
- **FR-56 (P2):** *Gateway observation:* an adapter for MCP gateways sends tool-call metadata to Keel as drift signals, so agents that never call Keel are still checked.
- **FR-57 (P1):** *Slack thread capture:* decisions stated in Slack threads (by people or agents) become proposed decisions for owner confirmation.
- **FR-58 (P0):** Drift signals are only checked when they touch scopes with active decisions; low-confidence findings are shown as "possible drift."
- **FR-59 (P1):** *Shared goal:* sessions can link to a project goal; drift signals and new decisions are also checked against the goal and its decisions.

### 6.11 Agent identity, plans, and decision requests
- **FR-60 (P1):** Autonomous agents register with their own identity, role, and a human sponsor. Decisions and actions by the agent are attributed to the agent and its sponsor.
- **FR-61 (P1):** Agent participants can be limited to scopes and decision categories (e.g., a support agent can propose but not activate product decisions).
- **FR-62 (P1):** *Plan-stage capture:* when an agent finalizes a plan (e.g., plan mode or a plan artifact), Keel extracts proposed decisions and checks them before implementation starts.
- **FR-63 (P1):** *Decision requests:* when `check_intent` returns `unclear`, or an agent faces a choice in a scope it doesn't own, it can call `request_decision`. The owner is notified (session, Slack, dashboard); the answer becomes a decision.
- **FR-64 (P2):** Workspace and orchestrator adapters (e.g., Orchestrator.inc plugins, other agent workspaces) pass Keel context to the workers they spawn and report worker activity as drift signals.

### 6.12 Integrations
- **FR-28 (P0):** Claude Code adapter (MCP server plus hooks).
- **FR-29 (P1):** Generic MCP adapter for Cursor, Codex, Copilot, and other MCP clients.
- **FR-30 (P1):** GitHub, Slack, and Notion adapters (ingest and notify).
- **FR-31 (P2):** Figma, HubSpot, Jira/Linear, Confluence, Google Docs.
- **FR-32 (P2):** Meeting-transcript and Slack ingestion that proposes candidate decisions for human confirmation (raw recordings in, structured decisions out).

**Integration tiers:**
- **FR-46 (P1):** *Deep tier:* harnesses with lifecycle hooks (Claude Code first) get guaranteed context injection, alert delivery, and pre-compaction capture.
- **FR-47 (P1):** *Light tier:* AI web apps connect to Keel as a remote MCP custom connector (Claude web/desktop/mobile, ChatGPT Developer Mode, Gemini Enterprise, Microsoft Copilot Studio, and others that support custom connectors).
- **FR-48 (P1):** Every Keel tool response includes pending alerts, handoffs, and relevant lessons ("piggyback delivery"), so light-tier clients receive them on any call.
- **FR-49 (P1):** Keel ships ready-to-paste project instructions per web app (Claude Projects, ChatGPT Projects/custom instructions, Gemini Gems) telling the model to call `get_context` first, `check_intent` before deciding, and `record_decision` after.
- **FR-50 (P1):** Light-tier participants are identified by OAuth user plus a conversation id issued by `register_session`.
- **FR-51 (P1):** People working in web apps can also receive alerts via Slack or email.
- **FR-52 (P0, stretch):** Demo version: one participant joins from claude.ai as a "PM" and records a product decision that the Claude Code sessions pick up.

## 7. Non-functional requirements

| Area | Requirement |
|---|---|
| **Latency** | `check_intent` returns fast enough not to interrupt agent flow. Target to be set after the first benchmark. |
| **Reliability** | If Keel is unreachable, agents continue working (fail open, but log loudly). |
| **Accuracy** | Every conflict shows evidence (the decision text and source). No conflict without a cited decision. |
| **False-positive control** | Severity threshold is configurable; low-confidence conflicts are shown as "possible" rather than blocking. |
| **Security** | Project-scoped tokens; no cross-project reads; secrets never stored in decisions. |
| **Privacy** | Keel stores decisions and metadata, not full transcripts. |
| **Auditability** | Append-only, hash-chained event log. |
| **Portability** | Self-hostable via Docker Compose; LLM provider is configurable. |
| **Extensibility** | Every integration is an adapter with two methods: `ingest` and `notify`. |
| **Context budget** | Injected context (decisions + lessons + alerts) stays within a configurable size; most relevant items first. |
| **Web reachability** | Light tier requires a public HTTPS endpoint with Streamable HTTP transport and OAuth; localhost-only deployments support the deep tier only. |
| **Tier transparency** | The dashboard shows each participant's tier, so teams know which sessions get guaranteed vs. best-effort delivery. |

## 8. Success criteria

**Hackathon (demo-measured, not projected):**
- Intra-person conflict detected between two sessions of the same person, including silent drift caught from an edit.
- Inter-person change propagated and acted on by a teammate's agent.
- Handoff from one person's session to a teammate's session, accepted with full context.
- Dashboard shows the full trail: decision → conflict → alert → acknowledgement → handoff.
- Stretch: a lesson drafted from a resolved conflict and injected into a new session; a claude.ai participant joining as a PM.

**How each theme is measured (from Keel's own event log, not surveys):**

| Theme | Metric | Source |
|---|---|---|
| Productivity | Conflicts caught before code; share caught pre-commit vs. post-commit; duplicate work detected | `check_intent`, drift signals, PR checks |
| Efficiency | Time from decision change to acknowledgement by all dependents; conflict resolution time; open conflict age | Alerts, conflicts |
| Knowledge accessibility | Share of sessions started with current decisions; re-explanation rate; decisions saved before compaction | Session start, duplicates, pre-compaction capture |
| Continuous improvement | Recurrence rate after lessons; reversal rate by scope | Outcomes, lessons |
| Trust guardrail | Alert precision (useful vs. noise) | Alert feedback |

**Hackathon proof:** run the same scripted scenario with and without Keel; compare time to discover drift, files reworked, and time until all sessions are consistent. Quote live numbers only.

**Open-source v1 (targets to be set by the team):**
- Time to first value for a new user (install → first conflict caught).
- Weekly active projects and retention.
- Community-contributed adapters.
- Conflict precision as rated by users (useful vs. noise).
- Recurrence rate: the same failure type in the same scope happens less often after a lesson is active.

## 9. Assumptions and dependencies

- MCP remains the common integration layer across major agent harnesses. Keel tracks the MCP roadmap (long-running Tasks, authorization and identity, skills) and aligns with it rather than building parallel mechanisms. See `ARCHITECTURE.md` §12.
- Claude Code hooks support injecting context at session start and prompt submit, and a pre-compaction event. Verify exact behavior against the official hooks reference before building: https://docs.claude.com/en/docs/claude-code/hooks
- Claude Code exposes hooks after tool use and at the end of a turn that Keel can use for edit observation and end-of-turn capture; plan-finalization capture depends on what the harness exposes. Verify before building.
- An LLM is available for semantic conflict checks; cost per check must stay low enough for frequent use.
- AI web apps continue to support remote MCP custom connectors. Support, plan gating, and write permissions vary by vendor and change often; verify per platform before committing (see `BUSINESS.md` §7.1).

## 10. Risks (product)

| Risk | Mitigation |
|---|---|
| Too many false positives; users mute it | Scope filtering first, evidence required, severity tiers, feedback on every alert |
| Agents don't record decisions consistently | Hook-driven prompts, skill instructions, silent-drift detection from edits, commits, and gateways |
| Silent-drift checks are costly or noisy | Scope filter first, batching, async checks, "possible drift" tier, deterministic rules for structured fields |
| Autonomous agents act without accountability | Agent identity with a human sponsor; scope and category limits |
| Latency slows agents down | Async checks by default; blocking checks only on explicit `check_intent` |
| "Decision" is too vague a unit | Start with explicit, small decisions; refine schema from real usage |
| Harness vendors add cross-session consistency inside their own tools | Stay neutral across harnesses; integrate their shared sessions as participants |
| Outcome data is too sparse to learn from | Infer candidate outcomes automatically; ask owners for one-click confirmation |
| Keel learns the wrong lesson from thin data | Minimum evidence count, owner approval, expiry dates |
| Too many lessons degrade agent performance | Inject only top-ranked lessons per scope; lessons decay over time |
| Gaming the metric (fewer alerts ≠ better) | Judge improvement by recurrence and rework, never by alert volume |
| Web-app models don't call Keel reliably | Project instructions, steering tool descriptions, piggyback delivery, Slack/email fallback |