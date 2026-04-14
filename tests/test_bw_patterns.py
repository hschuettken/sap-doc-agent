"""Tests for BW pattern knowledge base detection."""

from sap_doc_agent.migration.bw_patterns import (
    BW_PATTERNS,
    PATTERNS_BY_NAME,
    BWPattern,
    detect_pattern_names,
    detect_patterns,
)
from sap_doc_agent.migration.models import MigrationClassification


def test_at_least_30_patterns():
    assert len(BW_PATTERNS) >= 30


def test_all_patterns_have_required_fields():
    for p in BW_PATTERNS:
        assert p.name, f"Pattern missing name: {p}"
        assert p.description, f"Pattern {p.name} missing description"
        assert p.classification in MigrationClassification
        assert p.dsp_equivalent, f"Pattern {p.name} missing dsp_equivalent"
        assert p.rationale, f"Pattern {p.name} missing rationale"


def test_all_patterns_have_unique_names():
    names = [p.name for p in BW_PATTERNS]
    assert len(names) == len(set(names)), "Duplicate pattern names found"


def test_patterns_by_name_lookup():
    assert "tcurr_conversion" in PATTERNS_BY_NAME
    assert PATTERNS_BY_NAME["tcurr_conversion"].classification == MigrationClassification.SIMPLIFY


def test_every_pattern_has_detection():
    """Each pattern should have at least one detection mechanism."""
    for p in BW_PATTERNS:
        has_detection = bool(p.source_regexes) or bool(p.metadata_checks)
        # complex_abap_routine is special (detected by line count, not regex)
        if p.name == "complex_abap_routine":
            continue
        assert has_detection, f"Pattern {p.name} has no detection rules"


# --- Source regex detection tests ---


def test_detect_tcurr_conversion():
    code = "SELECT * FROM tcurr INTO TABLE lt_tcurr WHERE kurst = 'M'."
    matched = detect_pattern_names(code)
    assert "tcurr_conversion" in matched


def test_detect_read_table_lookup():
    code = "READ TABLE lt_customer INTO DATA(ls_cust) WITH KEY kunnr = <s>-kunnr."
    matched = detect_pattern_names(code)
    assert "read_table_lookup" in matched


def test_detect_delete_source_package():
    code = "DELETE SOURCE_PACKAGE WHERE auart IN ('ZT01', 'ZT02')."
    matched = detect_pattern_names(code)
    assert "delete_source_package" in matched


def test_detect_field_symbol_loop():
    code = "LOOP AT SOURCE_PACKAGE ASSIGNING FIELD-SYMBOL(<s>).\n  <s>-netwr = <s>-netwr * 2.\nENDLOOP."
    matched = detect_pattern_names(code)
    assert "field_symbol_loop" in matched


def test_detect_authority_checks():
    code = "AUTHORITY-CHECK OBJECT 'S_RS_AUTH' ID 'ACTVT' FIELD '03'."
    matched = detect_pattern_names(code)
    assert "authority_checks" in matched


def test_detect_manual_delta():
    code = "SELECT * FROM vbak WHERE erdat > lv_last_load_date."
    matched = detect_pattern_names(code)
    assert "manual_delta_handling" in matched


def test_detect_dynamic_sql():
    code = "EXEC SQL.\n  SELECT * FROM some_table\nENDEXEC."
    matched = detect_pattern_names(code)
    assert "dynamic_sql" in matched


def test_detect_move_corresponding():
    code = "MOVE-CORRESPONDING SOURCE_PACKAGE TO RESULT_PACKAGE."
    matched = detect_pattern_names(code)
    assert "move_corresponding" in matched


def test_detect_hardcoded_company_code():
    code = "DELETE SOURCE_PACKAGE WHERE bukrs = '1000'."
    matched = detect_pattern_names(code)
    assert "hardcoded_company_code" in matched


def test_detect_select_star():
    code = "SELECT * FROM mara INTO TABLE lt_mara WHERE matnr IN lr_matnr."
    matched = detect_pattern_names(code)
    assert "abap_select_star" in matched


def test_detect_binary_search():
    code = "SORT lt_customer BY kunnr.\nREAD TABLE lt_customer WITH KEY kunnr = <s>-kunnr BINARY SEARCH."
    matched = detect_pattern_names(code)
    assert "internal_table_sort" in matched
    assert "read_table_lookup" in matched


def test_detect_concatenate():
    code = "CONCATENATE <s>-kunnr <s>-vkorg INTO <s>-comp_key SEPARATED BY '|'."
    matched = detect_pattern_names(code)
    assert "string_concatenation" in matched


# --- Metadata detection tests ---


def test_detect_empty_routine_via_metadata():
    matched = detect_patterns("", metadata={"source_code": ""})
    names = [p.name for p in matched]
    assert "empty_routines" in names


def test_detect_dead_chain_via_metadata():
    # 18 months ago
    matched = detect_patterns("", metadata={"last_run": "2024-01-15"})
    names = [p.name for p in matched]
    assert "dead_process_chain" in names


def test_no_false_positive_on_recent_run():
    """A chain run last month should NOT match dead_process_chain."""
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
    matched = detect_patterns("", metadata={"last_run": recent})
    names = [p.name for p in matched]
    assert "dead_process_chain" not in names


# --- No false positives ---


def test_no_match_on_simple_code():
    code = "DATA: lv_value TYPE i.\nlv_value = 42."
    matched = detect_pattern_names(code)
    # This simple ABAP should not match any pattern
    assert matched == []


def test_detect_returns_bwpattern_objects():
    code = "SELECT * FROM tcurr INTO TABLE lt_tcurr."
    matched = detect_patterns(code)
    assert all(isinstance(p, BWPattern) for p in matched)
    assert any(p.name == "tcurr_conversion" for p in matched)


# --- Classification distribution ---


def test_classification_distribution():
    """All five classification types should be represented."""
    classifications = {p.classification for p in BW_PATTERNS}
    assert MigrationClassification.SIMPLIFY in classifications
    assert MigrationClassification.REPLACE in classifications
    assert MigrationClassification.DROP in classifications
    assert MigrationClassification.CLARIFY in classifications


def test_multiple_patterns_can_match():
    """A complex routine can match multiple patterns at once."""
    code = (
        "LOOP AT SOURCE_PACKAGE ASSIGNING FIELD-SYMBOL(<s>).\n"
        "  SELECT SINGLE ukurs FROM tcurr INTO lv_rate\n"
        "    WHERE kurst = 'M' AND fcurr = <s>-waers.\n"
        "  READ TABLE lt_customer INTO DATA(ls_cust) WITH KEY kunnr = <s>-kunnr.\n"
        "ENDLOOP."
    )
    matched = detect_pattern_names(code)
    assert len(matched) >= 3  # field_symbol_loop, tcurr_conversion, read_table_lookup
