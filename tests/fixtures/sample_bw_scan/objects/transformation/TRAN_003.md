---
object_id: TRAN_003
object_type: transformation
name: TR_REVENUE_AGG
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# TR_REVENUE_AGG Transformation

**Technical Name:** `TR_REVENUE_AGG`  
**Type:** Transformation | **Space:** TRANSFORMATIONS

**Status:** — | **Owner:** DEVUSER

## Description

Transformation TR_REVENUE_AGG aggregates clean revenue by customer hierarchy level and material. Resolves customer-to-hierarchy mappings via 0CUSTOMER master data, calculates gross profit margin, and produces analytical cube-ready facts.

## Details

- **Type**: transformation
- **Package**: TRANSFORMATIONS
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| HIER_NODE | CHAR | Customer Hierarchy Node |
| MATNR | CHAR | Material Number |
| CALMONTH | DATS | Calendar Month |
| NETWR_EUR | CURR | Aggregated Net Amount EUR |
| MARGIN | DEC | Gross Profit Margin % |

## Source Code

```abap
*& Transformation TR_REVENUE_AGG: Hierarchy resolution & margin calculation
*& Source: ZADSO_REVENUE_CLEAN -> ZADSO_REVENUE_AGG
*& Uses: 0CUSTOMER master data for hierarchy

INITIALIZATION.
  CLEAR RESULT_PACKAGE.

START_ROUTINE.
  " Load customer master hierarchy
  SELECT * FROM /BIC/CUSTOMER INTO TABLE t_cust_master
    WHERE OBJVERS = 'A'
      AND LANGU = 'E'.
  IF sy-subrc NE 0.
    MESSAGE W001(Z_BILLING) WITH 'Customer master partially loaded'.
  ENDIF.
  
  " Load cost data for margin calculation
  SELECT * FROM /BIC/COSTMATERIAL INTO TABLE t_cost_data.
END_ROUTINE.

FIELD_ROUTINE: HIER_NODE.
  " Resolve customer to hierarchy node
  DATA: l_hier_node TYPE /BIC/HIER_NODE.
  
  READ TABLE t_cust_master ASSIGNING FIELD-SYMBOL(<cust>)
    WITH KEY CUSTOMER = SOURCE_FIELDS-KUNNR.
  IF sy-subrc = 0.
    l_hier_node = <cust>-HIERARCHY_NODE.
  ELSE.
    l_hier_node = 'UNKNOWN'.
  ENDIF.
  
  RESULT_FIELDS-HIER_NODE = l_hier_node.

FIELD_ROUTINE: MARGIN.
  " Calculate gross margin: (Revenue - Cost) / Revenue * 100
  DATA: l_cost TYPE /BIC/COST,
        l_revenue TYPE CURRENCY,
        l_margin TYPE DEC.
  
  l_revenue = SOURCE_FIELDS-NETWR_EUR.
  
  READ TABLE t_cost_data ASSIGNING FIELD-SYMBOL(<cost>)
    WITH KEY MATNR = SOURCE_FIELDS-MATNR.
  IF sy-subrc = 0.
    l_cost = <cost>-COST_PER_UNIT.
  ELSE.
    l_cost = 0.
  ENDIF.
  
  IF l_revenue NE 0.
    l_margin = ( ( l_revenue - l_cost ) / l_revenue ) * 100.
  ELSE.
    l_margin = 0.
  ENDIF.
  
  RESULT_FIELDS-MARGIN = l_margin.

END_ROUTINE.
  LOOP AT SOURCE_PACKAGE ASSIGNING FIELD-SYMBOL(<source>).
    MOVE-CORRESPONDING <source> TO <result>.
    APPEND <result> TO RESULT_PACKAGE.
  ENDLOOP.
```

## Dependencies

### Reads From

- [`ZADSO_REVENUE_CLEAN`](../../adso/DSO_CLEAN.md) — Advanced DSO
- [`0CUSTOMER`](../../infoobject/IOBJ_CUST.md) — InfoObject

### Writes To

- [`ZADSO_REVENUE_AGG`](../../adso/DSO_AGG.md) — Advanced DSO

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

