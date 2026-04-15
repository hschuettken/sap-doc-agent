"""Tests for the DSP SQL Validator — one test per rule."""

from spec2sphere.migration.sql_validator import (
    SQLValidationResult,
    SQLViolation,
    validate_dsp_sql,
)


# --- Rule 1: No CTE ---


def test_no_cte_detects_with_clause():
    sql = "WITH cte AS (SELECT 1) SELECT * FROM cte"
    result = validate_dsp_sql(sql)
    assert not result.is_valid
    violations = [v for v in result.violations if v.rule_id == "no_cte"]
    assert len(violations) >= 1


def test_no_cte_passes_clean_sql():
    sql = "SELECT * FROM (SELECT 1) cte"
    result = validate_dsp_sql(sql)
    cte_violations = [v for v in result.violations if v.rule_id == "no_cte"]
    assert len(cte_violations) == 0


def test_no_cte_case_insensitive():
    sql = "with my_cte AS (SELECT 1) SELECT * FROM my_cte"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "no_cte"]
    assert len(violations) >= 1


# --- Rule 2: LIMIT inside UNION ALL ---


def test_limit_in_union_detects_unwrapped():
    sql = "SELECT 'a' AS col LIMIT 1\nUNION ALL\nSELECT 'b' AS col LIMIT 1"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "limit_in_union"]
    assert len(violations) >= 1


def test_limit_in_union_passes_wrapped():
    sql = "(SELECT 'a' AS col LIMIT 1)\nUNION ALL\n(SELECT 'b' AS col LIMIT 1)"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "limit_in_union"]
    assert len(violations) == 0


def test_limit_without_union_is_ok():
    sql = "SELECT * FROM t LIMIT 10"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "limit_in_union"]
    assert len(violations) == 0


# --- Rule 3: Column aliases on every UNION ALL leg ---


def test_union_aliases_detects_missing():
    sql = 'SELECT col1 AS "Name" FROM t1\nUNION ALL\nSELECT col2 FROM t2'
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "union_aliases"]
    assert len(violations) >= 1


def test_union_aliases_passes_all_aliased():
    sql = 'SELECT col1 AS "Name" FROM t1\nUNION ALL\nSELECT col2 AS "Name" FROM t2'
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "union_aliases"]
    assert len(violations) == 0


# --- Rule 4: No SELECT * on cross-space joins ---


def test_no_select_star_cross_space_detects():
    sql = 'SELECT * FROM "OTHER_SPACE"."view_name"'
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "no_select_star_cross_space"]
    assert len(violations) >= 1


def test_no_select_star_cross_space_passes_explicit():
    sql = 'SELECT a."COL1", a."COL2" FROM "OTHER_SPACE"."view_name" a'
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "no_select_star_cross_space"]
    assert len(violations) == 0


def test_select_star_same_space_ok():
    sql = "SELECT * FROM my_local_view"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "no_select_star_cross_space"]
    assert len(violations) == 0


# --- Rule 5: Cross-space references need full prefix ---


def test_cross_space_prefix_detects_unquoted():
    sql = "SELECT a.COL1 FROM SAP_ADMIN.my_view a"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "cross_space_prefix"]
    assert len(violations) >= 1


def test_cross_space_prefix_passes_quoted():
    sql = 'SELECT a."COL1" FROM "SAP_ADMIN"."my_view" a'
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "cross_space_prefix"]
    assert len(violations) == 0


def test_cross_space_prefix_passes_local_view():
    sql = "SELECT col1 FROM my_local_view"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "cross_space_prefix"]
    assert len(violations) == 0


# --- Rule 6: No --> inside block comments ---


def test_no_arrow_in_comments_detects():
    sql = "/* This --> breaks the parser */\nSELECT 1"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "no_arrow_in_comments"]
    assert len(violations) >= 1


def test_no_arrow_in_comments_passes_clean():
    sql = "/* This => works fine */\nSELECT 1"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "no_arrow_in_comments"]
    assert len(violations) == 0


def test_arrow_outside_comment_ok():
    sql = "SELECT CASE WHEN a --> 0 THEN 1 END FROM t"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "no_arrow_in_comments"]
    assert len(violations) == 0


# --- Rule 7: DATAB DESC in ROW_NUMBER ---


def test_datab_desc_detects_missing():
    sql = "ROW_NUMBER() OVER (\n  PARTITION BY MATNR, KUNNR\n  ORDER BY ACCESS_PRIORITY ASC\n) AS RN"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "datab_desc_in_row_number"]
    assert len(violations) >= 1


def test_datab_desc_passes_when_present():
    sql = "ROW_NUMBER() OVER (\n  PARTITION BY MATNR, KUNNR\n  ORDER BY ACCESS_PRIORITY ASC, DATAB DESC\n) AS RN"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "datab_desc_in_row_number"]
    assert len(violations) == 0


def test_datab_desc_not_flagged_without_row_number():
    sql = "SELECT * FROM t ORDER BY ACCESS_PRIORITY ASC"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "datab_desc_in_row_number"]
    assert len(violations) == 0


# --- Rule 8: VARCHAR date comparison ---


def test_varchar_date_detects_current_date():
    sql = "WHERE DATAB <= CURRENT_DATE"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "varchar_date_comparison"]
    assert len(violations) >= 1


def test_varchar_date_passes_string_format():
    sql = "WHERE DATAB <= '20260101'"
    result = validate_dsp_sql(sql)
    violations = [v for v in result.violations if v.rule_id == "varchar_date_comparison"]
    assert len(violations) == 0


# --- Result structure ---


def test_validation_result_is_valid_when_no_violations():
    sql = "SELECT col1, col2 FROM my_table WHERE col1 = 'A'"
    result = validate_dsp_sql(sql)
    assert result.is_valid
    assert len(result.violations) == 0


def test_validation_result_has_violations():
    sql = "WITH cte AS (SELECT 1) SELECT * FROM cte"
    result = validate_dsp_sql(sql)
    assert isinstance(result, SQLValidationResult)
    for v in result.violations:
        assert isinstance(v, SQLViolation)
        assert v.rule_id
        assert v.message
        assert v.severity in ("error", "warning")


def test_validate_empty_sql():
    result = validate_dsp_sql("")
    assert result.is_valid
    assert len(result.violations) == 0


def test_validate_multiple_violations():
    sql = 'WITH cte AS (SELECT 1)\n/* This --> breaks */\nSELECT * FROM "OTHER"."view"'
    result = validate_dsp_sql(sql)
    assert not result.is_valid
    assert len(result.violations) >= 2
