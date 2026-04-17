"""Field extractor — parse structured field metadata from scanned landscape objects.

Supports DSP SQL views, CDP column metadata, and BW/ABAP objects.
Returns lists of dicts whose keys match the object_fields and
transformation_rules table schemas.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Aggregate function names (SQL)
# ---------------------------------------------------------------------------

_AGGREGATE_FUNCTIONS = frozenset(
    [
        "SUM",
        "AVG",
        "COUNT",
        "MIN",
        "MAX",
        "MEDIAN",
        "VARIANCE",
        "STDDEV",
        "LISTAGG",
        "ARRAY_AGG",
        "STRING_AGG",
        "GROUP_CONCAT",
        "FIRST",
        "LAST",
        "CORR",
        "COVAR_POP",
        "COVAR_SAMP",
        "PERCENTILE_CONT",
        "PERCENTILE_DISC",
        "RANK",
        "DENSE_RANK",
        "ROW_NUMBER",
        "NTILE",
        "CUME_DIST",
        "PERCENT_RANK",
        "LAG",
        "LEAD",
    ]
)

# Regex to detect aggregate calls — e.g. SUM(, COUNT(
_AGG_PATTERN = re.compile(
    r"\b(" + "|".join(_AGGREGATE_FUNCTIONS) + r")\s*\(",
    re.IGNORECASE,
)

# Detect non-trivial expressions: arithmetic, CASE, CAST, string funcs, etc.
_EXPR_PATTERN = re.compile(
    r"[\+\-\*/]|CASE\b|CAST\b|CONVERT\b|COALESCE\b|NULLIF\b|IIF\b|DECODE\b"
    r"|NVL\b|SUBSTR\b|SUBSTRING\b|TRIM\b|UPPER\b|LOWER\b|TO_DATE\b|TO_CHAR\b"
    r"|DATEDIFF\b|DATEADD\b|TRUNC\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# DSP SQL view parsing
# ---------------------------------------------------------------------------


def _strip_sql_comments(sql: str) -> str:
    """Remove /* */ block comments and -- line comments."""
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    sql = re.sub(r"--[^\n]*", " ", sql)
    return sql


def _extract_select_clause(sql: str) -> str | None:
    """Return the raw text between SELECT and the first FROM at the top level."""
    sql = _strip_sql_comments(sql)
    # Find SELECT … FROM (ignore nested parens)
    m = re.search(r"\bSELECT\b(.*?)\bFROM\b", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        return None
    return m.group(1).strip()


def _extract_source_table(sql: str) -> str | None:
    """Best-effort: return the first table name after FROM."""
    sql = _strip_sql_comments(sql)
    m = re.search(r"\bFROM\s+([\w\.\"\`]+)", sql, re.IGNORECASE)
    if m:
        return m.group(1).strip('"').strip("`")
    return None


def _parse_select_columns(select_clause: str) -> list[dict[str, Any]]:
    """Split a SELECT clause into individual column expressions.

    Handles nested parentheses so comma-splitting inside function calls works.
    Returns a list of raw expression strings.
    """
    columns: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in select_clause:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            columns.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        columns.append("".join(current).strip())
    return [c for c in columns if c]


def _column_to_field(expr: str, ordinal: int, source_table: str | None) -> dict[str, Any]:
    """Convert a raw SELECT column expression to an object_fields dict."""
    expr = expr.strip()

    # Detect alias: expr AS alias  or  expr alias  (last bare word)
    alias: str | None = None
    field_name: str = expr

    as_match = re.search(r"\bAS\s+([\w\"\`]+)\s*$", expr, re.IGNORECASE)
    if as_match:
        alias = as_match.group(1).strip('"').strip("`")
        raw_expr = expr[: as_match.start()].strip()
    else:
        # No AS — check if the last token is a plain identifier (not a paren/operator)
        bare_match = re.search(r"^(.*?)\s+([\w]+)\s*$", expr, re.DOTALL)
        if bare_match and not re.search(r"[\(\)\+\-\*/,]", bare_match.group(1)):
            alias = bare_match.group(2)
            raw_expr = bare_match.group(1).strip()
        else:
            raw_expr = expr

    # Resolve field_name
    if alias:
        field_name = alias
    elif re.match(r"^[\w\.]+$", raw_expr):
        # Simple column reference — strip table prefix
        field_name = raw_expr.split(".")[-1]
    else:
        field_name = f"col_{ordinal}"

    # Detect source_field for simple "table.column" references
    source_field: str | None = None
    simple_ref = re.match(r"^([\w]+)\.([\w]+)$", raw_expr)
    if simple_ref:
        source_field = simple_ref.group(2)

    is_aggregated = bool(_AGG_PATTERN.search(raw_expr))
    # Expressions are anything that isn't a plain column ref
    is_plain_ref = bool(re.match(r"^[\w\.]+$", raw_expr))
    is_calculated = not is_plain_ref or is_aggregated

    agg_match = _AGG_PATTERN.search(raw_expr)
    aggregation_type: str | None = agg_match.group(1).upper() if agg_match else None

    return {
        "field_name": field_name,
        "field_ordinal": ordinal,
        "data_type": None,
        "expression": raw_expr if not is_plain_ref else None,
        "source_object": source_table,
        "source_field": source_field,
        "is_key": False,
        "is_calculated": is_calculated,
        "is_aggregated": is_aggregated,
        "aggregation_type": aggregation_type,
        "field_role": "measure" if is_aggregated else "dimension",
    }


def extract_fields_from_sql(sql: str, object_type: str = "view") -> list[dict]:
    """Parse a SQL SELECT statement and return structured field dicts.

    Each dict has keys matching the object_fields table schema.
    Returns an empty list when parsing fails or SQL is absent.
    """
    if not sql or not sql.strip():
        return []

    select_clause = _extract_select_clause(sql)
    if not select_clause:
        logger.debug("field_extractor: no SELECT clause found in SQL")
        return []

    source_table = _extract_source_table(sql)
    raw_cols = _parse_select_columns(select_clause)

    fields: list[dict] = []
    for i, col in enumerate(raw_cols):
        if col.strip() == "*":
            continue
        try:
            fields.append(_column_to_field(col, i + 1, source_table))
        except Exception as exc:  # noqa: BLE001
            logger.debug("field_extractor: failed to parse column %d: %s — %s", i + 1, col, exc)

    return fields


# ---------------------------------------------------------------------------
# CDP column metadata
# ---------------------------------------------------------------------------


def extract_fields_from_metadata(metadata: dict, object_type: str) -> list[dict]:
    """Extract fields from CDP-captured column metadata.

    Expects metadata["columns"] to be a list of
    {"name": "...", "type": "...", "description": "..."}.
    """
    columns: list[dict] = []
    raw = metadata.get("columns")
    if not raw or not isinstance(raw, list):
        return []

    for i, col in enumerate(raw):
        if not isinstance(col, dict):
            continue
        name = col.get("name") or col.get("field_name") or f"col_{i + 1}"
        dtype = col.get("type") or col.get("data_type")
        desc = col.get("description") or col.get("comment")

        # Heuristic: columns ending in KEY / _ID are likely keys
        is_key = bool(re.search(r"(^|_)(key|id)$", name, re.IGNORECASE))

        columns.append(
            {
                "field_name": name,
                "field_ordinal": i + 1,
                "data_type": dtype,
                "expression": desc or None,
                "source_object": None,
                "source_field": None,
                "is_key": is_key,
                "is_calculated": False,
                "is_aggregated": False,
                "aggregation_type": None,
                "field_role": "key" if is_key else "attribute",
            }
        )

    return columns


# ---------------------------------------------------------------------------
# BW / ABAP object parsing
# ---------------------------------------------------------------------------

# ABAP field declaration patterns
_ABAP_DATA_PATTERN = re.compile(
    r"^\s*(DATA|TYPES)\s+:?\s*(\w+)\s+TYPE\s+([\w\-\/]+)",
    re.IGNORECASE | re.MULTILINE,
)

# SELECT field list in ABAP: SELECT field1 field2 field3 FROM ...
_ABAP_SELECT_PATTERN = re.compile(
    r"\bSELECT\b(.+?)\bFROM\b",
    re.IGNORECASE | re.DOTALL,
)


def _parse_abap_source(source_code: str) -> list[dict]:
    """Extract DATA/TYPES declarations and SELECT fields from ABAP source."""
    fields: list[dict] = []
    seen: set[str] = set()

    # DATA/TYPES declarations
    for m in _ABAP_DATA_PATTERN.finditer(source_code):
        name = m.group(2).upper()
        dtype = m.group(3).upper()
        if name not in seen:
            seen.add(name)
            fields.append(
                {
                    "field_name": name,
                    "field_ordinal": len(fields) + 1,
                    "data_type": dtype,
                    "expression": None,
                    "source_object": None,
                    "source_field": None,
                    "is_key": False,
                    "is_calculated": False,
                    "is_aggregated": False,
                    "aggregation_type": None,
                    "field_role": "attribute",
                }
            )

    # SELECT field lists (BW ABAP SELECT ... FROM)
    for m in _ABAP_SELECT_PATTERN.finditer(source_code):
        raw = m.group(1).strip()
        # Skip SELECT * and SELECT SINGLE *
        if raw.lstrip().startswith("*"):
            continue
        for token in re.split(r"\s+", raw):
            token = token.strip().upper()
            if token and re.match(r"^\w+$", token) and token not in seen:
                seen.add(token)
                fields.append(
                    {
                        "field_name": token,
                        "field_ordinal": len(fields) + 1,
                        "data_type": None,
                        "expression": None,
                        "source_object": None,
                        "source_field": None,
                        "is_key": False,
                        "is_calculated": False,
                        "is_aggregated": False,
                        "aggregation_type": None,
                        "field_role": "attribute",
                    }
                )

    return fields


def extract_bw_fields(metadata: dict, object_type: str, source_code: str = "") -> tuple[list[dict], list[dict]]:
    """Extract fields (and optionally transformation rules) from BW/ABAP objects.

    Returns (fields, transformation_rules).
    transformation_rules are populated for Transformation objects.
    """
    fields: list[dict] = []
    transformation_rules: list[dict] = []
    ot = object_type.lower()

    if ot == "adso":
        # ADSO: key_fields + data_fields in metadata
        key_fields: list = metadata.get("key_fields") or metadata.get("keyFields") or []
        data_fields: list = metadata.get("data_fields") or metadata.get("dataFields") or []
        ordinal = 1
        for f in key_fields:
            name = (f if isinstance(f, str) else f.get("name", "")).upper()
            if name:
                fields.append(
                    {
                        "field_name": name,
                        "field_ordinal": ordinal,
                        "data_type": f.get("type") if isinstance(f, dict) else None,
                        "expression": None,
                        "source_object": None,
                        "source_field": None,
                        "is_key": True,
                        "is_calculated": False,
                        "is_aggregated": False,
                        "aggregation_type": None,
                        "field_role": "key",
                    }
                )
                ordinal += 1
        for f in data_fields:
            name = (f if isinstance(f, str) else f.get("name", "")).upper()
            if name:
                fields.append(
                    {
                        "field_name": name,
                        "field_ordinal": ordinal,
                        "data_type": f.get("type") if isinstance(f, dict) else None,
                        "expression": None,
                        "source_object": None,
                        "source_field": None,
                        "is_key": False,
                        "is_calculated": False,
                        "is_aggregated": False,
                        "aggregation_type": None,
                        "field_role": "measure",
                    }
                )
                ordinal += 1

    elif ot == "infoobject":
        # InfoObject: attributes, compounding info
        attrs: list = metadata.get("attributes") or []
        ordinal = 1
        for attr in attrs:
            name = (attr if isinstance(attr, str) else attr.get("name", "")).upper()
            if name:
                fields.append(
                    {
                        "field_name": name,
                        "field_ordinal": ordinal,
                        "data_type": attr.get("type") if isinstance(attr, dict) else None,
                        "expression": None,
                        "source_object": None,
                        "source_field": None,
                        "is_key": False,
                        "is_calculated": False,
                        "is_aggregated": False,
                        "aggregation_type": None,
                        "field_role": "attribute",
                    }
                )
                ordinal += 1

    elif ot == "transformation":
        # Transformation: source → target field mappings
        mappings: list = metadata.get("field_mappings") or metadata.get("rules") or metadata.get("mappings") or []
        for i, mapping in enumerate(mappings):
            if not isinstance(mapping, dict):
                continue
            src = mapping.get("source_field") or mapping.get("source") or ""
            tgt = mapping.get("target_field") or mapping.get("target") or ""
            if not src and not tgt:
                continue
            transformation_rules.append(
                {
                    "rule_sequence": i + 1,
                    "source_field": src.upper() if src else None,
                    "target_field": tgt.upper() if tgt else None,
                    "rule_type": mapping.get("rule_type") or "direct",
                    "formula": mapping.get("formula") or mapping.get("expression") or None,
                    "description": mapping.get("description") or None,
                }
            )

    # Supplement with ABAP source code analysis if available
    if source_code and ot != "transformation":
        abap_fields = _parse_abap_source(source_code)
        existing_names = {f["field_name"] for f in fields}
        for af in abap_fields:
            if af["field_name"] not in existing_names:
                af["field_ordinal"] = len(fields) + 1
                fields.append(af)
                existing_names.add(af["field_name"])

    return fields, transformation_rules


# ---------------------------------------------------------------------------
# Main dispatch entry point
# ---------------------------------------------------------------------------


def extract_fields(obj: dict) -> tuple[list[dict], list[dict]]:
    """Extract fields and transformation rules from any scanned landscape object.

    Args:
        obj: A landscape_object dict with keys: platform, object_type,
             metadata, documentation (may contain SQL/ABAP source code).

    Returns:
        (fields, transformation_rules) — both as lists of dicts ready to
        insert into the object_fields / transformation_rules tables.
    """
    platform: str = (obj.get("platform") or "").lower()
    object_type: str = (obj.get("object_type") or "").lower()
    metadata: dict = obj.get("metadata") or {}
    documentation: str = obj.get("documentation") or ""

    # Normalize metadata if it came back as a string (asyncpg JSONB quirk)
    if isinstance(metadata, str):
        import json as _json

        try:
            metadata = _json.loads(metadata)
        except Exception:  # noqa: BLE001
            metadata = {}

    fields: list[dict] = []
    transformation_rules: list[dict] = []

    if platform == "dsp":
        if object_type == "view":
            # Try SQL from metadata first, fall back to documentation field
            sql = metadata.get("sql") or metadata.get("definition") or documentation
            fields = extract_fields_from_sql(sql, object_type)
            # Fall back to CDP column metadata if SQL parsing yielded nothing
            if not fields:
                fields = extract_fields_from_metadata(metadata, object_type)
        else:
            # CDP column metadata for tables, entities, etc.
            fields = extract_fields_from_metadata(metadata, object_type)

    elif platform == "bw":
        source_code = metadata.get("source_code") or documentation or ""
        fields, transformation_rules = extract_bw_fields(metadata, object_type, source_code)

    elif platform in ("cdp", "sac", "hana"):
        # Generic CDP/SAC/HANA: use column metadata
        fields = extract_fields_from_metadata(metadata, object_type)
        # Also try SQL if present
        sql = metadata.get("sql") or metadata.get("definition") or ""
        if sql and not fields:
            fields = extract_fields_from_sql(sql, object_type)

    else:
        # Unknown platform — try metadata columns first, then SQL
        fields = extract_fields_from_metadata(metadata, object_type)
        if not fields:
            sql = metadata.get("sql") or metadata.get("definition") or documentation
            fields = extract_fields_from_sql(sql, object_type)

    logger.debug(
        "field_extractor: platform=%s type=%s fields=%d rules=%d",
        platform,
        object_type,
        len(fields),
        len(transformation_rules),
    )
    return fields, transformation_rules
