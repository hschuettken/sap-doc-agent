You are generating DSP SQL code for a view in an SAP Datasphere migration.

## View Specification
- **Technical Name:** {{ technical_name }}
- **Space:** {{ space }}
- **Layer:** {{ layer }}
- **Semantic Usage:** {{ semantic_usage }}
- **Description:** {{ description }}
- **Source Objects:** {{ source_objects | join(", ") }}
- **Source BW Chains:** {{ source_chains | join(", ") }}
{% if collapsed_bw_steps %}- **Replaces BW Steps:** {{ collapsed_bw_steps | join(", ") }}{% endif %}
{% if collapse_rationale %}- **Collapse Rationale:** {{ collapse_rationale }}{% endif %}

## Columns
{% for col in columns %}
- `{{ col.name }}` ({{ col.data_type }}){% if col.is_key %} [KEY]{% endif %}{% if col.is_measure %} [MEASURE{% if col.aggregation %}: {{ col.aggregation }}{% endif %}]{% endif %}{% if col.source_field %} ← {{ col.source_field }}{% endif %}
{% endfor %}

## SQL Logic Sketch
```sql
{{ sql_logic }}
```

{% if persistence %}
**Note:** This view will be PERSISTED. Ensure the SQL is efficient for initial load.
{% endif %}

## DSP SQL Rules (MANDATORY — violations will be flagged)
1. **NO CTEs** — `WITH cte AS (...)` is NOT supported. Use inline subqueries: `SELECT ... FROM (...) alias`
2. **LIMIT in UNION ALL** — Wrap each leg in parentheses: `(SELECT ... LIMIT 1) UNION ALL (SELECT ... LIMIT 1)`
3. **Column aliases on EVERY UNION ALL leg** — Not just the first. Every leg needs `AS "ColName"`
4. **No SELECT * on cross-space** — Use explicit columns: `SELECT a."COL1" FROM "SPACE"."view" a`
5. **Cross-space prefix** — Reference as `"SPACE_NAME"."view_name"` with quotes
6. **No --> in comments** — Use `--` or `=>` instead
7. **DATAB DESC in ROW_NUMBER** — When using ROW_NUMBER for validity periods, include `DATAB DESC`
8. **VARCHAR dates** — Compare DATAB/DATBI as strings: `WHERE DATAB <= '20260101'`

## Output Requirements
- Generate complete, deployable DSP SQL
- Include traceability comments: `-- Source: BW <step_id> (<description>)`
- Follow naming conventions (quoted identifiers for German business names)
- No trailing semicolons (DSP doesn't need them in view definitions)

Return ONLY the SQL code, no markdown fences or explanation.
