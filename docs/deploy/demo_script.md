# Spec2Sphere — 10-Minute Demo Script

> **Audience:** Sales engineer or developer running a live demo for a prospect.
> **Pre-requisites:** Stack running, CPG library imported, `STUDIO_AUTHOR_EMAILS` includes your email.
> Run `bash scripts/demo_bootstrap.sh` before the meeting to reach this state.

---

## Table of Contents

1. [Before You Start](#before-you-start)
2. [0:00–1:00 — Studio Overview](#000100--studio-overview)
3. [1:00–3:00 — Enhancement Editor + Generation Log](#100300--enhancement-editor--generation-log)
4. [3:00–5:00 — Live SAC Widget](#300500--live-sac-widget)
5. [5:00–6:00 — Action Enhancement Drill-Down](#500600--action-enhancement-drill-down)
6. [6:00–7:30 — Publish Workflow + Diff Modal](#600730--publish-workflow--diff-modal)
7. [7:30–9:00 — Brain Explorer](#730900--brain-explorer)
8. [9:00–10:00 — Library Export + Backup Story](#900100--library-export--backup-story)
9. [What's Next (30 seconds)](#whats-next-30-seconds)

---

## Before You Start

Verify the stack is healthy:

```bash
curl -sf http://localhost:8261/v1/healthz && echo "API OK"
curl -sf http://localhost:8260/ | grep -o "Spec2Sphere" && echo "Studio OK"
```

Have two browser tabs ready:

- Tab 1: `http://localhost:8260/ai-studio/`
- Tab 2: `http://localhost:8261/widget-test.html` (or your SAC sandbox story)

---

## 0:00–1:00 — Studio Overview

**Switch to Tab 1.**

> *"This is AI Studio — where business analysts configure and publish AI enhancements for SAP Analytics Cloud."*

Point out:

- The list shows **8 published CPG enhancements** (or 5 Horváth if using that seed set). Each card shows name, description, render hint (inline / panel / badge), and publish status.
- The **admin chip** (green badge) in the top-right of each card — visible only to authors. Clicking it opens the Generation Log for that enhancement.
- The **Library** button in the top nav — import/export bundles for client onboarding.

![screenshot: studio-list](./img/studio-list.png)

---

## 1:00–3:00 — Enhancement Editor + Generation Log

**Click "Morning Brief" (or the first enhancement in the list).**

> *"Each enhancement has a name, a prompt template, a render hint, and a cost cap. The prompt template is what gets sent to the LLM — with DSP object data injected at runtime."*

Point out:

- The `prompt_template` field — Jinja2 syntax, `{{ dsp_object.name }}` etc.
- The **Preview** button — runs the enhancement against a sample DspObject right now.

**Click Preview.**

> *"The result comes back in under two seconds. The admin chip in the top-right corner of the result card links directly to the Generation Log."*

**Click the admin chip on the preview result.**

![screenshot: generation-log-detail](./img/generation-log-detail.png)

> *"Every generation is logged: timestamp, model used, prompt tokens, completion tokens, cost in USD, and latency. Full audit trail — no black box."*

Point to:

- `cost_usd` — typically `$0.001–$0.003` per call
- `model` — shows which LLM was used (important for cost attribution)
- `latency_ms` — SLA visibility

**Hit the back button.**

---

## 3:00–5:00 — Live SAC Widget

**Switch to Tab 2** (widget-test.html or SAC story).

> *"The widget is a Custom Widget loaded inside SAC Analytics Designer. It uses SAC's Custom Widget SDK — no iframes, no workarounds."*

Point out **Pattern A** (inline render):

- Widget renders the Morning Brief text directly inside the canvas cell.
- Content is live: every page load triggers a fresh generation (or serves from the Redis cache if within TTL).

**Show Pattern B** (batch briefing in story panel):

- Side-by-side with a chart — the AI content is contextual to the selected KPI.

> *"Both patterns use the same widget code — the `renderHint` field in Studio controls which layout the widget adopts."*

![screenshot: widget-pattern-a](./img/widget-pattern-a.png)
![screenshot: widget-pattern-b](./img/widget-pattern-b.png)

---

## 5:00–6:00 — Action Enhancement Drill-Down

**Scroll to the "Why this?" button in the widget** (rendered by an action enhancement).

> *"Action enhancements add interactive buttons to the widget. Click generates a follow-up LLM call on demand."*

**Click "Why this?"**

> *"The explanation appears inline. Again — the admin chip in the result card links to the generation log."*

**Click the admin chip.**

Point out that this is a **second** log entry linked to the same widget session — showing the full chain of calls a user triggered.

---

## 6:00–7:30 — Publish Workflow + Diff Modal

**Switch back to Tab 1 (Studio). Open the Morning Brief editor.**

> *"Let's simulate what happens when a business analyst changes a prompt and tries to publish."*

**Edit the `prompt_template`** — change one word, e.g. append ` Focus on risks.` to the prompt.

**Click Publish.**

> *"Before publishing, Studio shows a diff modal. It lists every changed field."*

![screenshot: publish-diff](./img/publish-diff.png)

Point out:

- "Prompt template changed" — shown as a **warning** (yellow banner). Downstream consumers will see different text, but the interface contract is intact.

**Cancel. Now change `render_hint`** from `inline` to `panel`.

**Click Publish.**

> *"Changing the render hint IS a breaking change — the SAC story layout depends on it. Studio catches this automatically and shows a red banner."*

![screenshot: publish-breaking](./img/publish-breaking.png)

> *"This prevents silent breakage in production SAC stories. The analyst must explicitly acknowledge the impact."*

---

## 7:30–9:00 — Brain Explorer

**Click "Brain Explorer" in the top nav.**

> *"Brain Explorer visualises the knowledge graph that powers contextual enhancements. Every DspObject, Glossary term, and user interest edge is here."*

![screenshot: brain-explorer](./img/brain-explorer.png)

Point out:

- Nodes: `DspObject` (blue), `Domain` (orange), `GlossaryTerm` (green), `User` (purple)
- Edges: `DOMAIN_OF`, `RELATED_TO`, `INTERESTED_IN`

**Run a Cypher query in the query panel:**

```cypher
MATCH (d:DspObject)-[:DOMAIN_OF]->(dom:Domain)
RETURN d.id, dom.name
LIMIT 10
```

> *"This is Neo4j running inside the compose stack. The Brain Feeder service keeps it up to date every 4 hours — or on demand via the /brain/feed endpoint."*

---

## 9:00–10:00 — Library Export + Backup Story

**Click "Library" in the top nav → Export.**

> *"The entire enhancement set — prompts, render hints, cost caps, publish history — exports as a single portable JSON file."*

**Click Export JSON.** A file downloads.

> *"This is the CPG Retail bundle you're looking at right now. When we onboard the next client — different tenant, different `CUSTOMER` env var — we import this file, adjust the prompt templates for their data model, and they're live in under an hour."*

**Open a terminal. Show the backup script briefly:**

```bash
cat scripts/backup.sh
```

> *"The operator counterpart: a cron job that runs nightly and produces a tarball with the Postgres dump, Neo4j dump, Redis snapshot, and the library JSON. Full restore is a single command."*

---

## What's Next (30 seconds)

> *"Three things we didn't demo today:"*
>
> 1. **Cost guardrails** — set a `$25/month` cap per enhancement; the system auto-pauses and alerts when exceeded.
> 2. **Second tenant onboarding** — spin up the same stack with `CUSTOMER=acme`, import the bundle, done. RLS keeps data isolated at the Postgres row level.
> 3. **Offline profile** — no internet, no cloud LLM. One extra compose flag adds a bundled Ollama container with `qwen2.5:14b` running locally — identical UX, zero data leaves the network.

---

*Demo duration: ~10 minutes. For a 30-minute deep-dive, add: cost guardrail live trigger, second-tenant import walkthrough, and offline profile boot.*
