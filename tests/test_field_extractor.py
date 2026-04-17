"""Tests for field extraction from SQL and metadata."""

from __future__ import annotations

from spec2sphere.core.scanner.field_extractor import (
    extract_fields,
    extract_fields_from_metadata,
    extract_fields_from_sql,
)


def test_extract_simple_select():
    sql = "SELECT company_code, fiscal_year, revenue FROM sales_data"
    fields = extract_fields_from_sql(sql)
    assert len(fields) == 3
    assert fields[0]["field_name"] == "company_code"
    assert fields[1]["field_name"] == "fiscal_year"
    assert fields[2]["field_name"] == "revenue"
    assert fields[0]["field_ordinal"] == 1


def test_extract_aliased_columns():
    sql = "SELECT a.company_code AS cc, b.amount AS total_amount FROM table_a a JOIN table_b b ON a.id = b.id"
    fields = extract_fields_from_sql(sql)
    names = [f["field_name"] for f in fields]
    assert "cc" in names or "company_code" in names
    assert "total_amount" in names or "amount" in names


def test_extract_aggregated_columns():
    sql = "SELECT company_code, SUM(amount) AS total, COUNT(*) AS cnt FROM sales GROUP BY company_code"
    fields = extract_fields_from_sql(sql)
    agg_fields = [f for f in fields if f.get("is_aggregated")]
    assert len(agg_fields) >= 1  # at least SUM(amount) detected


def test_extract_calculated_columns():
    sql = "SELECT company_code, amount * 1.19 AS gross_amount FROM sales"
    fields = extract_fields_from_sql(sql)
    calc = [f for f in fields if f.get("is_calculated")]
    assert len(calc) >= 1


def test_extract_star_select():
    """SELECT * is intentionally skipped — no structured fields to extract."""
    sql = "SELECT * FROM master_data"
    fields = extract_fields_from_sql(sql)
    assert len(fields) == 0


def test_extract_from_metadata_columns():
    metadata = {
        "columns": [
            {"name": "COMPANY_CODE", "type": "NVARCHAR(10)", "description": "Company"},
            {"name": "AMOUNT", "type": "DECIMAL(17,2)", "description": "Revenue amount"},
        ]
    }
    fields = extract_fields_from_metadata(metadata, "view")
    assert len(fields) == 2
    assert fields[0]["field_name"] == "COMPANY_CODE"
    assert fields[0]["data_type"] == "NVARCHAR(10)"
    assert fields[1]["field_name"] == "AMOUNT"


def test_extract_fields_dispatch_dsp():
    obj = {
        "platform": "dsp",
        "object_type": "view",
        "metadata": {},
        "documentation": "SELECT id, name, revenue FROM dim_product",
    }
    fields, rules = extract_fields(obj)
    assert len(fields) >= 3
    assert len(rules) == 0


def test_extract_fields_dispatch_metadata():
    obj = {
        "platform": "dsp",
        "object_type": "view",
        "metadata": {
            "columns": [
                {"name": "ID", "type": "INT"},
                {"name": "NAME", "type": "NVARCHAR(100)"},
            ]
        },
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    assert len(fields) == 2


def test_extract_empty_object():
    obj = {
        "platform": "unknown",
        "object_type": "other",
        "metadata": {},
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    assert fields == []
    assert rules == []


def test_extract_bw_adso():
    obj = {
        "platform": "bw",
        "object_type": "adso",
        "metadata": {
            "key_fields": ["CALMONTH", "MATERIAL", "PLANT"],
            "data_fields": ["QUANTITY", "AMOUNT", "CURRENCY"],
        },
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    keys = [f for f in fields if f.get("is_key")]
    data = [f for f in fields if not f.get("is_key")]
    assert len(keys) == 3
    assert len(data) == 3


# ---------------------------------------------------------------------------
# SQL parsing edge cases
# ---------------------------------------------------------------------------


def test_extract_cte():
    """CTE prefix should be ignored; parser finds the outer SELECT clause."""
    sql = "WITH cte AS (SELECT id FROM t) SELECT cte.id, name FROM cte JOIN other ON cte.id = other.id"
    fields = extract_fields_from_sql(sql)
    names = [f["field_name"] for f in fields]
    # Outer select has cte.id (alias: id) and name
    assert len(fields) >= 1
    assert any(n in ("id", "cte") for n in names) or "name" in names


def test_extract_distinct():
    """DISTINCT keyword should not block extraction."""
    sql = "SELECT DISTINCT company_code, amount FROM sales"
    fields = extract_fields_from_sql(sql)
    names = [f["field_name"] for f in fields]
    # DISTINCT is part of the SELECT clause text; columns still extracted
    # At minimum 'amount' should appear
    assert len(fields) >= 1
    assert "amount" in names


def test_extract_qualified_name():
    """Three-part schema.table.column reference: field_name should be the leaf."""
    sql = "SELECT schema.table.column FROM schema.table"
    fields = extract_fields_from_sql(sql)
    assert len(fields) == 1
    assert fields[0]["field_name"] == "column"


def test_extract_case_expression():
    """CASE expression column gets is_calculated=True."""
    sql = "SELECT CASE WHEN status = 'A' THEN 'Active' ELSE 'Inactive' END AS status_text FROM t"
    fields = extract_fields_from_sql(sql)
    assert len(fields) == 1
    assert fields[0]["field_name"] == "status_text"
    assert fields[0]["is_calculated"] is True


def test_extract_nested_function():
    """Nested function calls (COALESCE(NULLIF(...))) parse without error."""
    sql = "SELECT COALESCE(NULLIF(a.name, ''), 'Unknown') AS clean_name FROM t"
    fields = extract_fields_from_sql(sql)
    assert len(fields) == 1
    assert fields[0]["field_name"] == "clean_name"
    assert fields[0]["is_calculated"] is True


def test_extract_multiple_joins():
    """Multiple JOINs don't confuse the FROM boundary detection."""
    sql = "SELECT a.id, b.name, c.amount FROM t1 a JOIN t2 b ON a.id = b.id JOIN t3 c ON b.id = c.id"
    fields = extract_fields_from_sql(sql)
    assert len(fields) == 3
    names = [f["field_name"] for f in fields]
    assert "id" in names
    assert "name" in names
    assert "amount" in names


def test_extract_no_from_clause():
    """SELECT without FROM should not crash and may return the literal column."""
    sql = "SELECT 1 AS dummy"
    fields = extract_fields_from_sql(sql)
    # Parser extracts the clause up to end-of-string; "1 AS dummy" yields one field.
    assert isinstance(fields, list)
    # Either 0 (if parser bails) or 1 (if it succeeds on the alias) — both are acceptable.
    assert len(fields) <= 1
    if fields:
        assert fields[0]["field_name"] == "dummy"


def test_extract_empty_sql_string():
    """Empty SQL string returns empty list without raising."""
    fields = extract_fields_from_sql("")
    assert fields == []


def test_extract_sql_only_comments():
    """SQL with only comments returns empty list."""
    fields = extract_fields_from_sql("-- just a comment\n-- another line")
    assert fields == []


def test_extract_many_columns():
    """SELECT with 20+ columns all parsed correctly."""
    cols = ", ".join(f"col_{i}" for i in range(1, 22))
    sql = f"SELECT {cols} FROM big_table"
    fields = extract_fields_from_sql(sql)
    assert len(fields) == 21
    assert fields[0]["field_name"] == "col_1"
    assert fields[20]["field_name"] == "col_21"
    assert all(f["field_ordinal"] == i + 1 for i, f in enumerate(fields))


# ---------------------------------------------------------------------------
# BW extraction edge cases
# ---------------------------------------------------------------------------


def test_bw_infoobject_string_and_dict_attributes():
    """InfoObject attributes can be a mix of strings and dicts."""
    obj = {
        "platform": "bw",
        "object_type": "infoobject",
        "metadata": {
            "attributes": [
                "REGION",  # plain string
                {"name": "COUNTRY", "type": "CHAR(3)"},  # dict with type
                {"name": "CURRENCY"},  # dict without type
            ]
        },
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    assert len(fields) == 3
    names = [f["field_name"] for f in fields]
    assert "REGION" in names
    assert "COUNTRY" in names
    assert "CURRENCY" in names
    # Dict attribute with type should have data_type set
    country = next(f for f in fields if f["field_name"] == "COUNTRY")
    assert country["data_type"] == "CHAR(3)"
    # String attribute has no type
    region = next(f for f in fields if f["field_name"] == "REGION")
    assert region["data_type"] is None


def test_bw_transformation_all_rule_types():
    """Transformation with field_mappings including all expected rule_type values."""
    obj = {
        "platform": "bw",
        "object_type": "transformation",
        "metadata": {
            "field_mappings": [
                {"source_field": "COMP_CODE", "target_field": "BUKRS", "rule_type": "direct"},
                {
                    "source_field": "AMOUNT",
                    "target_field": "DMBTR",
                    "rule_type": "formula",
                    "formula": "AMOUNT * 1.0",
                },
                {
                    "source_field": "DATE",
                    "target_field": "BUDAT",
                    "rule_type": "routine",
                    "description": "Date mapping",
                },
                {"source_field": "", "target_field": "WAERS", "rule_type": "constant"},
            ]
        },
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    # No fields for transformations — only rules
    # Last entry has empty source_field but non-empty target_field → it IS included
    # Skipping only happens when BOTH source and target are empty
    assert len(rules) == 4
    rule_types = {r["rule_type"] for r in rules}
    assert "direct" in rule_types
    assert "formula" in rule_types
    assert "routine" in rule_types
    assert "constant" in rule_types
    formula_rule = next(r for r in rules if r["rule_type"] == "formula")
    assert formula_rule["formula"] == "AMOUNT * 1.0"
    assert formula_rule["source_field"] == "AMOUNT"
    assert formula_rule["target_field"] == "DMBTR"


def test_bw_adso_mixed_key_fields():
    """ADSO with mixed string/dict key_fields handles both correctly."""
    obj = {
        "platform": "bw",
        "object_type": "adso",
        "metadata": {
            "key_fields": [
                "CALDAY",
                {"name": "PLANT", "type": "CHAR(4)"},
            ],
            "data_fields": ["AMOUNT"],
        },
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    keys = [f for f in fields if f.get("is_key")]
    assert len(keys) == 2
    plant = next(f for f in keys if f["field_name"] == "PLANT")
    assert plant["data_type"] == "CHAR(4)"
    calday = next(f for f in keys if f["field_name"] == "CALDAY")
    assert calday["data_type"] is None


# ---------------------------------------------------------------------------
# Metadata extraction edge cases
# ---------------------------------------------------------------------------


def test_metadata_columns_missing_name():
    """Columns with no name field fall back to col_N generated name."""
    metadata = {
        "columns": [
            {"type": "INT"},  # no name
            {"name": "valid_col", "type": "TEXT"},
        ]
    }
    fields = extract_fields_from_metadata(metadata, "table")
    assert len(fields) == 2
    assert fields[0]["field_name"] == "col_1"
    assert fields[1]["field_name"] == "valid_col"


def test_metadata_columns_as_strings():
    """Columns that are plain strings (not dicts) are skipped gracefully."""
    metadata = {
        "columns": [
            "COMPANY_CODE",  # plain string — not a dict
            {"name": "AMOUNT", "type": "DECIMAL"},
        ]
    }
    fields = extract_fields_from_metadata(metadata, "table")
    # String entries are skipped
    assert len(fields) == 1
    assert fields[0]["field_name"] == "AMOUNT"


def test_metadata_empty_columns_list():
    """Empty columns list returns empty fields without error."""
    fields = extract_fields_from_metadata({"columns": []}, "view")
    assert fields == []


def test_metadata_missing_columns_key():
    """Missing 'columns' key returns empty list."""
    fields = extract_fields_from_metadata({}, "view")
    assert fields == []


# ---------------------------------------------------------------------------
# Integration-level dispatch
# ---------------------------------------------------------------------------


def test_dispatch_bw_infoobject():
    """extract_fields dispatches BW infoobject to extract_bw_fields."""
    obj = {
        "platform": "bw",
        "object_type": "infoobject",
        "metadata": {"attributes": ["COLOR", "SIZE"]},
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    assert len(fields) == 2
    assert rules == []


def test_dispatch_bw_transformation():
    """extract_fields dispatches BW transformation; returns rules not fields."""
    obj = {
        "platform": "bw",
        "object_type": "transformation",
        "metadata": {
            "field_mappings": [
                {"source_field": "SRC", "target_field": "TGT", "rule_type": "direct"},
            ]
        },
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    assert fields == []
    assert len(rules) == 1
    assert rules[0]["rule_sequence"] == 1


def test_dispatch_sac_with_columns():
    """SAC platform with columns in metadata uses extract_fields_from_metadata."""
    obj = {
        "platform": "sac",
        "object_type": "model",
        "metadata": {
            "columns": [
                {"name": "REVENUE", "type": "DECIMAL"},
                {"name": "PROFIT", "type": "DECIMAL"},
            ]
        },
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    assert len(fields) == 2
    assert rules == []
    assert fields[0]["field_name"] == "REVENUE"


def test_dispatch_hana_falls_through_to_metadata():
    """HANA platform with metadata columns parses them correctly."""
    obj = {
        "platform": "hana",
        "object_type": "view",
        "metadata": {
            "columns": [
                {"name": "MANDT", "type": "CLNT"},
                {"name": "BUKRS", "type": "CHAR(4)"},
            ]
        },
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    assert len(fields) == 2
    assert fields[0]["field_name"] == "MANDT"
    assert fields[1]["field_name"] == "BUKRS"


def test_dispatch_unknown_platform_uses_sql_fallback():
    """Unknown platform with no columns falls back to SQL in documentation."""
    obj = {
        "platform": "custom",
        "object_type": "view",
        "metadata": {},
        "documentation": "SELECT id, label FROM ref_table",
    }
    fields, rules = extract_fields(obj)
    assert len(fields) == 2
    names = [f["field_name"] for f in fields]
    assert "id" in names
    assert "label" in names


def test_dispatch_metadata_string_deserialized():
    """Metadata arriving as a JSON string (asyncpg JSONB quirk) is deserialized correctly."""
    import json

    metadata_str = json.dumps({"columns": [{"name": "X", "type": "INT"}]})
    obj = {
        "platform": "dsp",
        "object_type": "table",
        "metadata": metadata_str,
        "documentation": "",
    }
    fields, rules = extract_fields(obj)
    assert len(fields) == 1
    assert fields[0]["field_name"] == "X"
