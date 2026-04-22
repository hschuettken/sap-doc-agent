# CPG/Retail Reference Enhancement Library

A ready-to-import library of 8 AI enhancements for Consumer Packaged Goods (CPG) and Retail
customers running SAP DSP / BW / ECC.

## Quick start

```bash
# 1. Bring up a fresh Spec2Sphere instance
docker compose up -d

# 2. Wait for services to be healthy
until curl -fs http://localhost:8260/api/health > /dev/null; do sleep 2; done

# 3. Import this library
curl -fs -X POST http://localhost:8260/ai-studio/library/import \
     -F "file=@libraries/cpg_retail/export.json" \
     -F "mode=merge"

# 4. Open the Studio and customise the DSP queries for your tenant
open http://localhost:8260/ai-studio/
```

## Enhancements

| # | Name | Kind | Render hint | Schedule |
|---|------|------|-------------|----------|
| 01 | CPG Morning Brief — Revenue | briefing | brief | batch/daily |
| 02 | CPG Weekly Sell-Through | briefing | brief | Mon 06:00 |
| 03 | CPG Out-of-Stock Ranking | ranking | ranked_list | hourly |
| 04 | CPG Price Anomaly Explainer | action | callout | on-click |
| 05 | CPG Promo Lift Summary | narrative | narrative_text | monthly |
| 06 | CPG Category Heatmap KPIs | ranking | ranked_list | weekly |
| 07 | CPG Supplier Scorecard | briefing | brief | Mon 07:00 |
| 08 | CPG SKU Description Refiner | item_enrich | narrative_text | batch |

## Customisation

Each enhancement has a `bindings.data.dsp_query` that targets SAP standard tables
(VBAP, MARA, MAKT, EKKO, LFA1, etc.). Before publishing, update:

1. **Table names** — if using BW InfoProviders or custom views, replace `/BIC/…` references.
2. **Parameters** — adjust `price_min/max` in the price anomaly explainer.
3. **Schedules** — the `schedule` field is a cron expression; adjust to your timezone.
4. **Prompt templates** — localise terminology and output length to your audience.

All enhancements are imported as **draft** by default via `mode=merge`. Publish them one
by one from the AI Studio after verifying preview output against your live DSP system.
