---
object_id: TRAN_DEAD
object_type: transformation
name: TR_LEGACY_DEAD
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# TR_LEGACY_DEAD Transformation (Orphaned)

**Technical Name:** `TR_LEGACY_DEAD`  
**Type:** Transformation | **Space:** TRANSFORMATIONS

**Status:** Orphaned | **Owner:** DEVUSER

## Description

Orphaned transformation TR_LEGACY_DEAD feeds deprecated DSO_DEAD. No active consumers. Exists in metadata but unreachable from any production reports or dashboards. Candidate for decommission audit.

## Details

- **Type**: transformation
- **Package**: TRANSFORMATIONS
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| CONTRACT_ID | CHAR | Contract ID |
| PARTNER_CODE | CHAR | Partner Code |

## Source Code

```abap
*& Transformation TR_LEGACY_DEAD: ORPHANED - No active consumers
*& Source: 2LIS_LEGACY -> DSO_DEAD (DEPRECATED)

INITIALIZATION.
  MESSAGE W001(Z_ARCHIVE) WITH 'TR_LEGACY_DEAD is orphaned'.
  LOOP AT SOURCE_PACKAGE INTO ls_source.
    MOVE-CORRESPONDING ls_source TO ls_result.
    APPEND ls_result TO RESULT_PACKAGE.
  ENDLOOP.
```

## Dependencies

### Reads From

- [`2LIS_LEGACY`](../../data_source/DS_DEAD.md) — Data Source

### Writes To

- [`DSO_DEAD`](../../adso/DSO_DEAD.md) — Advanced DSO

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

