# Business Perspective — Keel (working name)

**Version:** 1.0 (final draft for team review) · **Last updated:** 2026-10-05

---

## 1. Recommendation

Launch Keel as an **open-source, vendor-neutral intent ledger** for AI builders, win single-player and small-team adoption first, then sell a governed **enterprise edition** (the GitHub → GitLab path). Do not compete on memory storage or enterprise search; position as the consistency layer that sits on top of them.

## 2. Why now

- **Context is where enterprise AI competition has moved.** At Team '26 (May 2026), Atlassian opened its Teamwork Graph to any MCP-compatible agent, positioning it as a context layer for external AI tools. Coverage notes Microsoft, Glean, Salesforce, Notion, and others converging on the same idea.
  Sources: https://thelettertwo.com/2026/05/06/atlassian-teamwork-graph-open-third-party-ai-agents/ · https://productimpactpod.com/news/atlassian-teamwork-graph-context-2026/
- **Intent-as-source-of-truth is proven for code.** GitHub's Spec Kit reportedly passed 115,000 stars by June 2026; Kiro, OpenSpec, and Tessl follow the same pattern.
  Source: https://ssojet.com/blog/best-spec-driven-development-tools
- **MCP is the common integration layer.** Most major agent harnesses and enterprise tools now expose or consume MCP, which makes a neutral layer practical.
- **The AI-native company thesis needs a consistency layer.** Recent YC talks (Tom Blomfield, Diana Hu) argue that AI should replace humans as the organization's coordination mechanism, that companies should be fully legible to AI (a "company brain"), and that they should run as closed loops with quality gates. A company brain built from raw transcripts and chats will contain contradictions. Keel is the structured layer that keeps it consistent. *(Based on team-provided summaries; verify quotes against the original talks before external use.)*
- **AI is expected to go multiplayer.** YC's Request for Startups on "Multiplayer AI" argues that agent work is still single-player (private threads, read-only transcripts) and that teams will share live agent sessions to watch, redirect, and hand off long-running work across engineering, sales, support, legal, finance, and marketing. Multiplayer needs a shared source of truth underneath; Keel is that layer across harnesses. *(Team-provided text; cite the original RFS page and do not imply YC endorsement.)*
- **Agents are moving from coding to general knowledge work.** Coding agents reached production first because compilers and tests give automatic feedback. Knowledge work has no equivalent; Keel provides that feedback for intent.
- **Multi-agent work is now normal.** People run parallel sessions, subagents, and multiple tools on one project, and existing tools isolate each one.
- **Agent workspaces are getting traction, which validates the space.** HumanLayer positions itself as a multiplayer coding agent IDE and cloud that brings agent sessions, plan artifacts, and code diffs together for teams. Orchestrator.inc (Apache-2.0, ~12.9k GitHub stars at time of review) runs fleets of coding agents across 25+ harnesses. Both focus on running and supervising the work; neither positions itself around cross-person, cross-task contradiction detection.
  Sources: https://www.humanlayer.dev/ · https://github.com/OrchestratorInc/agent-orchestrator

## 3. Problem → value

| Pain | Who feels it | Value Keel delivers |
|---|---|---|
| Agents act on stale or contradictory assumptions | Developers, tech leads | Conflicts flagged before code is written |
| Decisions live in chat history and disappear | Everyone | Versioned decision history with owner and rationale |
| Changes don't reach the people and agents affected | Cross-team projects | Push propagation to dependents |
| No audit trail for why an agent did something | Engineering leadership, regulated enterprises | Append-only, attributed event log |

## 4. Competitive landscape

| Category | Examples | What they do | Gap Keel fills |
|---|---|---|---|
| Shared agent memory | OpenKT, Mem0 OpenMemory, agentmemory, team-memory-mcp | Store and recall context across agents and people | No contradiction detection or push propagation |
| Coding-agent coordination | agent-coord, Concord MCP, MAC, Turf, CoordMCP | File locks, task claims, messaging between coding agents | File-level and developer-only; no semantic intent |
| Multiplayer agent workspaces | HumanLayer | Team workspace for coding agent sessions, plan artifacts, design reviews, diffs; comments and decisions feed back to agents | Coding-only, task-scoped, a destination workspace, not open source (yet) |
| Agent fleet orchestrators | Orchestrator.inc, others | One person's orchestrator plans work, spawns workers in worktrees, routes CI and review feedback | Single-supervisor scope; no cross-person consistency (complementary; adapter target) |
| MCP gateways and agent identity | Mint MCP, others | Govern which tools and data agents can access; agent identities and audit | Governs *access*, not *intent* (complementary; drift-signal source and distribution channel) |
| Agent registries / governance | Observal | Registry and insights for Skills, MCP servers, agents | Governs agents, not the intent they act on (complementary) |
| Knowledge-base hygiene | Slite, Bloomfire, Fini, Guru | Flag stale or contradictory published documents | Document-centric; not live agent sessions; proprietary |
| Spec-driven development | GitHub Spec Kit, Kiro, OpenSpec, Spec Kitty | Spec as source of truth for code | Developer-only, code-scoped |
| Live multiplayer agent sessions | Expected from harness vendors and new startups (per YC RFS) | Many people inside one running agent session | Consistency *across* sessions and tools; Keel integrates them as participants |
| Enterprise context graphs | Atlassian Teamwork Graph / Rovo, Microsoft Graph, Glean | Organization-wide context exposed to agents | Vendor-centric; no neutral cross-tool drift detection |

Sources: https://github.com/Observal/Observal · https://github.com/generalmachines/OpenKT-ai · https://mem0.ai/blog/introducing-openmemory-mcp · https://github.com/bradagi/awesome-cli-coding-agents · https://www.eesel.ai/blog/best-ai-tools-for-knowledge-base-management · https://github.blog/2025-09-02-spec-driven-development-with-ai-get-started-with-a-new-open-source-toolkit/

**Note:** this scan is based on public READMEs and articles as of 2026-10-05. Re-validate before any external pitch.

### 4.1 Closest competitors in detail

**HumanLayer** (YC-backed, closed source for now)
- *What it is:* a multiplayer coding agent IDE and cloud. Tasks group agent sessions, artifacts, and worktrees for the whole team; a structured workflow (questions → research → design → structure → plan → implement); inline human and agent comments on design docs that feed back to the agents; full session visibility; support for Claude Code, Codex, and Copilot; "compounding engineering" listed as a Pro feature.
- *Pricing (public):* Starter free for up to 3 members; Pro $100/user/month; Enterprise custom with SSO/SAML, audit logs, and on-prem/private VPC.
- *Overlap with Keel:* multiplayer, decisions feeding agents at the plan stage, learning over time.
- *Difference:* HumanLayer is a workspace you work *inside*, focused on coding tasks. Keel is a neutral layer that works *across* workspaces, tasks, tools, and roles, and focuses on detecting contradictions between them. Keel is open source from day one.
- *Implication:* do not position Keel as a "control plane" or workspace; HumanLayer owns that framing. Treat it as a potential integration target, not a head-on competitor.

**Orchestrator.inc** (Apache-2.0)
- *What it is:* a local desktop workspace where a project orchestrator agent plans work, spawns workers into their own branches and worktrees, and tracks them on a live Kanban with PR, CI, and review state. Its orchestrator keeps project goals, decisions, and constraints in a project-scoped conversation and passes relevant context to workers.
- *Overlap with Keel:* decisions and constraints passed to workers.
- *Difference:* that context lives in one supervisor's planning conversation on one machine. Keel keeps intent consistent *between* supervisors, people, tasks, and non-coding roles, and catches drift after work starts.
- *Implication:* strong adapter target. An Orchestrator.inc plugin that pulls Keel context for every worker and reports worker activity would put Keel in front of a large open-source user base.

Sources: https://www.humanlayer.dev/ · https://orchestrator.inc/ · https://github.com/OrchestratorInc/agent-orchestrator

## 5. Positioning

- **For** teams whose members each work through AI agents,
- **who** lose time to contradictory assumptions and rework between sessions, people, and tools,
- **Keel is** an open-source intent ledger
- **that** captures decisions from agent sessions, detects contradictions, and pushes changes to everyone affected.
- **Unlike** memory layers, knowledge-base tools, or vendor context graphs, Keel is neutral across tools and focused on consistency, not storage.

**One-liner:** Every AI-native company needs a brain. Keel keeps it consistent.

**Category line:** Workspaces run the work. Orchestrators split the work. Keel keeps everyone's intent consistent across all of them.

**Multiplayer line:** AI is going multiplayer. Multiplayer needs a shared source of truth. Keel is that layer for agents, across every tool.

**Self-improving line:** Keel sees the gap between what a team intended and what actually happened, across every person, session, and tool, and turns repeated failures into approved lessons every agent starts with. Measured by recurrence, not claimed.

**Supporting line:** Keel is the compiler for team intent: it catches contradictions before they become rework, and learns which decisions drift.

### Deliberate design choice: decisions, not transcripts
The AI-native playbook says "record everything." Keel does not store raw transcripts. Raw recordings (meetings, Slack, sessions) are *inputs*; Keel stores the *structured truth* extracted from them: decisions with owners, rationale, status, and outcomes. This keeps the data model small and auditable, reduces privacy exposure, and makes enterprise security review easier.

## 6. Business model (open core)

**Market reference:** HumanLayer's public pricing ($100/user/month for Pro, free for up to 3) shows teams pay per seat for multiplayer agent tooling. Keel's pricing is still undecided; this is a reference point, not a target.


| Open source (Apache-2.0 proposed) | Enterprise edition |
|---|---|
| Core ledger, conflict engine, MCP server | SSO / SAML, SCIM provisioning |
| Claude Code and generic MCP adapters | Role-based access and permission mirroring from source systems |
| GitHub, Slack, Notion adapters | Microsoft 365, Salesforce, ServiceNow, Atlassian adapters |
| Self-hosted, single project or small team | Multi-team, cross-project policies and approval gates |
| Basic dashboard and metrics | Audit exports, retention controls, compliance reporting |
| Community support | Hosted option, SLAs, support |

**Pricing:** not defined. Options to evaluate later: per-seat, per-active-project, or platform license for self-hosted enterprise. No numbers until there is usage data.

**Open question:** whether SSO and audit logs stay in open source. Observal ships SAML SSO, SCIM, and audit logs under Apache-2.0, which raises the bar for what can be paid. See `OPEN_QUESTIONS.md`.

## 7. Go-to-market phases

| Phase | Target | Motion | Exit signal |
|---|---|---|---|
| **0. Hackathon** | Judges, builders at the event | Live demo | Working demo, early feedback |
| **1. Single player** | Solo builders running parallel sessions | Open-source launch, Claude Code plugin, Cursor/Codex setup guides, builder communities | Users keep it installed after week one |
| **2. Small teams** | Dev teams of 2–10 | Team server, Slack alerts, GitHub PR checks, Orchestrator.inc plugin | Teams invite second and third members |
| **3. Cross-functional** | Startups with PM/design/sales on agents | Light tier in AI web apps (Claude, ChatGPT, Gemini, Copilot) plus Notion, Figma, HubSpot adapters | Non-developers record decisions |
| **4. Enterprise** | Platform and engineering leadership | Enterprise edition, design partners | Paid pilots |

### 7.1 Platform coverage (light tier, as of mid-2026)

| Platform | Custom MCP support | Notes |
|---|---|---|
| Claude (web, desktop, mobile) | Yes, all plans including Free | Remote servers are called from Anthropic's cloud |
| ChatGPT | Developer Mode (beta, web, paid plans) | Write-action availability by plan is documented inconsistently; test `record_decision` on the target plan |
| Gemini Enterprise | Yes, admin-configured | Streamable HTTP only; public HTTPS with a public-CA certificate |
| Gemini consumer app | Unclear | Sources conflict; verify before claiming |
| Microsoft 365 Copilot | Maker/admin via Copilot Studio | Not available in consumer Copilot |
| Perplexity, Grok, Mistral Le Chat | Reported yes | Verify individually |

Sources: https://support.claude.com/en/articles/11175166-about-custom-connectors-remote-mcp · https://support.claude.com/en/articles/11503834-building-custom-connectors-via-remote-mcp-servers · https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt · https://docs.cloud.google.com/gemini/enterprise/docs/connectors/custom-mcp-server/set-up-custom-mcp-server · https://calmara.app/mcp-compatibility

**Why it matters commercially:** the deep tier wins developers; the light tier is how PMs, sales, legal, and support join without changing tools, which is the path to cross-functional and enterprise adoption.

## 8. Moat (honest view)

- **Weak early:** the core idea is easy to copy; incumbents could add drift detection inside their own graphs.
- **Builds over time:** neutrality across tools, an adapter ecosystem, the decision-schema standard if adopted, and accumulated decision and outcome history inside customer projects. If internal software becomes disposable, as the AI-native thesis argues, the durable asset is context; decision history with outcomes is the most valuable part of it.
- **Compounding:** the outcome loop makes Keel better per project over time (which scopes drift, which alerts are noise), which a newly installed competitor cannot replicate.
- **Cross-session learning:** a single agent's memory can learn from its own mistakes; only a cross-session, cross-tool layer can see systemic failure patterns (e.g., contradictions clustering after handoffs). Approved lessons and their measured effectiveness accumulate inside each customer project.
- **Strategy:** publish the decision schema and MCP tool contract as an open spec early, so Keel is the reference implementation.

## 9. Key risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Atlassian, Notion, or Microsoft add cross-role drift detection | Medium–high | Stay neutral and agent-native; integrate them as sources |
| Agent workspaces (e.g., HumanLayer) add cross-task, cross-person contradiction detection | Medium–high | Stay a neutral layer; integrate with workspaces; differentiate on cross-role and open source |
| Harness vendors build shared sessions plus cross-session consistency inside their own tools | Medium | Neutrality across harnesses; integrate their shared sessions as participants |
| Memory-layer projects (e.g., OpenKT) add contradiction detection | Medium | Move fast on propagation and lifecycle; consider partnering |
| Noise causes users to disable alerts | High if unmanaged | Precision over recall; evidence on every alert |
| Open-source traction without monetization | Medium | Define the enterprise boundary early |
| Crowded space makes discovery hard | High | Sharp single-player wedge and clear demo |
| Web-app vendors change connector policies, plan gating, or permissions | Medium–high | Support many platforms; keep the deep tier and Slack/email as fallbacks |
| "Self-improving" is perceived as hype | Medium | Show measured recurrence reduction; publish the autonomy levels and approval model |

## 10. Metrics to track

- **Adoption:** installs, weekly active projects, participants per project.
- **Value:** conflicts caught, share marked useful, time from change to acknowledgement.
- **Learning:** decisions with recorded outcomes, reversal rate by scope over time, alert precision trend, recurrence rate after lessons, share of drafted lessons approved.
- **Reach:** participants by tier (deep vs. light), non-developer participants per project.
- **Expansion:** projects that add a second person, a second harness, a non-developer role.
- **Community:** contributors, adapters contributed, issues closed.