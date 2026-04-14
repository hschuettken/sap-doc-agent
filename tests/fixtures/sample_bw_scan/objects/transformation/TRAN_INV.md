---
object_id: TRAN_INV
object_type: transformation
name: TR_INVENTORY
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# TR_INVENTORY Transformation

**Technical Name:** `TR_INVENTORY`  
**Type:** Transformation | **Space:** TRANSFORMATIONS

**Status:** — | **Owner:** DEVUSER

## Description

Transformation TR_INVENTORY performs simple 1:1 mapping of inventory data from source to DSO. Light-weight pass-through transformation without aggregation or enrichment. Entry point for inventory reporting chain.

## Details

- **Type**: transformation
- **Package**: TRANSFORMATIONS
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

## Source Code

```abap
*& Transformation TR_INVENTORY: 1:1 pass-through to inventory DSO
*& Source: 2LIS_03_BF -> ZADSO_INVENTORY

INITIALIZATION.
  LOOP AT SOURCE_PACKAGE INTO ls_source.
    " Simple 1:1 mapping
    MOVE-CORRESPONDING ls_source TO ls_result.
    APPEND ls_result TO RESULT_PACKAGE.
  ENDLOOP.
```

## Dependencies

### Reads From

- [`2LIS_03_BF`](../../data_source/DS_INVENTORY.md) — Data Source

### Writes To

- [`ZADSO_INVENTORY`](../../adso/DSO_INV.md) — Advanced DSO

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

