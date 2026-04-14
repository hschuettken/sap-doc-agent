---
object_id: DSO_INV
object_type: adso
name: ZADSO_INVENTORY
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# ZADSO_INVENTORY Advanced DSO

**Technical Name:** `ZADSO_INVENTORY`  
**Type:** Advanced DSO | **Space:** ADSO

**Status:** — | **Owner:** DEVUSER

## Description

Inventory stock balances by plant and material. Stores daily snapshot of unrestricted stock quantities for supply chain analytics. Supports inventory aging, turnover ratio, and safety stock analysis.

## Details

- **Type**: adso
- **Package**: ADSO
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| MATNR | CHAR | Material Number |
| WERKS | CHAR | Plant Code |
| LABST | QUAN | Unrestricted Stock Quantity |
| CALDAY | DATS | Stock Count Date |

## SQL Definition

```sql
CREATE TABLE ZADSO_INVENTORY (
  REQUEST_ID VARCHAR(20),
  RECORD_NO INT,
  MATNR CHAR(18),
  WERKS CHAR(4),
  LABST DECIMAL(13,3),
  CALDAY CHAR(8),
  PROCESSED_FLAG CHAR(1)
)
```

## Dependencies

### Reads From

- [`TR_INVENTORY`](../../transformation/TRAN_INV.md) — Transformation

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

