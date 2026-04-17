# CPG/Retail Reference Enhancement Library

A production-ready library of 8 AI enhancements for Consumer Packaged Goods (CPG) and Retail operations. All enhancements are fully validated against the `EnhancementConfig` schema and include sample SQL/Cypher queries for immediate adaptation.

## Overview

This library covers the five enhancement kinds with realistic CPG use cases:

- **2 Briefing** enhancements: Morning revenue brief, weekly sell-through analysis, supplier scorecard
- **2 Ranking** enhancements: Stock urgency ranking, category KPI heatmap
- **1 Narrative** enhancement: Post-promo lift summary
- **1 Action** enhancement: Price anomaly explainer (click-to-explain)
- **1 Item Enrich** enhancement: SKU description refiner (bulk master data enrichment)

## Quick Start

```bash
# 1. Start the services
cp .env.example .env
docker compose up -d
# Wait 30 seconds for services to come up

# 2. Import the library
curl -X POST http://localhost:8260/ai-studio/library/import \
     -F "file=@libraries/cpg_retail/export.json" \
     -F "mode=merge"

# 3. Test an enhancement (e.g., Morning Brief)
curl -X POST http://localhost:8260/ai-studio/enhancements/run \
     -H "Content-Type: application/json" \
     -d '{
       "name": "CPG Morning Brief — Revenue",
       "mode": "preview",
       "user_id": "demo_user",
       "user_state": {"time_bucket": "morning"}
     }'
```

## Adapting to Your Tenant

Each enhancement uses **public table names** as placeholders. To connect to your actual data:

1. **Identify your schema**: Map your tables to the generic names below
2. **Update dsp_query**: Replace table/column names in each enhancement's `bindings.data.dsp_query`
3. **Update cypher queries**: Adapt Neo4j patterns if your graph uses different node/relationship names
4. **Update searxng_query**: Customize Jinja templates for your domain (e.g., replace "cpg revenue" with your product category)

### Generic Table Schema

Adapt these to your actual table/column names:

- **sales**: order_date, region, amount, sku, category
- **stock_level**: date, sku, category, units_sold, inventory_available, current_stock, projected_daily_demand
- **price_changes**: price_change_id, sku, category, region, current_price, previous_price, price_delta_pct, price_change_date, avg_regional_price
- **promotions**: promo_id, campaign_name, start_date, end_date, promo_revenue, baseline_revenue, promo_units, baseline_units, sku
- **category_metrics**: date, category, revenue, gross_margin_pct, sku, units, return_rate_pct
- **suppliers**: supplier_id, supplier_name, last_order_date, on_time_delivery_pct, quality_score, lead_time_days, order_id
- **sku_master**: sku, category, current_title, current_description, ingredients, net_weight, uom, last_updated

## Per-Enhancement Notes

### 1. CPG Morning Brief — Revenue
**Kind**: briefing | **Mode**: batch | **TTL**: 1 hour

Daily summary of regional revenue trends. Combines 7-day sales data with market news context. Suitable for daily email or morning dashboard briefing.

**Dependencies**: `sales` table with regional aggregation

---

### 2. Weekly Sell-Through Analysis
**Kind**: briefing | **Mode**: batch | **TTL**: 7 days

Identifies fast-moving (>80% sell-through) and slow-moving (<20% sell-through) SKUs. Suggests replenishment or clearance actions. Ideal for inventory planning meetings.

**Dependencies**: `stock_level` table; recommend weekly schedule

---

### 3. Stock Urgency Ranking
**Kind**: ranking | **Mode**: live | **Cost Cap**: $5.00 | **TTL**: 30 minutes

Real-time ranking of SKUs at stockout risk. Computes days-of-cover from projected demand. Triggers urgent replenishment workflows.

**Dependencies**: `stock_level` table; Cypher graph of supplier lead times; **live mode**: expect 3-5s latency

---

### 4. Price Anomaly Explainer
**Kind**: action | **Mode**: live | **TTL**: 1 hour

Click-to-explain widget for price changes. Accepts `anomaly_id` parameter, fetches the price record, and generates explanation context (regional averages, competitive pressure, seasonal factors).

**Dependencies**: `price_changes` table; `price_point` Neo4j nodes with regional aggregates; requires parameterized SQL

---

### 5. Promo Lift Post-Analysis
**Kind**: narrative | **Mode**: batch | **TTL**: 24 hours

Retrospective narrative summarizing campaign performance. Calculates revenue and unit lift vs. baseline, identifies top SKUs, comments on ROI.

**Dependencies**: `promotions` table with baseline_revenue / baseline_units columns

---

### 6. Category KPI Heatmap
**Kind**: ranking | **Mode**: batch | **TTL**: 30 days

Ranks top 5 metrics per category that need attention (margin erosion, return spike, volume drop). Renders as chart-compatible ranked list with scores.

**Dependencies**: `category_metrics` table; weekly aggregation recommended

---

### 7. Supplier Scorecard
**Kind**: briefing | **Mode**: batch | **TTL**: 7 days

Health dashboard across all suppliers. Scores on-time delivery, quality, lead time. Recommends review meetings or escalations based on performance.

**Dependencies**: `suppliers` table with last 30 days of order-level metrics; Neo4j graph mapping suppliers to SKUs

---

### 8. SKU Description Refiner
**Kind**: item_enrich | **Mode**: batch | **TTL**: 30 days

Bulk master data enrichment. Generates richer product titles, detailed descriptions, and tags from ingredients, weight, and attributes. Outputs suggested changes for manual review before publishing.

**Dependencies**: `sku_master` table; optional `Sku` Neo4j nodes with attributes

---

## Library Format

All enhancements are bundled in `export.json` in the standard library format:

```json
{
  "version": "1.0",
  "exported_at": "2026-04-17T20:19:12Z",
  "customer": "cpg_retail_reference",
  "enhancements": [
    {
      "name": "...",
      "kind": "...",
      "version": 1,
      "status": "draft",
      "config": { ... }
    }
  ]
}
```

Import via the `/ai-studio/library/import` endpoint with `mode=merge` to add to existing enhancements.

## Validation

All 8 seeds and export.json pass EnhancementConfig validation:

```bash
# Validate all seeds
.venv/bin/python -c "
import json, pathlib
from spec2sphere.dsp_ai.config import EnhancementConfig
for p in sorted(pathlib.Path('libraries/cpg_retail').glob('0*.json')):
    blob = json.loads(p.read_text())
    EnhancementConfig.model_validate(blob)
    print(f'OK {p.name}')
"

# Validate export.json
.venv/bin/python -c "
import json, pathlib
from spec2sphere.dsp_ai.config import EnhancementConfig
blob = json.loads(pathlib.Path('libraries/cpg_retail/export.json').read_text())
for e in blob['enhancements']:
    EnhancementConfig.model_validate(e['config'])
print('✓ export.json ok')
"
```

## License & Attribution

Reference library for Spec2Sphere DSP-AI. Adapt freely for your CPG/Retail tenant. No external dependencies.
