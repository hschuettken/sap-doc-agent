# SAC Pattern B — Consuming `dsp_ai.*` natively

This guide walks through the **Pattern B** integration: dsp-ai writes
narratives into `dsp_ai.briefings` on a schedule; SAC consumes them
natively via an Analytic Model, no Custom Widget required. Pattern A
(the live widget) lands in Session B.

## 1. Install the Analytic Model view

Apply [`analytic_model_briefings.sql`](./analytic_model_briefings.sql)
inside the client's Datasphere tenant (Database Explorer → SQL
console, or via CLI):

```bash
psql "$DSP_CONNECTION_STRING" -f docs/sac/analytic_model_briefings.sql
```

This creates two read-only views — `dsp_ai.latest_briefings` and
`dsp_ai.latest_rankings` — scoped to the `dsp_ai` schema. Grant `SELECT`
to the SAC service principal (edit the GRANT block at the bottom of
the SQL to match the actual role name).

## 2. Bind as a Live Data Model

1. In the Datasphere UI, open *Data Builder* → *New Analytic Model*.
2. Source: **Local Table/View**, schema `dsp_ai`, object
   `latest_briefings`.
3. Map the SAC session variable `$user` to `user_id` (enables per-user
   rendering out of the box).
4. Expose `enhancement_name`, `context_key`, and `render_hint` as
   dimensions; `narrative_text`, `key_points`, `suggested_actions` as
   measures/attributes.
5. Save + deploy.

## 3. Bind into a SAC Story

- Add a **Rich Text** widget → data source the new Analytic Model →
  bind `narrative_text` to the widget body.
- Filter the model by `enhancement_name = 'Morning Brief — Revenue'`
  (or whichever seed you published) and `context_key = 'default'`.
- The per-user scope falls out from step 2's `$user` mapping — each
  viewer sees their own narrative.
- For key points use a **Text** list widget bound to `key_points`
  (JSON array of strings).

## 4. Verify end-to-end

1. Author a new enhancement in Spec2Sphere's AI Studio (`/ai-studio/`)
   and publish it, or rely on the bundled Morning Brief seed.
2. Wait for the next `BATCH_CRON` tick, or fire the Celery task
   manually: `celery -A spec2sphere.tasks.celery_app call
   spec2sphere.dsp_ai.run_batch_enhancements` (ops-bridge exec).
3. `SELECT count(*) FROM dsp_ai.briefings` in DSP — non-zero means
   content has arrived.
4. Refresh the SAC Story — narrative appears.

## 5. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Story shows blank | No rows yet | Run the batch task; check `dsp_ai.briefings`. |
| Only one user sees content | Session variable unmapped | Re-bind `$user` → `user_id` in the Analytic Model. |
| Stale text | Cache hit | Evict with `pg_notify('enhancement_published', …)` or wait for TTL. |
| `permission denied` on SAC refresh | Missing GRANT | Apply GRANT block on both views. |
| `column "render_hint" not found` | Old view | Re-apply the full SQL (CREATE OR REPLACE is idempotent). |

## What ships in Session B

- Pattern A Custom Widget (live rendering + SSE + telemetry).
- Ranking + callout + action + button render hints.
- `dsp_ai.latest_*` analogues for per-object enrichments.
- Studio Brain Explorer + Generation Log pages.
