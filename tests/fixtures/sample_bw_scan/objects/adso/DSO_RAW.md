---
object_id: DSO_RAW
object_type: adso
name: ZADSO_BILLING_RAW
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# ZADSO_BILLING_RAW Advanced DSO

**Technical Name:** `ZADSO_BILLING_RAW`  
**Type:** Advanced DSO | **Space:** ADSO

**Status:** — | **Owner:** DEVUSER

## Description

Raw staging area for billing line items. Stores unfiltered, unmapped data from billing data source before currency conversion and enrichment. Serves as single source of truth for historical billing facts.

## Details

- **Type**: adso
- **Package**: ADSO
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| KUNNR | CHAR | Customer Number |
| MATNR | CHAR | Material Number |
| NETWR | CURR | Net Amount (Original Currency) |
| WAERS | CHAR | Currency Code |
| BUKRS | CHAR | Company Code |
| AUART | CHAR | Sales Document Type |

## SQL Definition

```sql
CREATE TABLE ZADSO_BILLING_RAW (
  REQUEST_ID VARCHAR(20),
  RECORD_NO INT,
  KUNNR CHAR(10),
  MATNR CHAR(18),
  NETWR DECIMAL(15,2),
  WAERS CHAR(3),
  BUKRS CHAR(4),
  AUART CHAR(4),
  PROCESSED_FLAG CHAR(1)
)
```

## Dependencies

### Reads From

- [`TR_BILLING_RAW`](../../transformation/TRAN_001.md) — Transformation

### Read By

- [`TR_REVENUE_CLEAN`](../../transformation/TRAN_002.md) — Transformation

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

