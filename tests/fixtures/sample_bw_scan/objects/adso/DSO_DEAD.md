---
object_id: DSO_DEAD
object_type: adso
name: ZADSO_LEGACY_DEAD
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# ZADSO_LEGACY_DEAD Advanced DSO (Orphaned)

**Technical Name:** `ZADSO_LEGACY_DEAD`  
**Type:** Advanced DSO | **Space:** ADSO

**Status:** Orphaned | **Owner:** DEVUSER

## Description

Orphaned DSO with no active consumers. Previously held legacy contract master data but deprecated in favor of new master data structures. Unreachable from any production query or composite. Marked for decommissioning.

## Details

- **Type**: adso
- **Package**: ADSO
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| CONTRACT_ID | CHAR | Contract ID |
| PARTNER_CODE | CHAR | Partner Code |

## SQL Definition

```sql
CREATE TABLE ZADSO_LEGACY_DEAD (
  REQUEST_ID VARCHAR(20),
  RECORD_NO INT,
  CONTRACT_ID CHAR(15),
  PARTNER_CODE CHAR(10),
  PROCESSED_FLAG CHAR(1)
)
```

## Dependencies

### Reads From

- [`TR_LEGACY_DEAD`](../../transformation/TRAN_DEAD.md) — Transformation

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

