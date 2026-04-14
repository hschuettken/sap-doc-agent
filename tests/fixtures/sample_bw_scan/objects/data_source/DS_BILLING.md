---
object_id: DS_BILLING
object_type: data_source
name: 2LIS_11_VAITM
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# SD Billing Items Data Source

**Technical Name:** `2LIS_11_VAITM`  
**Type:** Data Source | **Space:** DATASOURCES

**Status:** — | **Owner:** DEVUSER

## Description

Data source 2LIS_11_VAITM extracts sales and distribution (SD) billing line item data from SAP ERP. Provides core transaction facts: customer, material, net amount, currency, company code.

## Details

- **Type**: data_source
- **Package**: DATASOURCES
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| AUART | CHAR | Sales Document Type |
| KUNNR | CHAR | Customer Number |
| MATNR | CHAR | Material Number |
| NETWR | CURR | Net Amount (Original Currency) |
| WAERS | CHAR | Currency Code |
| BUKRS | CHAR | Company Code |
| BUDAT | DATS | Document Date |

## SQL Definition

```sql
-- Data source extractor for 2LIS_11_VAITM (SD Billing)
SELECT
  AUART,
  KUNNR,
  MATNR,
  NETWR,
  WAERS,
  BUKRS,
  BUDAT
FROM VBRP
WHERE ERDAT >= :last_extraction_date
```

## Dependencies

*(No dependencies recorded)*

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

