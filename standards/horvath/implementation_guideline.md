# Horvath Implementation Guideline
## SAP Datasphere and BW/4HANA Projects

**Version:** 2.0  
**Status:** Mandatory  
**Applies to:** All Horvath project teams working on SAP Datasphere (DSP) and BW/4HANA implementations  
**Review cycle:** Annually or after major platform release

---

## Table of Contents

1. [4-Layer Architecture](#1-4-layer-architecture)
2. [Naming Conventions](#2-naming-conventions)
3. [SQL Coding Standards](#3-sql-coding-standards)
4. [ABAP Coding Standards](#4-abap-coding-standards)
5. [Data Modeling Rules](#5-data-modeling-rules)
6. [Performance Guidelines](#6-performance-guidelines)
7. [Transport and Deployment](#7-transport-and-deployment)
8. [Security and Authorization](#8-security-and-authorization)
9. [Testing Requirements](#9-testing-requirements)
10. [Change Management](#10-change-management)
11. [Common Anti-Patterns](#11-common-anti-patterns)

---

## 1. 4-Layer Architecture

Every object in the data platform is assigned to exactly one of four layers. Layer assignment is not optional and must be documented. Objects that span layers — or that are placed in the wrong layer — cause maintenance debt and data quality issues that compound over time.

### Layer Definitions

#### Layer 01: RAW

The RAW layer is the landing zone. Its sole responsibility is to store data as close to the source as possible with minimal transformation. The RAW layer is the single source of truth for historical source data and must never be rebuilt from downstream layers.

**What goes here:**
- Replication flows (DSP) writing to local tables
- ODP extractors writing to ADSOs in full or delta mode
- Remote tables pointing to source systems (read-only, never persisted)
- SLT-replicated tables
- File uploads (CSV/Excel) before any cleansing

**Persistence strategy:** Always persist. RAW tables must be snapshots you can replay from. In-memory RAW objects are only acceptable for remote tables used as pass-through to HARMONIZED.

**Allowed transformations:**
- Type casting only when the source system forces it (e.g., VARCHAR dates from ERP)
- Addition of technical columns: `LOAD_TIMESTAMP`, `SOURCE_SYSTEM`, `BATCH_ID`
- No business logic. No derived columns. No joins to master data.

**Not allowed:**
- Joins between source systems
- Calculated key figures
- Business rule application
- Filtering records that "look wrong"

#### Layer 02: HARMONIZED

The HARMONIZED layer integrates data from one or more RAW sources, applies business rules, and produces a canonical model that is independent of any single reporting requirement.

**What goes here:**
- Business-key aligned views or fact tables
- Master data joins (e.g., material text, cost center hierarchy)
- Currency conversion (if consistent across all consumers)
- Data type normalization (VARCHAR dates converted to DATE)
- Lookup tables for code-to-description mappings

**Persistence strategy:** Persist for large volumes or when multiple MART layers read the same harmonized output. Keep in-memory when the HARMONIZED layer is a pure transformation view feeding a single MART.

**Allowed transformations:**
- Business key alignment across source systems
- Null handling and default value assignment
- Date normalization
- Code mapping (material type codes to descriptions)
- Calculation of technical derived fields used across multiple marts (e.g., fiscal period)

**Not allowed:**
- Report-specific aggregations
- KPI definitions that belong to a single business domain
- Hardcoded filter criteria that exclude valid business data

#### Layer 03: MART

The MART layer is domain-specific. It contains the pre-aggregated or pre-joined data that supports a specific analytical domain (Finance, Logistics, HR, etc.). Each MART is owned by a business domain team and may make assumptions about the data that are valid only for that domain.

**What goes here:**
- Pre-aggregated fact views or tables
- Domain-specific KPI calculations
- Slowly changing dimension handling (SCD Type 2 resolution)
- Domain joins that would not make sense in HARMONIZED

**Persistence strategy:** Persist all MART fact tables. Do not expect downstream consumers to wait for a chain of in-memory views to resolve at query time. Exception: thin calculation views over a persisted MART are acceptable if they add only calculated columns.

**Allowed transformations:**
- All HARMONIZED transformations plus domain-specific business logic
- Aggregation to reporting grain
- SCD resolution to current or as-of-date snapshot

#### Layer 04: CONSUMPTION

The CONSUMPTION layer exposes data to reporting tools, APIs, or downstream systems. Objects here are shaped for the consumer, not for the platform's internal logic.

**What goes here:**
- Analytic models (DSP) / CompositeProviders (BW)
- Virtual tables for SAC consumption
- API-exposed views for external consumers
- Data export structures

**Persistence strategy:** Never persist CONSUMPTION layer objects unless forced by an external tool's requirement. CONSUMPTION is read-through. Caching is handled by the reporting tool.

**Allowed transformations:**
- Renaming columns for business user readability
- Adding input parameters for date range filtering
- Restricting access via data access controls
- Adding measure definitions and aggregation semantics for analytic models

### Layer Decision Table

| Scenario | Layer |
|---|---|
| Raw ERP table landed via SLT | RAW |
| ADSO loaded from ODP extractor, no transformation | RAW |
| View joining two RAW tables with fiscal period derivation | HARMONIZED |
| Material master text table join | HARMONIZED |
| Revenue per customer per month pre-aggregated | MART |
| Gross margin calculation for Finance domain | MART |
| Analytic model exposed to SAC | CONSUMPTION |
| CompositeProvider joining MART and a dimension | CONSUMPTION |

---

## 2. Naming Conventions

Names must encode: layer assignment, object type, and subject area. Every name must be readable without opening the object. The project may define a customer namespace prefix (e.g., `Z`, `Y`, or a 3-letter client abbreviation) which prepends the pattern below.

### DSP — Naming Reference

#### Local Tables

| Layer | Pattern | Example |
|---|---|---|
| RAW | `LT_<SUBJECT>_<ENTITY>` | `LT_FI_GL_ITEMS` |
| HARMONIZED | `LT_HARM_<SUBJECT>_<ENTITY>` | `LT_HARM_FI_POSTINGS` |
| MART | `LT_MART_<DOMAIN>_<ENTITY>` | `LT_MART_CO_REVENUE` |

#### Remote Tables

Always prefix with `RT_`. Remote tables are never renamed to omit the `RT_` prefix — this makes it immediately clear in lineage tools that the object is a live connection, not a persisted copy.

Pattern: `RT_<SOURCE_SYSTEM>_<ENTITY>`  
Example: `RT_S4H_BKPF`, `RT_S4H_EKKO`, `RT_LEGACY_ORDERS`

#### Replication Flows

Pattern: `RF_<SOURCE_SYSTEM>_<SUBJECT>_<ENTITY>`  
Example: `RF_S4H_FI_GL_ITEMS`, `RF_S4H_MM_EKKO`

One replication flow per entity. Do not bundle unrelated entities in a single flow.

#### Graphical Views (DSP)

| Layer | Pattern | Example |
|---|---|---|
| RAW | `RV_<SUBJECT>_<ENTITY>` | `RV_FI_GL_HEADER` |
| HARMONIZED | `HV_<SUBJECT>_<ENTITY>` | `HV_FI_POSTINGS_ENRICHED` |
| MART | `FV_<DOMAIN>_<ENTITY>` | `FV_CO_MARGIN_MONTHLY` |
| Dimension/Master Data | `MD_<ENTITY>` | `MD_COSTCENTER`, `MD_MATERIAL` |

#### SQL Views (DSP)

Same layer prefix logic as graphical views, but append `_SQL` to distinguish:  
`HV_FI_POSTINGS_SQL`, `FV_CO_MARGIN_SQL`

#### Transformation Flows (DSP)

Pattern: `TF_<SOURCE_LAYER>_<TARGET_ENTITY>`  
Example: `TF_RAW_TO_HARM_FI_POSTINGS`, `TF_HARM_TO_MART_CO_REVENUE`

#### Task Chains (DSP)

Pattern: `TC_<DOMAIN>_<DESCRIPTION>`  
Example: `TC_FI_DAILY_LOAD`, `TC_CO_MONTHLY_CLOSE`

#### Analytic Models (DSP)

Pattern: `AM_<DOMAIN>_<SUBJECT>`  
Example: `AM_FI_PROFITABILITY`, `AM_CO_COSTCENTER_ANALYSIS`

#### Data Access Controls (DSP)

Pattern: `DAC_<ENTITY>_<RESTRICTION_TYPE>`  
Example: `DAC_COMPANYCODE_ROW`, `DAC_COSTCENTER_ROW`

### BW/4HANA — Naming Reference

#### ADSOs (Advanced DSOs)

| Type | Pattern | Example |
|---|---|---|
| Write-optimized (RAW) | `0<NS>W<SUBJECT><SEQ>` | `0ZFW_GLITEMS01` |
| Standard (HARMONIZED) | `0<NS>S<SUBJECT><SEQ>` | `0ZFS_GLITEMS01` |
| Direct-update (lookup) | `0<NS>D<SUBJECT><SEQ>` | `0ZFD_COSTCTR01` |

`<NS>` = customer namespace letter (Z or Y). `<SEQ>` = 2-digit sequence for uniqueness.

#### InfoObjects

| Type | Pattern | Example |
|---|---|---|
| Characteristic | `0<NS><SUBJECT><NAME>` | `0ZFKOKRS` (controlling area) |
| Key figure | `0<NS>KF<NAME>` | `0ZYKFREVENUE` |
| Unit/currency | `0<NS>UN<NAME>` | `0ZFUNCURR` |

InfoObject names are limited to 9 characters. Abbreviate the subject area to 2 characters if necessary. Document the full name in the description field.

#### CDS Views (BW)

| Layer | Pattern | Example |
|---|---|---|
| RAW extraction | `Z<NS>_CDS_<ENTITY>_E` | `ZFI_CDS_BKPF_E` |
| HARMONIZED | `Z<NS>_CDS_<ENTITY>_H` | `ZFI_CDS_POSTINGS_H` |

#### CompositeProviders (BW)

Pattern: `0<NS>CP_<DOMAIN>_<SUBJECT>`  
Example: `0ZFCP_CO_REVENUE`, `0ZHCP_HR_HEADCOUNT`

#### Process Chains (BW)

Pattern: `Z<NS>_PC_<DOMAIN>_<FREQ>_<DESCRIPTION>`  
Example: `ZFI_PC_FI_DAILY_GLLOAD`, `ZFI_PC_CO_MONTHLY_ALLOCATIONS`

`<FREQ>` = `DAILY`, `WEEKLY`, `MONTHLY`, `ADHOC`

#### ABAP Programs and Function Modules

| Object | Pattern | Example |
|---|---|---|
| Program | `Z<NS>_<DOMAIN>_<PURPOSE>` | `ZFI_GLLOAD_DELTA` |
| Function module | `Z<NS>_FM_<DOMAIN>_<PURPOSE>` | `ZFI_FM_PERIOD_DERIVE` |
| Method (class) | `<VERB>_<NOUN>` (all caps) | `GET_FISCAL_PERIOD`, `VALIDATE_AMOUNT` |
| Class | `ZCL_<NS>_<DOMAIN>_<PURPOSE>` | `ZCL_FI_AMOUNT_CONVERTER` |

### General Naming Rules

- Use underscores as word separators. No CamelCase except in ABAP class method names.
- Maximum 30 characters for DSP objects. BW InfoObjects max 9 characters (hard system limit).
- No abbreviations that are not listed in the project abbreviation register. Maintain the register in the project wiki.
- Sequence numbers (`_01`, `_02`) are used only when multiple objects serve the same purpose at different granularities or versions. Document the distinction clearly.
- Temporary or test objects must use the prefix `TMP_` or `TEST_` and must be removed before production transport.

---

## 3. SQL Coding Standards

These rules apply to all SQL views in DSP (graphical view SQL expressions, SQL views, analytic model calculations) and to HANA SQL scripts used in BW transformation routines.

### 3.1 Explicit Column Lists

Never use `SELECT *`. Specify every column you need.

**Wrong:**
```sql
SELECT * FROM LT_FI_GL_ITEMS
```

**Correct:**
```sql
SELECT
    GL_ACCOUNT,
    COMPANY_CODE,
    POSTING_DATE,
    AMOUNT_LC,
    CURRENCY_LC
FROM LT_FI_GL_ITEMS
```

Rationale: `SELECT *` breaks silently when a source table changes structure. Explicit lists make column dependencies visible in lineage tools and prevent unexpected column pollution.

### 3.2 JOIN Patterns

- Always use explicit JOIN syntax (`INNER JOIN`, `LEFT OUTER JOIN`). Never use implicit joins in the WHERE clause.
- Every JOIN must have an alias. Single-letter aliases are not acceptable on objects with more than three columns.
- Document the business reason for each join in a comment when it is not self-evident.

```sql
-- Correct: explicit join with named aliases
SELECT
    gl.COMPANY_CODE,
    gl.GL_ACCOUNT,
    gl.POSTING_DATE,
    gl.AMOUNT_LC,
    cc.COST_CENTER_DESC
FROM LT_HARM_FI_GL_ITEMS  AS gl
LEFT OUTER JOIN MD_COSTCENTER AS cc
    ON gl.COST_CENTER = cc.COST_CENTER
   AND gl.COMPANY_CODE = cc.COMPANY_CODE
```

- Prefer LEFT OUTER JOIN when the dimension may not always have a matching record (e.g., new cost centers not yet in master data). Document the assumption.
- Never join on a derived expression (e.g., `ON SUBSTR(a.FIELD, 1, 4) = b.FIELD`). Derive the field in the source layer first.

### 3.3 UNION ALL Rules

- Use `UNION ALL` rather than `UNION` unless deduplication is explicitly required by business logic. `UNION` adds a sort + deduplication step that is almost never intentional.
- Every leg of a `UNION ALL` must have matching column count and matching aliases. Use explicit `AS` aliases even when the column name is the same in both legs.
- Add a `SOURCE_SYSTEM` or `ORIGIN` discriminator column in every `UNION ALL` so downstream queries can trace which leg a record came from.

```sql
SELECT
    'S4H'          AS SOURCE_SYSTEM,
    VBELN          AS SALES_ORDER,
    ERDAT          AS CREATED_DATE,
    NETWR          AS NET_VALUE,
    WAERK          AS CURRENCY
FROM RV_S4H_VBAK

UNION ALL

SELECT
    'LEGACY'       AS SOURCE_SYSTEM,
    ORDER_ID       AS SALES_ORDER,
    CREATE_DATE    AS CREATED_DATE,
    ORDER_VALUE    AS NET_VALUE,
    CURRENCY_CODE  AS CURRENCY
FROM RV_LEGACY_ORDERS
```

### 3.4 Date Handling

SAP ERP systems frequently store dates as `VARCHAR(8)` in `YYYYMMDD` format rather than as native `DATE` columns. This causes silent errors in date comparisons and range queries.

**Rule:** Convert VARCHAR dates to DATE in the RAW-to-HARMONIZED transition. Never carry VARCHAR dates into MART or CONSUMPTION layers.

```sql
-- In the HARMONIZED view: convert DATAB/DATBI from VARCHAR to DATE
SELECT
    KOKRS,
    KOSTL,
    TO_DATE(DATAB, 'YYYYMMDD') AS VALID_FROM,
    TO_DATE(DATBI, 'YYYYMMDD') AS VALID_TO
FROM RT_S4H_CSKS
WHERE DATBI >= '99991231'  -- current records only
```

**The DATAB/DATBI gotcha:** DATBI = '99991231' means "open-ended" in SAP. Always document this convention and apply it consistently. Never compare `DATBI` to `CURRENT_DATE` without first checking for this sentinel value.

**Date arithmetic:** Use `ADD_DAYS()`, `ADD_MONTHS()`, `DAYS_BETWEEN()` rather than string manipulation. Never derive dates from string operations on YYYYMMDD fields.

### 3.5 NULL Handling

- Use `COALESCE()` to replace NULLs with business-meaningful defaults. Document what the default represents.
- Aggregation functions ignore NULLs silently — this is often correct, but verify with the business that `SUM(AMOUNT)` returning NULL for an all-NULL group is acceptable.
- Use `NULLIF(expr, 0)` before division to prevent division-by-zero errors. Never rely on the database to return NULL silently.

```sql
-- Safe division with NULLIF
COALESCE(ACTUAL_COST / NULLIF(PLANNED_COST, 0), 0) AS COST_RATIO
```

### 3.6 Aggregation

- Always pair `GROUP BY` with the exact set of non-aggregated columns in the SELECT. Do not add columns to GROUP BY "just to make it compile" — each GROUP BY column changes the grain.
- Prefer `SUM()` over `COUNT()` for financial amounts. `COUNT()` is for row-level analytics.
- Use `HAVING` for post-aggregation filters. Do not use `WHERE` to filter on aggregated values.

### 3.7 CASE Expressions

- Always include an `ELSE` clause. A `CASE` without `ELSE` returns NULL for unmatched records — this is almost always a bug.
- Keep `CASE` expressions to a maximum of 5 branches in a single view. If business logic requires more branches, it belongs in a lookup/mapping table in the HARMONIZED layer.

```sql
CASE POSTING_KEY
    WHEN '40' THEN 'DEBIT'
    WHEN '50' THEN 'CREDIT'
    ELSE 'UNKNOWN'  -- Never omit this
END AS POSTING_DIRECTION
```

### 3.8 Calculated Columns and Input Parameters

- Calculated columns in MART or CONSUMPTION views must have comments explaining the business formula.
- Input parameters in DSP analytic models must have a default value. Never deploy a model that throws an error when no parameter is supplied.
- Do not use input parameters to implement business logic that belongs in the MART layer. Input parameters are for filtering and date-range selection only.

### 3.9 Commenting Standards

Every SQL view must have a header block comment:

```sql
/*
  View    : HV_FI_POSTINGS_ENRICHED
  Layer   : HARMONIZED
  Author  : <initials>, <date>
  Purpose : Joins GL line items with cost center master data.
            Converts VARCHAR posting date to DATE.
            Source: LT_FI_GL_ITEMS (via RF_S4H_FI_GL_ITEMS)
  Changes : <date> <initials> - <description>
*/
```

Inline comments are required for non-obvious WHERE clauses, JOIN conditions, and CASE expressions.

---

## 4. ABAP Coding Standards

### 4.1 SELECT Patterns

Never use `SELECT *`. Specify the INTO target precisely.

**Wrong:**
```abap
SELECT * FROM bkpf INTO TABLE lt_bkpf.
```

**Correct:**
```abap
SELECT bukrs, belnr, gjahr, budat, blart
  FROM bkpf
  INTO TABLE @DATA(lt_bkpf)
 WHERE bukrs IN @lr_bukrs
   AND budat BETWEEN @lv_date_from AND @lv_date_to.
```

### 4.2 FOR ALL ENTRIES vs JOIN

Use `FOR ALL ENTRIES` when:
- The driving table is already in memory
- You need to read a second table for a subset of records from the driver
- The JOIN would produce a Cartesian product due to non-unique keys

Use `JOIN` when:
- Both tables are read from the database in a single pass
- The join condition is on indexed fields
- You need to filter on columns from both tables simultaneously

**FOR ALL ENTRIES rules:**
- Always check that the driving internal table is not empty before using it. An empty driving table returns all records from the secondary table.
- Use `SORT` + `DELETE ADJACENT DUPLICATES` on the driving table before `FOR ALL ENTRIES` to avoid duplicate reads.

```abap
" Correct FOR ALL ENTRIES usage
IF lt_bkpf IS NOT INITIAL.
  SELECT bukrs, belnr, gjahr, buzei, hkont, wrbtr
    FROM bseg
    INTO TABLE @DATA(lt_bseg)
    FOR ALL ENTRIES IN @lt_bkpf
   WHERE bukrs = @lt_bkpf-bukrs
     AND belnr = @lt_bkpf-belnr
     AND gjahr = @lt_bkpf-gjahr.
ENDIF.
```

### 4.3 No Hardcoded Clients, Dates, or Magic Numbers

**Wrong:**
```abap
WHERE mandt = '100'
  AND datbi = '99991231'
```

**Correct:**
```abap
CONSTANTS: lc_open_datbi TYPE d VALUE '99991231'.

WHERE mandt = sy-mandt
  AND datbi = lc_open_datbi
```

All constants must be declared with `CONSTANTS` and documented with a comment explaining the business meaning.

### 4.4 Error Handling

- Every `CALL FUNCTION` and `CALL METHOD` that can raise exceptions must handle those exceptions explicitly.
- Empty `CATCH` blocks are forbidden. At minimum, log the error and raise a new exception with context.
- Use the application log (`BAL_LOG_*`) for business process errors. Use `MESSAGE` only for interactive programs.

```abap
TRY.
    lo_converter->convert(
      EXPORTING iv_amount   = lv_amount
                iv_from_cur = lv_source_currency
                iv_to_cur   = lv_target_currency
      IMPORTING ev_result   = lv_converted ).
  CATCH cx_currency_conversion INTO DATA(lx_conv).
    " Log with context — never swallow
    lv_message = lx_conv->get_text( ).
    CALL FUNCTION 'BAL_LOG_MSG_ADD'
      EXPORTING i_log_handle = lv_log_handle
                i_msgty      = 'E'
                i_msgid      = 'ZFI_MESSAGES'
                i_msgno      = '001'
                i_msgv1      = lv_message.
    RAISE EXCEPTION TYPE cx_fi_conversion_error
      EXPORTING previous = lx_conv.
ENDTRY.
```

### 4.5 Modularization

- Methods must do one thing. A method named `PROCESS_DATA` that loads, transforms, and writes data is three methods pretending to be one.
- Maximum 50 executable statements per method. If you exceed this, refactor.
- Pass data via parameters, not via class attributes used as implicit global variables.
- `FORM` routines are only acceptable when maintaining legacy code. All new ABAP uses classes.

### 4.6 CDS Views in BW Context

- Use CDS views for ODP extraction sources. Define `@Analytics.dataExtract: true` and `@Semantics.systemDate.lastChangedAt` for delta-enabled extraction.
- Apply `@VDM.viewType` annotations correctly: `#BASIC` for entity-level views, `#COMPOSITE` for joined views, `#CONSUMPTION` for report-ready views.
- Do not put business logic in CDS extraction views (`_E` suffix). These are structural views only. Business logic belongs in the transformation layer.

### 4.7 AMDP (ABAP Managed Database Procedures)

- Use AMDP only when native HANA SQL capabilities (window functions, L-calculus, spatial) are genuinely required and cannot be achieved in ABAP.
- AMDP methods must have unit tests that can run on any HANA instance (no hardcoded schema names).
- Never use AMDP for operations that are straightforward in ABAP — the debugging experience is significantly worse.

---

## 5. Data Modeling Rules

### 5.1 Key Design

- Every fact table must have a fully defined surrogate key or a documented composite business key. Undocumented keys cause silent duplicates.
- Composite keys may have a maximum of 5 fields. If more are needed, reconsider the grain.
- Never use generated UUIDs as the sole key in HARMONIZED or MART tables — always include at least one business key field so records can be traced back to the source.

### 5.2 Fact vs Dimension

| Fact | Dimension |
|---|---|
| Measures that change per event | Descriptive attributes stable over time |
| Examples: revenue, quantity, count | Examples: material, cost center, customer |
| Contains foreign keys to dimensions | Contains business keys + attributes |
| Never: long text strings | Never: measures or aggregatable fields |

Do not store dimension attributes in fact tables. Denormalization for performance is acceptable only in MART layer with explicit documentation of the denormalization decision.

### 5.3 Slowly Changing Dimensions (SCD)

The standard approach is SCD Type 2 in HARMONIZED for master data that changes over time (cost center assignment, material classification).

Required fields for SCD Type 2:
- `VALID_FROM DATE NOT NULL`
- `VALID_TO DATE NOT NULL` (use '9999-12-31' for current records)
- `IS_CURRENT TINYINT` (1 = current, 0 = historical) — computed column, not stored

```sql
-- Querying current records
SELECT *
FROM HV_COSTCENTER_SCD2
WHERE IS_CURRENT = 1

-- Querying as-of a specific date
SELECT *
FROM HV_COSTCENTER_SCD2
WHERE VALID_FROM <= '2024-03-31'
  AND VALID_TO   >= '2024-03-31'
```

Never implement SCD Type 2 in the CONSUMPTION layer. It must be resolved before the data reaches reporting consumers.

### 5.4 Hierarchy Handling

- Store hierarchy nodes in a separate dimension table, not as additional columns in the fact table.
- Parent-child hierarchies: store `NODE_ID`, `PARENT_NODE_ID`, `LEVEL`, `HIERARCHY_NAME`.
- Level-based hierarchies: store each level as a column (`L1_NODE`, `L2_NODE`, etc.) up to the deepest level.
- In DSP, use the hierarchy annotation in analytic models to expose hierarchies to SAC. Do not flatten hierarchies in the MART layer unless the hierarchy is static and the depth is fixed.

### 5.5 Currency and Unit Handling

- Always store amounts with their corresponding currency field in the same table. An `AMOUNT` column without `CURRENCY` is incomplete and invalid.
- Store amounts in transaction currency (`AMOUNT_TC`, `CURRENCY_TC`) and local currency (`AMOUNT_LC`, `CURRENCY_LC`) as separate column pairs. Do not store only one and expect downstream to convert.
- Perform currency conversion in the HARMONIZED layer for reporting currencies. Use SAP standard currency tables (`TCURR`, `TCURX`). Never implement a custom conversion algorithm.
- For units of measure: same rule as currency. `QUANTITY` always pairs with `UOM`.

### 5.6 Delta Logic

- RAW ADSOs and local tables must support delta loads. Document the delta mechanism (ODP, SLT, timestamp-based, full reload with swap).
- Full reload with table swap is acceptable only for tables under 1 million records.
- For timestamp-based delta: the `LAST_CHANGED_AT` field must come from the source system, not be derived from `LOAD_TIMESTAMP`. Load timestamp tells you when you loaded it, not when the source record changed.

### 5.7 Data Types and Length Conventions

| Concept | Type | Notes |
|---|---|---|
| SAP date (stored as VARCHAR in ERP) | `VARCHAR(8)` in RAW, `DATE` from HARMONIZED onwards | See Section 3.4 |
| Amount / key figure | `DECIMAL(15,2)` minimum | Use `DECIMAL(23,2)` for high-value consolidation |
| Quantity | `DECIMAL(13,3)` | Match SAP standard field length |
| Short text / description | `NVARCHAR(40)` | SAP standard for most descriptions |
| Long text | `NVARCHAR(255)` | Avoid `CLOB` unless genuinely needed |
| Boolean flag | `TINYINT` (0/1) | Do not use `CHAR(1)` X/space — it breaks NULL semantics |
| SAP GUID | `CHAR(32)` | Store without dashes |

---

## 6. Performance Guidelines

### 6.1 Persistence Strategy Decision

Persist an object when any of the following are true:
- Query execution exceeds 10 seconds on production data volume
- More than 3 downstream consumers read the same object
- The object involves a cross-source join (different source systems)
- The object contains an aggregation that reduces row count by more than 80%

Keep in-memory when:
- The object is a thin projection or renaming view over a single persisted table
- Data volume is under 100,000 records
- Freshness requirements mean persistence would be stale within the load cycle

### 6.2 View Stacking Depth

Maximum view stacking depth is 5 layers in DSP (including graphical view nesting). Deeper stacks cause unpredictable query plan behavior and make lineage difficult to trace.

If you find yourself at depth 6 or deeper, persist an intermediate result at the HARMONIZED layer and restart the stack.

### 6.3 Partitioning

Partition local tables in DSP by:
- Date column (posting date, document date) for fact tables with time-series data
- Company code or controlling area for tables with a natural organizational partition

Partition key must be the first field in the WHERE clause of the most common queries. Document the partitioning strategy in the object description.

### 6.4 Indexing

- Primary key enforcement is not native in all DSP local table types — define secondary indexes manually for JOIN keys that are not the primary key.
- Index every column used as a foreign key in JOIN conditions.
- Do not index columns with low cardinality (e.g., boolean flags, 5-value enum fields) — the query optimizer will ignore them.

### 6.5 Replication Scheduling

- Schedule replication flows to complete before the transformation chain that reads them. Add a buffer of at least 15 minutes.
- Do not schedule all replication flows to start at the same time. Stagger by 5-10 minutes to avoid connection pool exhaustion on the source system.
- Full replication outside business hours only. Delta replication may run during business hours if the source system load permits.

### 6.6 Parallel Execution in Task Chains

- Use parallel execution in task chains for independent entities (e.g., loading GL and AP simultaneously).
- Dependent flows must be in sequence. Document the dependency in the task chain name or description.
- Maximum 4 parallel tasks per task chain on standard infrastructure. Validate with the basis team before increasing.

---

## 7. Transport and Deployment

### 7.1 Environment Strategy

Three mandatory environments. No exceptions.

| Environment | Purpose | Direct changes allowed? |
|---|---|---|
| DEV | Development and unit testing | Yes, by developers |
| QA | Integration testing, business acceptance | Transport only |
| PROD | Production | Transport only, after QA sign-off |

Hotfixes follow the same process. If a production issue requires an immediate fix, the fix is developed in DEV, transported to QA (abbreviated testing acceptable with documented risk acceptance), then transported to PROD.

### 7.2 CTS+ Process for DSP

1. Create a transport request in the DSP tenant transport management (or CTS+ if integrated with ABAP).
2. Assign all changed objects to the request. Do not mix multiple unrelated features in one transport.
3. One transport request per feature or bug fix. This enables selective rollback.
4. Review the transport content with a peer before releasing. Use the transport description to list what changed and why.
5. Transport to QA. Business acceptance testing is performed by the business owner, not the developer.
6. After QA sign-off, transport to PROD in a scheduled change window.

### 7.3 BW/4HANA Transport Order

Objects have dependencies. Transport in this sequence:

1. InfoObjects (characteristics and key figures)
2. DSOs and DataStore objects
3. Transformations and Data Transfer Processes (DTPs)
4. Process chains
5. CompositeProviders
6. Queries and workbooks (if applicable)

If you transport out of order, dependent objects will fail activation. The CTS+ system does not always enforce order automatically — developers must verify manually.

### 7.4 Deployment Order for DSP

1. Remote tables and connections (manual, via Connection Manager)
2. Local tables (schema + data)
3. Replication flows
4. RAW layer views
5. HARMONIZED layer views and tables
6. MART layer objects
7. Task chains
8. CONSUMPTION analytic models and data access controls

### 7.5 Rollback Procedures

Every transport must have a documented rollback plan before release to PROD:
- Which objects to restore and from which previous transport
- Whether a data rollback is required (if the transport modified persisted table structure)
- Who is responsible for executing the rollback
- Maximum acceptable downtime for the rollback window

For DSP local table schema changes: always add columns rather than modifying existing ones. Removing a column requires a migration plan and explicit business approval.

---

## 8. Security and Authorization

### 8.1 Data Access Controls (DSP)

Every analytic model that exposes business data must have a data access control applied. No model goes to PRODUCTION without a DAC.

DAC implementation rules:
- Row-level restrictions are based on the authenticated user's attribute values (e.g., company code, cost center, profit center assigned to the user's role).
- Never implement row-level security in the MART layer views — it belongs in the DAC on the CONSUMPTION analytic model.
- DAC conditions must use indexed columns only. Non-indexed columns in DAC conditions cause full table scans on every query.

```sql
-- Example DAC definition (pseudo-code — implement via DSP UI)
-- Restricts to company codes assigned to the user's data access role
FILTER ON COMPANY_CODE IN (
    SELECT COMPANY_CODE FROM DAC_USER_COMPANYCODE
    WHERE USER_ID = SESSION_USER
)
```

### 8.2 Analytic Privileges (BW)

- Define analytic privileges at the InfoObject level, not at the query level. Query-level restrictions do not persist when the query is copied or replaced.
- Use variable-based authorization (authorization-relevant variables) rather than hardcoded value restrictions.
- Test analytic privileges with a non-admin test user before transport to QA. Admin users bypass privilege checks.

### 8.3 Row-Level Security Design

Document the authorization concept before implementation:
- Which dimensions carry the restriction (cost center, company code, plant)?
- What is the assignment source (HR org, role-based, manual maintenance)?
- Who maintains the assignment table and on what schedule?
- How are new users onboarded and offboarded?

### 8.4 Space Sharing Agreements (DSP)

When sharing objects between spaces:
- The sharing must be formally agreed between the space owners and documented.
- Shared objects from a source space must not be modified in the consumer space. If customization is needed, copy the object and own the copy.
- Shared dimension tables (master data) are maintained in the HARMONIZED space and shared read-only to domain MART spaces.

---

## 9. Testing Requirements

### 9.1 What Must Be Tested Before Transport

Every transport to QA must include evidence of the following tests:

| Test Type | Who | Minimum Requirement |
|---|---|---|
| Unit test (SQL logic) | Developer | All CASE branches exercised; edge cases verified |
| Volume test | Developer | Tested on at least 1 month of production data volume |
| Delta test | Developer | Full load + delta increment produces same result as two full loads |
| Reconciliation | Developer | Row count and key figure totals match source system report |
| Authorization test | Developer | Non-admin user sees only permitted data |
| Business acceptance | Business owner | Sign-off in the test protocol document |

### 9.2 Reconciliation Rules

For every new data flow, define at least one reconciliation query that can be run against both the source system and the target layer to verify record counts and aggregated values match:

```sql
-- Example reconciliation query for GL balance
-- Run same logic against source (S/4HANA) and target (HARM layer)
SELECT
    COMPANY_CODE,
    FISCAL_YEAR,
    GL_ACCOUNT,
    SUM(AMOUNT_LC)    AS TOTAL_AMOUNT,
    COUNT(*)          AS RECORD_COUNT
FROM HV_FI_POSTINGS_ENRICHED
WHERE FISCAL_YEAR = '2024'
GROUP BY COMPANY_CODE, FISCAL_YEAR, GL_ACCOUNT
ORDER BY COMPANY_CODE, GL_ACCOUNT
```

Document the reconciliation query in the object's technical documentation and run it as part of every regression test after a change.

### 9.3 Test Data Strategy

- Never use production data in DEV for initial development. Use a representative anonymized extract.
- Test data must cover: standard records, edge cases (zero amounts, null fields, open-ended dates), and records that should be excluded by filter logic.
- Volume testing must use production-scale data. QA environment should have a production data copy refreshed monthly at minimum.

### 9.4 Regression Testing

Any change to a shared HARMONIZED or MART object triggers regression tests for all downstream consumers. Identify downstream consumers via the lineage tool before making a change. If more than 5 objects are downstream, escalate the change to an architect review before proceeding.

---

## 10. Change Management

### 10.1 Documentation Requirements Per Change

Before closing a development ticket, the developer must update:
- The object header comment (author, date, description of change)
- The data flow documentation if the change affects data lineage
- The reconciliation query if the output structure changed
- The operational runbook if the change affects scheduling or error behavior

### 10.2 Code Review Checklist

The reviewer must verify the following before approving:

**Naming and structure:**
- [ ] Object name follows the naming convention for its layer and type
- [ ] Object is assigned to the correct layer
- [ ] Description field is populated (minimum 20 characters)
- [ ] Owner field is set

**SQL correctness:**
- [ ] No `SELECT *`
- [ ] All JOINs are explicit with aliases
- [ ] CASE expressions have ELSE clauses
- [ ] VARCHAR dates are converted to DATE in HARMONIZED or earlier
- [ ] No hardcoded dates, client numbers, or magic values

**ABAP correctness (if applicable):**
- [ ] No `SELECT *`
- [ ] `FOR ALL ENTRIES` is guarded against empty table
- [ ] No empty CATCH blocks
- [ ] No nested SELECT in LOOP
- [ ] No hardcoded client (`sy-mandt` is used)

**Performance:**
- [ ] Persistence decision is documented and justified
- [ ] JOINs are on indexed fields
- [ ] View stacking depth is under 5

**Security:**
- [ ] DAC applied if object is exposed to CONSUMPTION
- [ ] No column contains data that should be restricted but is not

**Testing:**
- [ ] Reconciliation query provided and results documented
- [ ] Delta test evidence provided if the object is delta-enabled

### 10.3 Approval Workflow

| Change type | Required approvers |
|---|---|
| New object in DEV | Peer developer review |
| Transport to QA | Technical lead + business owner |
| Transport to PROD | Technical lead + business owner + project manager |
| Schema change (column add/remove) | Technical lead + architect + business owner |
| Shared HARMONIZED object change | Architect + all affected domain leads |

---

## 11. Common Anti-Patterns

### 11.1 The Bypass Layer

**Anti-pattern:** Building a view in the CONSUMPTION layer that reads directly from RAW, skipping HARMONIZED and MART.

**Why it is wrong:** Business logic is duplicated across multiple consumption objects. A change to the source structure requires changes in every bypass view independently. Tracing data lineage becomes impossible.

**Correct approach:** Always go through all layers. If the data is "simple enough" to not need HARMONIZED processing, create a thin pass-through view at each layer rather than skipping them.

### 11.2 Logic in the CONSUMPTION Layer

**Anti-pattern:** Putting CASE expressions, JOIN conditions, or KPI formulas directly in an analytic model or CompositeProvider because "it's easier to test there."

**Why it is wrong:** Logic in CONSUMPTION is invisible to lineage tools, cannot be reused by other consumers, and is not covered by reconciliation tests. It will diverge from other reports that implement the "same" logic differently.

**Correct approach:** Move logic to the MART layer. CONSUMPTION objects are structural wrappers and access control boundaries, not logic containers.

### 11.3 Transformation Flow as Business Logic Container

**Anti-pattern:** Implementing complex business rules (allocations, currency conversion, hierarchy derivation) inside a DSP Transformation Flow's expression editor rather than in a SQL view.

**Why it is wrong:** Transformation flow expressions are not version-controlled in the same way as SQL views, are difficult to review, and cannot be unit-tested independently.

**Correct approach:** Implement the logic in a SQL view and use the Transformation Flow only to move data from one persisted table to another.

### 11.4 One Process Chain to Rule Them All

**Anti-pattern:** A single monolithic process chain that loads all subjects for all domains, often 50+ steps with complex conditional logic.

**Why it is wrong:** A single failure causes cascading failures across unrelated domains. Partial reruns are impossible. The chain takes so long that failures are not detected until the next morning.

**Correct approach:** One process chain per domain, per frequency. Use a master chain that triggers domain chains in parallel where dependencies permit.

### 11.5 VARCHAR Date Proliferation

**Anti-pattern:** Allowing `DATAB`, `DATBI`, `ERDAT`, `BUDAT` and similar SAP date fields to remain as `VARCHAR(8)` through all layers.

**Why it is wrong:** Range comparisons on VARCHAR dates fail silently for dates before '10000000'. `BETWEEN '20240101' AND '20241231'` sorts as strings, not dates — it works accidentally in most cases but breaks on edge cases and is semantically wrong.

**Correct approach:** Convert to DATE in the RAW-to-HARMONIZED transition without exception. See Section 3.4.

### 11.6 Delta Key Mismatch

**Anti-pattern:** Defining a delta key in the RAW ADSO that does not match the business key of the source record.

**Why it is wrong:** Records are updated at the source using the business key. If the delta key is different, delta loads create duplicate records rather than updating existing ones.

**Correct approach:** Always align the delta key with the source system's primary key. Verify by running a full load and a delta load and comparing record counts.

### 11.7 Implicit Data Type Conversion in JOINs

**Anti-pattern:** Joining `NVARCHAR` to `VARCHAR` (or `INTEGER` to `VARCHAR`) without explicit casting.

**Why it is wrong:** HANA performs implicit conversion but at a significant performance cost. On large tables this can increase JOIN execution time by an order of magnitude.

**Correct approach:** Cast explicitly in the view. If the source types differ, standardize in the HARMONIZED layer.

```sql
-- Wrong: implicit conversion
ON gl.KOKRS = cc.KOKRS  -- one is CHAR, one is NVARCHAR

-- Correct: cast to a common type
ON CAST(gl.KOKRS AS NVARCHAR(4)) = cc.KOKRS
```

### 11.8 Test Objects Left in Production

**Anti-pattern:** `TMP_`, `TEST_`, or developer-initials-prefixed objects transported to PROD because "we'll clean it up later."

**Why it is wrong:** They never get cleaned up. They appear in lineage tools, confuse support teams, and occasionally get used as dependencies by other objects.

**Correct approach:** The transport content review (Section 10.2) explicitly checks for test object naming patterns. Any object with a test prefix is rejected from the transport.

### 11.9 Omitting the Operational Runbook

**Anti-pattern:** Delivering a data flow without an operational runbook because "it's self-explanatory."

**Why it is wrong:** The person handling a 2am production failure is not the person who built it. Without documented recovery procedures, every incident becomes a crisis.

**Correct approach:** The operational runbook is a mandatory deliverable for every data flow that runs in production. See the documentation standard for required content.

### 11.10 Authorization as an Afterthought

**Anti-pattern:** Building and testing all layers without authorization, then "adding the DAC at the end before go-live."

**Why it is wrong:** Authorization requirements frequently reveal that the data model needs to store additional organizational attributes (e.g., profit center, controlling area) that were omitted. Retrofitting these into a production-ready model is expensive.

**Correct approach:** Define the authorization concept in the design phase. Implement DAC in DEV and include authorization testing in the QA acceptance criteria.

---

*This guideline is maintained by the Horvath SAP Competence Center. Questions and proposed amendments should be directed to the technical lead assigned to your project. Amendments require approval from the competence center before taking effect on active projects.*
