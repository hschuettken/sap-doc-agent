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
