# DSP-AI Enhancements — Dev Session Kickoff Prompts

Three self-contained prompts, one per dev session. Paste any of them as the initial message to `claude` (interactive) or `claude -p` (one-shot) to start that session, or hand to `team-lead` for orchestrated execution.

Each prompt is written to a fresh agent with no prior context — they include everything the agent needs to pick up cold.

**Repo:** `sap-doc-agent` (Spec2Sphere), deployed at `:8260`.
**Design spec:** `docs/superpowers/specs/2026-04-17-dsp-ai-enhancements-design.md`
**Plans (one per session):** `docs/superpowers/plans/2026-04-17-dspai-session-{a,b,c}-*.md`

---

## Prompt — Session A: Foundation + Vertical Slice

```
You are executing Session A of the DSP-AI Enhancements project inside the
sap-doc-agent (Spec2Sphere) repo at /home/hesch/dev/projects/sap-doc-agent.

GOAL
One enhancement produces a narrative natively in a Horváth SAC story via
Pattern B (write-back to dsp_ai.* tables). Studio create/preview/publish
loop works end-to-end. Bootstrap wizard brings a fresh compose to first
preview in <15 minutes.

READ FIRST (mandatory):
  1. docs/superpowers/specs/2026-04-17-dsp-ai-enhancements-design.md
     — full design, all 17 sections
  2. docs/superpowers/plans/2026-04-17-dspai-session-a-foundation-vertical-slice.md
     — your task list, 14 tasks with exact code blocks + commit guidance

EXECUTE
Use the superpowers:subagent-driven-development skill. Dispatch one
subagent per task, review between tasks, commit after each, push after
every 3 tasks. Checkbox items use `- [ ]` syntax — mark them as you go.

Where the plan says "similar test" or "fixtures as needed", write them
explicitly. No placeholders land in the code.

AUTONOMY RULES
- Do not ask permission — if the task is specified, build it
- When blocked, diagnose the root cause (read logs, check migrations,
  query Postgres/Neo4j); do not use destructive shortcuts
- If something in the plan is wrong (e.g., missing import, function
  signature mismatch) fix it inline and note why in the commit
- Do not touch services outside sap-doc-agent (no homelab infra changes)
- Keep LLM_ENDPOINT env-configurable; default to homelab router for dev
- Respect HTMX patterns from memory/feedback_htmx_script_loading.md —
  scripts in {% block content %}, IIFE not DOMContentLoaded

GIT WORKFLOW
- Branch: `feat/dsp-ai-session-a` off main
- Commit per task as the plan dictates (one commit = one logical change)
- Push every 3 tasks; PR at the end

COMPLETION
Session A is done when all these are true:
  □ `curl http://localhost:8261/v1/healthz` → 200 {"status":"ok"}
  □ Morning Brief seed produces ≥1 row in dsp_ai.briefings
  □ Studio UI: create a blank enhancement, preview, publish — all via UI
  □ Brain: `MATCH (o:DspObject) RETURN count(o)` > 0 after a DSP scan
  □ NOTIFY round-trips: psql LISTEN enhancement_published sees events
  □ `pytest -m smoke` green against a running compose
  □ `docker compose down -v && docker compose up` → first preview <15 min
  □ All 14 tasks' commits on the branch, tests green in CI

ON COMPLETION
  1. Open PR titled "feat(dsp-ai): Session A — foundation + vertical slice"
     Body: the 7 ship criteria checklist above with ☑ per item
  2. Merge to main when CI is green (auto-merge if all checks pass)
  3. Deploy via ops-bridge: `mcp__ops-bridge__deploy --repo sap-doc-agent`
  4. Run `pytest -m smoke` against the deployed instance
  5. Hand to the QA agent with inputs:
       task:   "Verify DSP-AI Session A end-to-end"
       brief:  path to this prompt + the Session A plan + the spec
       report: "verify all 7 ship criteria on live :8260/:8261"
  6. Save a memory summarizing what shipped and what remains for Session B.

Begin with reading the three referenced documents, then start Task 1.
```

---

## Prompt — Session B: Breadth + Widget + Consolidation

```
You are executing Session B of the DSP-AI Enhancements project inside the
sap-doc-agent (Spec2Sphere) repo at /home/hesch/dev/projects/sap-doc-agent.

PREREQUISITE
Session A must be merged to main and deployed at :8260/:8261. Verify
before starting:
  - `curl http://localhost:8261/v1/healthz` returns 200
  - `SELECT count(*) FROM dsp_ai.enhancements WHERE status='published'` ≥ 1
  - `pytest -m smoke` green
If any precondition fails, STOP and escalate.

GOAL
Expand from vertical slice to full breadth. All 5 enhancement kinds ship.
SAC Custom Widget (Pattern A) built and deployed. Studio gains Template
Library, Generation Log, Brain Explorer. Consolidate: graph.json →
Neo4j, Copilot ContentHub → Corporate Brain, MCP Studio tools, AND every
existing LLM call across agents/, migration/, core/standards/,
core/knowledge/ logs to dsp_ai.generations via the ObservedLLMProvider
wrapper (one-line factory change; zero call-site changes required).

READ FIRST (mandatory):
  1. docs/superpowers/specs/2026-04-17-dsp-ai-enhancements-design.md
  2. docs/superpowers/plans/2026-04-17-dspai-session-b-breadth-widget-consolidation.md
     — your task list, 13 tasks
  3. docs/superpowers/plans/2026-04-17-dspai-session-a-foundation-vertical-slice.md
     — Session A context (what's already built; don't re-scaffold)

EXECUTE
Use superpowers:subagent-driven-development. One subagent per task.

Special attention points for Session B:
- The SAC Custom Widget (Task 4) is the riskiest single deliverable.
  Budget time: if SAC SDK friction blocks integration end-to-end in
  the Horváth tenant, ship it as Studio-preview-only and file a
  follow-up ticket for full SAC install. Document the blocker clearly.
- graph.json cutover (Task 8) ships as WRITE-BOTH + optional brain-read
  flag — do NOT delete graph.json writes in this session. That's
  Session C.
- MCP Studio tools (Task 10) must not interfere with existing Copilot
  MCP tools — register alongside, don't replace.
- Task 13 observability — the one-line factory change in
  llm/__init__.py is the whole migration; don't overthink it. The
  wrapper is best-effort (logging failures never break LLM calls).
  Migration 013 renumbers to 012 if Session C hasn't landed its 012
  first — resolve during execution. Populating `caller=...` at the
  ~15–25 call sites is a nice-to-have (Step 13.6), not a blocker.

AUTONOMY RULES
Same as Session A:
- Don't ask permission
- Fix plan inconsistencies inline with explanation in commit
- No touches outside sap-doc-agent
- Respect HTMX + nb9-* CSS + existing Spec2Sphere conventions
- Keep the widget under 50 KB gzipped (enforce in build step)

GIT WORKFLOW
- Branch: `feat/dsp-ai-session-b` off main
- Commit per task; push every 3 tasks
- PR at the end; squash-merge is OK given the number of commits

COMPLETION
All must be true:
  □ 5 seed templates published; each has ≥1 generation
  □ Widget manifest + bundle served from /widget/* with integrity hash
  □ Widget renders in Horváth SAC (or Studio preview if SAC blocked)
  □ Widget telemetry lands in dsp_ai.user_state + Brain OPENED edges
  □ Studio: Template Library, Generation Log, Brain Explorer all live
  □ MCP studio tools callable from Claude Code
  □ graph.json write-both works; GRAPH_READ_FROM_BRAIN flag toggles
  □ Copilot ContentHub queries Brain; existing Copilot answers unchanged
  □ browser_viewer + agent_terminal polling replaced with SSE
  □ file_drop uses inotify + NOTIFY (no 5-min poll)
  □ Task 13 observability: ObservedLLMProvider wraps every factory
    result; trigger any agent/migration/standards path and confirm
    dsp_ai.generations has a new row with caller='...' and
    enhancement_id=NULL
  □ `pytest -m smoke` green

ON COMPLETION
  1. PR: "feat(dsp-ai): Session B — breadth + widget + consolidation"
  2. Merge on CI green
  3. Deploy via ops-bridge
  4. Run `pytest -m smoke` against live
  5. Build widget in container + verify manifest served at /widget/manifest.json
  6. Hand to QA agent with:
       task:   "Verify DSP-AI Session B breadth + widget + consolidation"
       brief:  this prompt + Session B plan + spec
       report: "11-item ship criteria; pay special attention to widget
                end-to-end in SAC and graph.json dual-read safety"
  7. Update memory with B status + open items (e.g., if SAC install
     blocked, note the workaround).

Begin with reading the three docs, verifying preconditions, then Task 1.
```

---

## Prompt — Session C: Portability + Second-Customer Ready

```
You are executing Session C of the DSP-AI Enhancements project inside the
sap-doc-agent (Spec2Sphere) repo at /home/hesch/dev/projects/sap-doc-agent.

PREREQUISITE
Sessions A + B merged and deployed. Verify:
  - Session B smoke tests green on live
  - All 5 enhancement kinds published with recent generations
  - SAC widget manifest served at /widget/manifest.json
  - `pytest -m smoke` green
If any precondition fails, STOP and escalate.

GOAL
Turn the prototype into a shippable product. Offline profile with
bundled Ollama. Library export/import. Publish diff preview. Cost
guardrails. Multi-tenant RLS. RBAC enforcement. graph.json retirement.
CPG/Retail reference library. Deploy docs + demo script + backup/
restore scripts. Widget degraded-mode polish + admin chip.

READ FIRST (mandatory):
  1. docs/superpowers/specs/2026-04-17-dsp-ai-enhancements-design.md
  2. docs/superpowers/plans/2026-04-17-dspai-session-c-portability-second-customer.md
     — your task list, 12 tasks
  3. docs/superpowers/plans/2026-04-17-dspai-session-{a,b}-*.md
     — context for what's built

EXECUTE
Use superpowers:subagent-driven-development. One subagent per task.

Special attention points for Session C:
- Multi-tenant RLS (Task 2) is high-risk: Postgres RLS policies + every
  asyncpg.connect call site needs the customer context. Miss one and
  you've got a cross-tenant leak. Task 11 (portability test) is the
  safety net — run it after every multi-tenant change.
- graph.json retirement (Task 7) only proceeds if Session B's write-
  both + brain-read have been stable on live for ≥1 week. If not yet,
  SKIP Task 7 this session; complete the other 11 tasks and reschedule
  the cutover. Document clearly in the PR.
- Offline profile (Task 1) requires ~10GB pulled model weights on first
  boot. Don't gate Session C ship on a successful offline spin-up if
  the runner lacks disk — mark as "build successful, manual verification
  required on a machine with disk space."

AUTONOMY RULES
Same as A + B, plus:
- Every migration has an explicit downgrade path — no one-way changes
- RBAC failures MUST return 403 (not 401 or 500) — user-facing, auditable
- Cost guard CostExceeded → 429 with error_kind=cost_cap; never 500
- CPG/Retail library JSONs ship with realistic but PUBLIC sample data —
  zero customer-specific identifiers

GIT WORKFLOW
- Branch: `feat/dsp-ai-session-c` off main
- Commit per task; push every 3 tasks
- PR at the end

COMPLETION
All must be true:
  □ `docker compose --profile offline up` — Morning Brief works via Ollama
  □ Library export → fresh instance import → previews succeed → parity
  □ Publish diff modal shows on every publish; breaking changes flagged
  □ Cost guard pauses an enhancement when monthly cap breached;
    studio_audit has auto_pause row
  □ Viewer JWT blocked from publish/regen; author JWT allowed
  □ RLS blocks cross-customer reads via the standard connection helper
  □ Brain queries respect customer property filter
  □ graph.json no longer written by default (or Task 7 deferred with reason)
  □ CPG/Retail library imports cleanly into Horváth tenant, produces output
  □ Deploy docs present: client_checklist.md, demo_script.md, tls.md
  □ Scripts executable: demo_bootstrap.sh, backup.sh, restore.sh
  □ `pytest -m smoke` green; `pytest -m portability` green on a 2-instance run
  □ Time-to-demo-ready: ≤10 min via demo_bootstrap.sh

ON COMPLETION
  1. PR: "feat(dsp-ai): Session C — portability + second-customer ready"
  2. Merge on CI green
  3. Deploy via ops-bridge
  4. Run `pytest -m smoke` against live; run `pytest -m portability` on
     a clean VM or second docker project name
  5. Execute `scripts/backup.sh` to verify the tarball format
  6. Hand to QA agent with:
       task:   "Verify DSP-AI Session C portability + second-customer ready"
       brief:  this prompt + Session C plan + spec
       report: "13-item ship criteria; special focus on multi-tenant
                isolation (no cross-customer leaks), RBAC boundary,
                and the portability round-trip test"
  7. Save a memory: project_dsp_ai_complete.md summarizing what shipped
     across A+B+C, any deferred items, known limitations.
  8. If Session B was shipped with Studio-preview-only widget (SAC
     install blocked), verify during this session whether to retry SAC
     install now that RBAC + TLS docs exist. If successful, add a final
     commit. If still blocked, document clearly in the completion memo.

FINAL STATE
The repo + exported library + this compose must be bring-to-a-client
ready. A fresh machine with docker + 16GB RAM + internet should
complete demo_bootstrap.sh in under 10 minutes and land on a working
Studio UI with at least 3 published enhancements producing output.

Begin with reading the docs, verifying preconditions, then Task 1.
```

---

## Usage

### Interactive — paste into `claude` inside the repo worktree

```bash
cd /home/hesch/dev/projects/sap-doc-agent
claude
# then paste Prompt — Session A
```

### Team-lead orchestrated (autonomous)

Team-lead picks up Ready backlog items. Add three backlog items to the
Feature Registry, one per session, each with the prompt text as the
description:

```
create_backlog_item({
  "title": "DSP-AI Session A — foundation + vertical slice",
  "description": <Prompt — Session A body>,
  "spec_id": "dsp-ai-enhancements",
  "ready": true,
  "priority": "high"
})
```

Then invoke team-lead in autonomous mode for the time window you have
available.

### Safety net — how to stop early

Each prompt is a long-running task. If you need to interrupt:

- The branch `feat/dsp-ai-session-{a,b,c}` preserves in-progress work
- Commits after each task = natural checkpoints
- Re-entering the session: tell the agent "resume Session X from task N"
  and it will pick up where it left off

### On Session failures

If a session fails mid-way:
1. DO NOT revert completed tasks — leave the branch as-is
2. Diagnose the failure (logs, smoke output, migration state)
3. Fix the root cause
4. Resume from the failing task
5. If the failure reveals a design flaw, update the spec + affected
   plan first, commit that, then resume
