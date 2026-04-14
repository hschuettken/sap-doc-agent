---
object_id: IOBJ_CUST
object_type: infoobject
name: 0CUSTOMER
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# 0CUSTOMER InfoObject

**Technical Name:** `0CUSTOMER`  
**Type:** InfoObject | **Space:** INFOOBJECTS

**Status:** — | **Owner:** DEVUSER

## Description

Standard SAP InfoObject for customer master data. Holds customer dimension hierarchy, classifications, and text attributes. Shared dependency across revenue and billing chains. Enables customer segmentation in reports and analytics.

## Details

- **Type**: infoobject
- **Package**: INFOOBJECTS
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| CUSTOMER | CHAR | Customer ID (Key) |
| HIERARCHY_NODE | CHAR | Hierarchy Level (Attribute) |
| CUSTOMER_NAME | CHAR | Customer Name |
| CUSTOMER_GROUP | CHAR | Customer Group Code |
| REGION | CHAR | Geographic Region |

## SQL Definition

```sql
-- InfoObject 0CUSTOMER master table
CREATE TABLE /BIC/CUSTOMER (
  CUSTOMER CHAR(10) PRIMARY KEY,
  HIERARCHY_NODE CHAR(10),
  CUSTOMER_NAME VARCHAR(80),
  CUSTOMER_GROUP CHAR(4),
  REGION CHAR(3),
  OBJVERS CHAR(1),
  LANGU CHAR(1),
  CHANGED_AT TIMESTAMP
)
```

## Dependencies

### Read By

- [`TR_REVENUE_CLEAN`](../../transformation/TRAN_002.md) — Transformation
- [`TR_REVENUE_AGG`](../../transformation/TRAN_003.md) — Transformation

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

