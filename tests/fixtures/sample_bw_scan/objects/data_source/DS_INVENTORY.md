---
object_id: DS_INVENTORY
object_type: data_source
name: 2LIS_03_BF
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# Inventory Balances Data Source

**Technical Name:** `2LIS_03_BF`  
**Type:** Data Source | **Space:** DATASOURCES

**Status:** — | **Owner:** DEVUSER

## Description

Data source 2LIS_03_BF extracts inventory/stock balance data from material management (MM) module. Provides plant-level, material-level inventory quantities and monetary values for inventory analytics.

## Details

- **Type**: data_source
- **Package**: DATASOURCES
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
-- Data source extractor for 2LIS_03_BF (Inventory Balances)
SELECT
  MATNR,
  WERKS,
  LABST,
  CALDAY
FROM MSLB
WHERE BUDAT >= :last_extraction_date
```

## Dependencies

*(No dependencies recorded)*

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

