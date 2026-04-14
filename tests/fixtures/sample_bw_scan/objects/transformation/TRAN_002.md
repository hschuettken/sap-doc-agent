---
object_id: TRAN_002
object_type: transformation
name: TR_REVENUE_CLEAN
source_system: BW4
layer: ""
owner: DEVUSER
scanned_at: "2026-04-14T10:00:00Z"
---

# TR_REVENUE_CLEAN Transformation

**Technical Name:** `TR_REVENUE_CLEAN`  
**Type:** Transformation | **Space:** TRANSFORMATIONS

**Status:** — | **Owner:** DEVUSER

## Description

Transformation TR_REVENUE_CLEAN performs currency conversion (USD→EUR via TCURR lookup) and extracts calendar month from document date (BUDAT). Produces clean, standardized revenue dataset ready for aggregation.

## Details

- **Type**: transformation
- **Package**: TRANSFORMATIONS
- **Owner**: DEVUSER
- **Layer**: 
- **Source System**: BW4

## Columns

| Column | Type | Description |
|--------|------|-------------|
| KUNNR | CHAR | Customer Number |
| MATNR | CHAR | Material Number |
| NETWR_EUR | CURR | Net Amount in EUR |
| CALMONTH | DATS | Calendar Month |

## Source Code

```abap
*& Transformation TR_REVENUE_CLEAN: Currency conversion & date extraction
*& Source: ZADSO_BILLING_RAW -> ZADSO_REVENUE_CLEAN
*& Uses: TCURR for FX lookups, 0CUSTOMER master data

INITIALIZATION.
  " Empty result package
  CLEAR RESULT_PACKAGE.

START_ROUTINE.
  " Load exchange rates for today
  SELECT * FROM TCURR INTO TABLE t_rates
    WHERE KURST = 'M'
      AND FROMCURR = 'USD'
      AND TOCURR = 'EUR'
      AND GDATU >= SY-DATUM.
  IF sy-subrc NE 0.
    MESSAGE E001(Z_BILLING) WITH 'Exchange rates not found'.
  ENDIF.
END_ROUTINE.

FIELD_ROUTINE: NETWR_EUR.
  " Convert original amount to EUR using TCURR
  DATA: l_rate TYPE tcurr-ukurs,
        l_exch_date TYPE tcurr-gdatu.
  
  l_exch_date = SOURCE_FIELDS-BUDAT.
  
  " Lookup rate
  READ TABLE t_rates ASSIGNING FIELD-SYMBOL(<rate>)
    WITH KEY gdatu = l_exch_date.
  IF sy-subrc = 0.
    l_rate = <rate>-ukurs.
  ELSE.
    " Use latest available rate
    READ TABLE t_rates INDEX 1 ASSIGNING FIELD-SYMBOL(<latest_rate>).
    l_rate = <latest_rate>-ukurs.
  ENDIF.
  
  RESULT_FIELDS-NETWR_EUR = SOURCE_FIELDS-NETWR / l_rate.

FIELD_ROUTINE: CALMONTH.
  " Extract calendar month from BUDAT (YYYYMMDD)
  RESULT_FIELDS-CALMONTH = SOURCE_FIELDS-BUDAT+0(6) && '01'.

END_ROUTINE.
  LOOP AT SOURCE_PACKAGE ASSIGNING FIELD-SYMBOL(<source>).
    MOVE-CORRESPONDING <source> TO <result>.
    APPEND <result> TO RESULT_PACKAGE.
  ENDLOOP.
```

## Dependencies

### Reads From

- [`ZADSO_BILLING_RAW`](../../adso/DSO_RAW.md) — Advanced DSO
- [`0CUSTOMER`](../../infoobject/IOBJ_CUST.md) — InfoObject

### Writes To

- [`ZADSO_REVENUE_CLEAN`](../../adso/DSO_CLEAN.md) — Advanced DSO

## Screenshots

*(Screenshots populated by deep scan)*

## Metadata

*(No additional metadata)*

