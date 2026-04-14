---
object_id: CMP_REV
object_type: composite
name: ZC_REVENUE
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# ZC_REVENUE Composite Provider

**Technical Name:** `ZC_REVENUE`  
**Type:** Composite Provider | **Space:** COMPOSITES

**Status:** — | **Owner:** DEVUSER

## Description

Composite Provider ZC_REVENUE unions aggregated revenue facts from ZADSO_REVENUE_AGG with optional ledger-based actuals. Single query layer for all revenue reporting, dashboards, and analytical tools. Consolidates billing and sub-ledger data.

## Details

- **Type**: composite
- **Package**: COMPOSITES
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| HIER_NODE | CHAR | Customer Hierarchy Node |
| MATNR | CHAR | Material Number |
| CALMONTH | DATS | Calendar Month |
| NETWR_EUR | CURR | Revenue EUR |
| MARGIN | DEC | Gross Profit Margin % |

## SQL Definition

```sql
-- Composite Provider ZC_REVENUE: Union of aggregated DSOs
CREATE VIEW ZC_REVENUE AS
  SELECT HIER_NODE, MATNR, CALMONTH, NETWR_EUR, MARGIN
  FROM ZADSO_REVENUE_AGG
  WHERE PROCESSED_FLAG = 'X'
  UNION ALL
  SELECT HIER_NODE, MATNR, CALMONTH, NETWR_EUR, MARGIN
  FROM /BIC/AREVENUE_LEDGER
  WHERE SOURCE = 'SUBLEDGER'
```

## Dependencies

### Reads From

- [`ZADSO_REVENUE_AGG`](../../adso/DSO_AGG.md) — Advanced DSO

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

