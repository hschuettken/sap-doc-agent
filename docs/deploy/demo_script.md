# Spec2Sphere — 10-Minute Demo Script

Target audience: DSP/SAC project team + business stakeholders.
Prerequisite: `demo_bootstrap.sh` completed successfully.

---

## 0:00–1:00 — AI Studio Overview

Open `http://localhost:8260/ai-studio/`.

**Say:** "This is the AI Studio — the authoring workspace where your team creates AI
enhancements that run directly inside your SAP Analytics Cloud stories. Each enhancement
here is a live AI service: it fetches data from DSP, reasons over it, and returns
structured output that SAC can consume."

Point to the table: show 3 published enhancements (Morning Brief, Out-of-Stock Ranking,
Supplier Scorecard).

---

## 1:00–3:00 — Edit and Preview an Enhancement

Click the **Morning Brief — Revenue** row → Edit.

**Show:** The split-pane editor:
- Left: JSON config (prompt template, DSP query, render hint)
- Right: live preview panel

Tweak one word in the prompt template. Click **Preview**. Show the result loading.

**Say:** "Preview runs the full 7-stage engine: fetches real data from DSP, queries the
Brain knowledge graph, runs it through the quality router, and returns a structured brief.
This is what SAC will display to your users every morning."

Point to the **provenance bar** at the bottom: model, latency, cost.

---

## 3:00–5:00 — SAC Widget and Pattern B

Open a Horváth SAC story in a second tab.

**Say:** "There are two integration patterns. Pattern B writes results directly into DSP
schema tables — SAC's native data binding picks them up with zero custom code. Pattern A
is the SAC Custom Widget: a lightweight web component that calls the engine live,
right inside the story."

Show the widget rendering next to a SAC chart. Point to the amber stale badge if data
is older than the TTL.

---

## 5:00–6:00 — Why This? / Generation Log

In the widget, click the **⚙ admin chip** (top-right, visible to authors).

A new tab opens: the Generation Log detail for this output.

**Say:** "Every AI output is traceable. You can see exactly which model was used, how
many tokens, what the cost was, and which Brain nodes fed the reasoning. This is your
AI audit trail."

Click **Brain graph** link — show the 1-hop Brain expansion of input objects.

---

## 6:00–7:30 — Publish with Diff Preview

Back in AI Studio, change the `render_hint` from `brief` to `ranked_list` on the
Morning Brief. Click **Publish**.

A diff modal appears:

- "Render hint: 'brief' → 'ranked_list'. SAC story widgets may need re-binding."
- Red banner: **Breaking change detected**

**Say:** "Before any publish, you see exactly what changes — and whether they'll break
existing SAC stories. The team can confirm or cancel. This prevents silent regressions
in production dashboards."

Confirm the publish. Show the status flipping to `published`.

---

## 7:30–9:00 — Brain Explorer

Navigate to AI Studio → **Brain Explorer**.

Run the pre-loaded Cypher: `MATCH (o:DspObject)-[:DOMAIN_OF]->(d:Domain) RETURN o, d LIMIT 50`.

The vis-network graph renders DSP objects and their domain relationships.

**Say:** "This is the semantic knowledge layer. The Brain learns from every scan: object
relationships, usage patterns, glossary terms. Enhancements use this to give context-aware
responses — not just what the numbers are, but what they mean."

---

## 9:00–10:00 — Library Export (Portability)

Navigate to AI Studio → **Library** → **Export library**.

A JSON file downloads.

**Say:** "This is the portability story. Everything we've configured — all 8 enhancements,
their queries, prompts, schemas — is in this file. To bring Spec2Sphere to your next
client, you hand them the repo, import this file, point it at their DSP, and they're
producing AI-enhanced analytics in 30 minutes."

Show the import form. Explain merge/replace/draftify modes.

---

## Close

**Say:** "To summarise: Spec2Sphere connects your SAP data layer to modern AI in a way
that is auditable, cost-controlled, and portable. You author enhancements once, they run
everywhere — in SAC stories, in your morning email, in Copilot for M365."

Questions?
