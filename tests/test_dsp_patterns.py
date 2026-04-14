"""Tests for the DSP Pattern Knowledge Base."""

from sap_doc_agent.migration.dsp_patterns import (
    DSP_SQL_RULES,
    LAYER_PREFIXES,
    PERSISTENCE_THRESHOLDS,
    SEMANTIC_USAGES,
    STEP_COLLAPSE_PATTERNS,
    CollapsePattern,
    DSPLayer,
    DSPSQLRule,
    get_prefix_for_layer_and_usage,
    suggest_collapse,
    suggest_layer,
    suggest_persistence,
    suggest_semantic_usage,
)


# --- Layer & naming tests ---


def test_dsp_layers_cover_four_layers():
    names = [l.value for l in DSPLayer]
    assert "staging" in names
    assert "harmonization" in names
    assert "mart" in names
    assert "consumption" in names


def test_layer_prefixes_exist_for_all_combinations():
    assert len(LAYER_PREFIXES) >= 8
    # Key prefixes from KNOWLEDGE.md
    assert LAYER_PREFIXES[("staging", "local_table")] == "01_LT_"
    assert LAYER_PREFIXES[("staging", "remote_table")] == "01_RT_"
    assert LAYER_PREFIXES[("staging", "replication_flow")] == "01_RF_"
    assert LAYER_PREFIXES[("harmonization", "relational_dataset")] == "02_RV_"
    assert LAYER_PREFIXES[("harmonization", "fact")] == "02_FV_"
    assert LAYER_PREFIXES[("harmonization", "dimension")] == "02_MD_"
    assert LAYER_PREFIXES[("harmonization", "helper")] == "02_HV_"
    assert LAYER_PREFIXES[("mart", "fact")] == "03_FV_"
    assert LAYER_PREFIXES[("mart", "helper")] == "03_HV_"


def test_get_prefix_returns_correct_prefix():
    assert get_prefix_for_layer_and_usage("harmonization", "fact") == "02_FV_"
    assert get_prefix_for_layer_and_usage("mart", "helper") == "03_HV_"


def test_get_prefix_returns_none_for_unknown():
    assert get_prefix_for_layer_and_usage("unknown", "thing") is None


def test_semantic_usages_defined():
    assert "relational_dataset" in SEMANTIC_USAGES
    assert "fact" in SEMANTIC_USAGES
    assert "dimension" in SEMANTIC_USAGES
    assert "text" in SEMANTIC_USAGES
    assert "hierarchy" in SEMANTIC_USAGES


# --- SQL rule tests ---


def test_sql_rules_count():
    assert len(DSP_SQL_RULES) >= 8


def test_every_sql_rule_has_required_fields():
    for rule in DSP_SQL_RULES:
        assert isinstance(rule, DSPSQLRule)
        assert rule.rule_id
        assert rule.description
        assert rule.severity in ("error", "warning")


def test_sql_rules_have_unique_ids():
    ids = [r.rule_id for r in DSP_SQL_RULES]
    assert len(ids) == len(set(ids))


def test_sql_rules_include_mandatory_rules():
    ids = {r.rule_id for r in DSP_SQL_RULES}
    assert "no_cte" in ids
    assert "limit_in_union" in ids
    assert "union_aliases" in ids
    assert "no_select_star_cross_space" in ids
    assert "cross_space_prefix" in ids
    assert "no_arrow_in_comments" in ids
    assert "datab_desc_in_row_number" in ids
    assert "varchar_date_comparison" in ids


# --- Persistence tests ---


def test_persistence_thresholds_exist():
    assert len(PERSISTENCE_THRESHOLDS) >= 3


def test_suggest_persistence_for_cross_join():
    result = suggest_persistence(
        has_cross_join=True,
        preview_seconds=5,
        consumer_count=1,
    )
    assert result is True


def test_suggest_persistence_for_slow_preview():
    result = suggest_persistence(
        has_cross_join=False,
        preview_seconds=45,
        consumer_count=1,
    )
    assert result is True


def test_suggest_persistence_for_many_consumers():
    result = suggest_persistence(
        has_cross_join=False,
        preview_seconds=5,
        consumer_count=5,
    )
    assert result is True


def test_suggest_no_persistence_for_simple_view():
    result = suggest_persistence(
        has_cross_join=False,
        preview_seconds=2,
        consumer_count=1,
    )
    assert result is False


# --- Step collapse tests ---


def test_collapse_patterns_exist():
    assert len(STEP_COLLAPSE_PATTERNS) >= 3


def test_collapse_pattern_has_required_fields():
    for p in STEP_COLLAPSE_PATTERNS:
        assert isinstance(p, CollapsePattern)
        assert p.name
        assert p.bw_pattern
        assert p.dsp_replacement
        assert p.rationale


def test_suggest_collapse_for_delta_chain():
    """Multi-step chain with delta staging should suggest collapse."""
    result = suggest_collapse(
        step_classifications=["simplify", "simplify", "migrate"],
        has_delta_staging=True,
        total_steps=3,
    )
    assert len(result) >= 1
    assert any("delta" in c.name.lower() or "staging" in c.name.lower() for c in result)


def test_suggest_collapse_for_no_patterns():
    """Chain with no collapsible patterns returns empty."""
    result = suggest_collapse(
        step_classifications=["migrate"],
        has_delta_staging=False,
        total_steps=1,
    )
    assert len(result) == 0


# --- Layer/usage suggestion tests ---


def test_suggest_layer_for_replication():
    assert suggest_layer("replication") == DSPLayer.STAGING


def test_suggest_layer_for_transformation():
    assert suggest_layer("transformation") == DSPLayer.HARMONIZATION


def test_suggest_layer_for_aggregation():
    assert suggest_layer("aggregation") == DSPLayer.MART


def test_suggest_layer_for_consumption():
    assert suggest_layer("consumption") == DSPLayer.CONSUMPTION


def test_suggest_semantic_usage_for_master_data():
    assert suggest_semantic_usage("customer master data") == "dimension"


def test_suggest_semantic_usage_for_transactions():
    assert suggest_semantic_usage("billing transactions with revenue") == "fact"


def test_suggest_semantic_usage_for_staging():
    assert suggest_semantic_usage("intermediate staging") == "relational_dataset"
