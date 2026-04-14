---
object_id: DS_DEAD
object_type: data_source
name: 2LIS_LEGACY
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# Legacy Data Source (Discontinued)

**Technical Name:** `2LIS_LEGACY`  
**Type:** Data Source | **Space:** DATASOURCES

**Status:** Deprecated | **Owner:** DEVUSER

## Description

Legacy data source 2LIS_LEGACY is deprecated and no longer used in active processes. Extracted contract/reference data previously used for master data. Kept for archival purposes only. All consumers migrated to newer sources.

## Details

- **Type**: data_source
- **Package**: DATASOURCES
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| CONTRACT_ID | CHAR | Contract ID |
| PARTNER_CODE | CHAR | Partner Code |
| LEGACY_FLAG | CHAR | Deprecated Mark |

## SQL Definition

```sql
-- Legacy extractor for 2LIS_LEGACY (DEPRECATED)
SELECT
  CONTRACT_ID,
  PARTNER_CODE,
  'X' AS LEGACY_FLAG
FROM EKKO_LEGACY
WHERE STATUS = 'ARCHIVED'
```

## Dependencies

### Read By

- [`TR_DEAD`](../../transformation/TRAN_DEAD.md) — Transformation

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

