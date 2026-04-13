# SAP HANA SQL Patterns and Gotchas

## LIMIT Inside UNION ALL
SAP HANA does not allow a bare LIMIT clause on a UNION ALL leg. Wrap each
leg in a subquery:

```sql
SELECT * FROM (SELECT col FROM t1 ORDER BY col LIMIT 10)
UNION ALL
SELECT * FROM (SELECT col FROM t2 ORDER BY col LIMIT 10);
```

## Alias Required on Every UNION Leg
All column aliases must be consistent across every UNION / UNION ALL leg.
Omitting an alias on any leg causes a "column name mismatch" parse error
even when the data types are compatible.

## DATAB / DATBI Are VARCHAR, Not DATE
SAP master-data validity fields (DATAB = valid-from, DATBI = valid-to) are
stored as VARCHAR(8) in the format YYYYMMDD. Always cast when comparing:

```sql
WHERE TO_DATE(DATAB, 'YYYYMMDD') <= CURRENT_DATE
  AND TO_DATE(DATBI, 'YYYYMMDD') >= CURRENT_DATE
```

## String Aggregation
SAP HANA uses `STRING_AGG(col, delimiter ORDER BY sort_col)` — not
`GROUP_CONCAT`. The ORDER BY clause inside STRING_AGG is mandatory in some
engine versions; always include it for portability.

## Calculated Views — No DML
Calculated views (CV) in HANA are read-only projections. Any attempt to
INSERT / UPDATE / DELETE against a CV raises "feature not supported."
Always target the underlying base tables for write operations.
