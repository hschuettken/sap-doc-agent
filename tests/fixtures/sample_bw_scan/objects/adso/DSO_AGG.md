---
object_id: DSO_AGG
object_type: adso
name: ZADSO_REVENUE_AGG
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# ZADSO_REVENUE_AGG Advanced DSO

**Technical Name:** `ZADSO_REVENUE_AGG`  
**Type:** Advanced DSO | **Space:** ADSO

**Status:** — | **Owner:** DEVUSER

## Description

Aggregated revenue facts by customer hierarchy, material, and month. Contains profitability metrics (margin %) for executive reporting and analytical cubes. Final transformation layer before consumption by reports and composites.

## Details

- **Type**: adso
- **Package**: ADSO
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| HIER_NODE | CHAR | Customer Hierarchy Node |
| MATNR | CHAR | Material Number |
| CALMONTH | DATS | Calendar Month |
| NETWR_EUR | CURR | Aggregated Revenue EUR |
| MARGIN | DEC | Gross Profit Margin % |

## SQL Definition

```sql
CREATE TABLE ZADSO_REVENUE_AGG (
  REQUEST_ID VARCHAR(20),
  RECORD_NO INT,
  HIER_NODE CHAR(10),
  MATNR CHAR(18),
  CALMONTH CHAR(8),
  NETWR_EUR DECIMAL(15,2),
  MARGIN DECIMAL(5,2),
  PROCESSED_FLAG CHAR(1)
)
```

## Dependencies

### Reads From

- [`TR_REVENUE_AGG`](../../transformation/TRAN_003.md) — Transformation

### Read By

- [`ZC_REVENUE`](../../composite/CMP_REV.md) — Composite Provider

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

