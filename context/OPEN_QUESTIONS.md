# Open Questions — for team review

Add `[GAP]` or `[CHALLENGE]` items at the bottom. Mark decisions with the owner and date once settled.

## Product
1. **Name.** "Keel" is a placeholder. Check GitHub, npm, PyPI, and domain availability before committing. — *still open; do not harden into identifiers.*
2. **What counts as a decision?** Explicit only (agent calls `record_decision`), or also extracted automatically with confirmation?
   - **Decision (vasanr, 2026-10-09):** Both. Explicit `record_decision` is the primary path; automatic extraction surfaces *candidates* that require human/agent confirmation before becoming an `active` decision. Extraction never writes an active decision silently (honors "propose, don't self-modify" + "humans resolve").
3. **Default status.** Should new decisions be `active` or `proposed` by default in team projects?
   - **Decision (vasanr, 2026-10-09):** `active` by default. Explicit `record_decision` from a trusted session creates an `active` decision (still runs the conflict pipeline on insert). Auto-extracted candidates (Q2) remain `proposed` until confirmed.
4. **Blocking vs warning.** Should `check_intent` ever block an agent, or only warn?
   - **Decision (vasanr, 2026-10-09):** Warn only in v1. `check_intent` never blocks. Matches principle "Humans resolve; Keel flags." Revisit a configurable blocking mode post-v1.
5. **Scope tags.** Free-form, or a small controlled vocabulary per project?
   - **[GAP] Open — to discuss.** Leaning: free-form proposal by agents + **server-side normalization** against existing tags (fuzzy match → canonical), since scope-tag mismatch is the single silent point of failure. Need to decide whether projects can pin a controlled vocabulary. Owner: team.

## Technical
6. **Build on a memory layer or own the store?** Start with plain Postgres, or integrate a memory layer (e.g., Mem0) from day one?
   - **Decision (vasanr, 2026-10-09):** Own the store — plain Postgres 16 + pgvector, no memory-layer dependency in v1. Rationale: our value is determinism, append-only hash chain, serialized-per-scope conflict insert, and auditable retrieval — a general memory layer abstracts away exactly the control the audit trail and deny-once rule depend on. Keep the store ours; a memory layer can be an optional adapter later.
7. **Which LLM for conflict judgment?** Cost and latency per check need a benchmark.
   - **Decision (vasanr, 2026-10-09):** Two-tier + a complexity router.
     - **Cold path (conflict judgment / explanations):** a strong reasoning model (default latest Claude Opus) for complex/ambiguous candidates — quality and explanation prose matter more than latency here.
     - **Router:** a lightweight classifier scores each check's complexity and routes simple candidates to a cheaper model (Haiku/Sonnet class), hard ones to Opus. Saves cost/latency without losing quality on the cases that matter.
     - **Hot path (`PreToolUse`):** small *local* classifier only (triage), never the LLM — must be imperceptible (§7.2).
     - Still need the benchmark (cost + latency per check) before external claims.
8. **Hook verification.** Confirm Claude Code hook names, inputs, and context-injection behavior against current docs.
   - **Decision (vasanr, 2026-10-09):** Yes — verify against https://docs.claude.com/en/docs/claude-code/hooks before building the adapter. Largest unvalidated assumption (#8 was flagged in CLAUDE.md). Build task: validate the six P0 hooks + `additionalContext` behavior first.
9. **Hosting for the demo.** Hosted instance vs tunnel from one laptop.
   - **Decision (vasanr, 2026-10-09):** Host on **GCP**. Target: Cloud Run (container from Docker Compose image) + Cloud SQL for Postgres (pgvector). Gives a stable public MCP endpoint for the light-tier connectors; no laptop tunnel.

## Business
10. **License.** Apache-2.0 vs a more protective license for the server.
11. **Open-core boundary.** Observal ships SSO, SCIM, and audit logs as open source. What stays paid for us?
12. **Partner or compete with a memory-layer project (e.g., Mem0)?** Reach out to the maintainers? *(Note: an earlier draft referenced "OpenKT" — that project name could not be verified as of 2026-10-09; do not cite it externally.)*
13. **Spec standard.** Publish the decision schema and MCP tool contract as an open spec early?

## Outcome loop and AI-native framing
17. **Outcome inference window.** How many days after a decision does a supersede count as "reversed"?
    - **Decision (vasanr, 2026-10-09):** User-configurable per project. Default proposed: 7 days. (Confirm against Q25/26 so the three windows — outcome, min-evidence, lesson-expiry — are not conflated.)
18. **Show the outcome loop in the demo?** A short dashboard view of "decisions reversed / rework caused" could support the closed-loop story, but adds build time.
    - **Decision (vasanr, 2026-10-09):** Yes — include a small read-only dashboard view (decisions reversed / rework caused) in the demo.
19. **Transcript ingestion.** Should meeting and Slack ingestion (decision candidates only) move earlier on the roadmap given the "company brain" framing?
    - **Decision (vasanr, 2026-10-09):** Yes — move transcript/Slack ingestion (candidate extraction only, confirmation required per Q2) earlier on the roadmap. Not necessarily in the P0 demo cut — confirm against HACKATHON_PLAN §3 before promoting it to P0.
20. **Pitch claims.** Verify YC talk quotes and MCP usage figures against the original sources before using them on slides.
    - **Decision (vasanr, 2026-10-09):** Yes — verify all pitch claims against primary sources before external use; no YC-endorsement implication.

## Multiplayer
21. **Handoff target.** Hand off to a person (any of their sessions) or to a specific session? Default proposed: person.
    - **Decision (vasanr, 2026-10-09):** Default to **person** (any of their sessions). Session-specific targeting can be an optional override later.
22. **Partial handoff.** Can a handoff transfer some decisions in a scope but not others?
    - **Decision (vasanr, 2026-10-09):** Yes — a handoff can transfer a subset of decisions within a scope, not forced all-or-nothing.
23. **Shared live sessions.** Which harnesses support multiple humans in one session today, and how would they register with Keel?
    - **[GAP] Open — not sure.** Needs research on current harness support. Note: live shared-session runtime is an explicit non-goal (PRD §3), so this is about *registration/identity* only, not building a shared runtime. Owner: team.

## Lessons (self-improvement)
24. **Who approves lessons?** The owner of the scope, the decision owner involved, or any project admin?
    - **Decision (vasanr, 2026-10-09):** The **decision owner** involved approves the lesson.
25. **Minimum evidence.** How many incidents before Keel drafts a lesson automatically?
    - **Decision (vasanr, 2026-10-09):** User-configurable per project. Default proposed: 2 incidents before an auto-draft. *(Note: the "default 7 days" from the raw answer reads as the expiry window — mapped to Q26. Confirm 25 vs 26.)*
26. **Lesson expiry.** Default lifetime before a lesson must be renewed?
    - **Decision (vasanr, 2026-10-09):** User-configurable per project. Default: **7 days** before a lesson must be renewed.
27. **Context budget.** How many lessons can be injected per session before they hurt agent performance? Needs a small experiment.
    - **Decision (vasanr, 2026-10-09):** Start with a configurable cap, default **5 lessons per session injection**, highest-relevance first. Confirm with a small experiment before hardening.

## Web-app tier
28. **Which plans does the team have?** Confirm Claude and ChatGPT plans support custom connectors with write actions.
    - **Decision (vasanr, 2026-10-09):** Proceed on the assumption plans support custom connectors with write actions — **confirm** the actual Claude/ChatGPT plan entitlements before relying on the light tier in the demo.
29. **OAuth provider.** Build OAuth into Keel, or use a hosted provider for the hackathon?
    - **Decision (vasanr, 2026-10-09):** Use a **hosted provider** for the hackathon (e.g., Google / Auth0) rather than building OAuth into Keel. Faster, safer, less surface to secure under time pressure. Self-hosted OAuth is a post-hackathon consideration.
30. **Gemini consumer app.** Sources conflict on custom MCP support; verify before listing it.
31. **Attempt the claude.ai stretch goal?** Decide by a fixed checkpoint during the event.

## Silent drift, identity, and ecosystem
32. **Edit-hook cost.** Batch window and per-session budget for drift checks?
33. **PR check in the demo?** A GitHub Action comment on a PR is a strong visual, but adds build time.
34. **Agent sponsors.** Can an agent sponsor be a team rather than one person? What can agents activate vs. only propose?
35. **Plan capture.** Which harnesses expose a reliable "plan finalized" event or artifact?
36. **Orchestrator.inc plugin.** Build after the hackathon as the first workspace adapter? Check their plugin API.
37. **HumanLayer.** Watch for open-sourced building blocks; integrate or differentiate? Avoid "control plane" wording in our pitch.
38. **Verify competitor facts** (pricing, star counts, features) on the day of any external pitch.

## Hackathon
14. **Event details.** Exact duration, judging criteria, and submission requirements.
15. **Include a fifth integration (HubSpot or Slack) in the demo, or keep it Claude-only?**
16. **Owners for each workstream** in `HACKATHON_PLAN.md`.

## Team additions
<!-- Add [GAP] / [CHALLENGE] items below -->