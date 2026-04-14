---
object_id: DSO_CLEAN
object_type: adso
name: ZADSO_REVENUE_CLEAN
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# ZADSO_REVENUE_CLEAN Advanced DSO

**Technical Name:** `ZADSO_REVENUE_CLEAN`  
**Type:** Advanced DSO | **Space:** ADSO

**Status:** — | **Owner:** DEVUSER

## Description

Clean revenue dataset with standardized amounts in EUR and monthly partitioning. Intermediate layer between raw billing extraction and analytical aggregation. Ensures consistent currency and date formats across all downstream reports.

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
| NETWR_EUR | CURR | Net Amount in EUR |
| CALMONTH | DATS | Calendar Month (YYYYMM01) |

## SQL Definition

```sql
CREATE TABLE ZADSO_REVENUE_CLEAN (
  REQUEST_ID VARCHAR(20),
  RECORD_NO INT,
  KUNNR CHAR(10),
  MATNR CHAR(18),
  NETWR_EUR DECIMAL(15,2),
  CALMONTH CHAR(8),
  PROCESSED_FLAG CHAR(1)
)
```

## Dependencies

### Reads From

- [`TR_REVENUE_CLEAN`](../../transformation/TRAN_002.md) — Transformation

### Read By

- [`TR_REVENUE_AGG`](../../transformation/TRAN_003.md) — Transformation

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

