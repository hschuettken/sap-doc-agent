---
object_id: TRAN_001
object_type: transformation
name: TR_BILLING_RAW
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# TR_BILLING_RAW Transformation

**Technical Name:** `TR_BILLING_RAW`  
**Type:** Transformation | **Space:** TRANSFORMATIONS

**Status:** — | **Owner:** DEVUSER

## Description

Transformation TR_BILLING_RAW filters incoming billing data from data source 2LIS_11_VAITM. Excludes test orders (AUART != 'ZT'), maps source fields to raw DSO. Entry point for billing data pipeline.

## Details

- **Type**: transformation
- **Package**: TRANSFORMATIONS
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| AUART | CHAR | Sales Document Type |
| KUNNR | CHAR | Customer Number |
| MATNR | CHAR | Material Number |
| NETWR | CURR | Net Amount |
| WAERS | CHAR | Currency Code |
| BUKRS | CHAR | Company Code |

## Source Code

```abap
*& Transformation TR_BILLING_RAW: Filter test orders, map to raw DSO
*& Source: 2LIS_11_VAITM -> ZADSO_BILLING_RAW

INITIALIZATION.
  LOOP AT SOURCE_PACKAGE INTO ls_source.
    " Filter: exclude test document type ZT
    IF ls_source-AUART = 'ZT'.
      CONTINUE.
    ENDIF.
    
    " Map to result structure
    ls_result-AUART = ls_source-AUART.
    ls_result-KUNNR = ls_source-KUNNR.
    ls_result-MATNR = ls_source-MATNR.
    ls_result-NETWR = ls_source-NETWR.
    ls_result-WAERS = ls_source-WAERS.
    ls_result-BUKRS = ls_source-BUKRS.
    
    APPEND ls_result TO RESULT_PACKAGE.
  ENDLOOP.
```

## Dependencies

### Reads From

- [`2LIS_11_VAITM`](../../data_source/DS_BILLING.md) — Data Source

### Writes To

- [`ZADSO_BILLING_RAW`](../../adso/DSO_RAW.md) — Advanced DSO

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

