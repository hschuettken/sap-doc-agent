"""Tests for the DSP Architect (classified chains → target architecture)."""

import pytest
from unittest.mock import AsyncMock

from spec2sphere.migration.architect import design_target_architecture, design_chain_views
from spec2sphere.migration.models import (
    ClassifiedChain,
    IntentCard,
    MigrationClassification,
    StepClassification,
    TargetArchitecture,
    TransformationIntent,
    ViewSpec,
)
from spec2sphere.scanner.models import ChainStep, DataFlowChain, ObjectType


def _make_chain(steps=None):
    return DataFlowChain(
        chain_id="c1",
        name="Revenue Chain",
        terminal_object_id="CMP_REV",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["DS_BILLING"],
        steps=steps or [],
        all_object_ids=["DS_BILLING", "CMP_REV"],
    )


def _make_intent(chain_id="c1", data_domain="SD"):
    return IntentCard(
        chain_id=chain_id,
        business_purpose="Monthly revenue reporting",
        data_domain=data_domain,
        key_entities=["Customer", "Material"],
        key_measures=["Net Revenue (EUR)"],
        grain="Customer × Material × Month",
        consumers=["BEx Query ZQ_REV"],
        transformations=[
            TransformationIntent(
                step_number=1,
                intent="Filter test orders",
                implementation="DELETE SOURCE_PACKAGE WHERE auart = 'ZT'",
                is_business_logic=True,
            ),
            TransformationIntent(
                step_number=2,
                intent="Convert currency to EUR",
                implementation="TCURR lookup",
                is_business_logic=True,
                simplification_note="Use CASE WHEN in DSP",
            ),
        ],
        confidence=0.9,
    )


def _make_classified(
    classification=MigrationClassification.MIGRATE,
    effort="moderate",
):
    intent = _make_intent()
    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Filter",
                source_code="DELETE SOURCE_PACKAGE WHERE auart = 'ZT'.",
            ),
            ChainStep(
                position=2,
                object_id="TR2",
                object_type=ObjectType.TRANSFORMATION,
                name="CurrConv",
                source_code="SELECT * FROM tcurr INTO TABLE lt_tcurr.",
            ),
        ]
    )
    return (
        ClassifiedChain(
            chain_id="c1",
            intent_card=intent,
            classification=classification,
            rationale="Real business need",
            step_classifications=[
                StepClassification(
                    step_number=1,
                    object_id="TR1",
                    classification=MigrationClassification.SIMPLIFY,
                    rationale="Simple filter",
                    dsp_equivalent="WHERE clause",
                ),
                StepClassification(
                    step_number=2,
                    object_id="TR2",
                    classification=MigrationClassification.SIMPLIFY,
                    rationale="TCURR conversion",
                    dsp_equivalent="CASE WHEN or JOIN",
                ),
            ],
            effort_category=effort,
            confidence=0.85,
        ),
        chain,
    )


# --- design_chain_views tests ---


@pytest.mark.asyncio
async def test_design_chain_views_returns_view_specs():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"views": ['
        '  {"technical_name": "02_RV_BILLING_CLEAN", "space": "SAP_ADMIN",'
        '   "layer": "harmonization", "semantic_usage": "relational_dataset",'
        '   "description": "Filter + currency conversion",'
        '   "sql_logic": "SELECT ... FROM 01_LT_BILLING WHERE auart <> \'ZT\'",'
        '   "collapse_rationale": "Steps 1-2 merged: filter + convert in one view",'
        '   "collapsed_bw_steps": ["TR1", "TR2"],'
        '   "persistence": false},'
        '  {"technical_name": "03_FV_REVENUE_MONTHLY", "space": "SAP_ADMIN",'
        '   "layer": "mart", "semantic_usage": "fact",'
        '   "description": "Monthly revenue fact",'
        '   "sql_logic": "SELECT ... GROUP BY CALMONTH",'
        '   "persistence": true,'
        '   "persistence_rationale": "Large aggregation, multiple consumers"}'
        "]}"
    )

    classified, chain = _make_classified()
    views = await design_chain_views(classified, chain, mock_llm)
    assert len(views) >= 1
    assert all(isinstance(v, ViewSpec) for v in views)
    assert mock_llm.generate.call_count >= 1


@pytest.mark.asyncio
async def test_design_chain_views_includes_source_chains():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"views": [{"technical_name": "02_RV_TEST", "space": "SAP_ADMIN",'
        '"layer": "harmonization", "semantic_usage": "relational_dataset",'
        '"description": "Test view", "source_chains": ["c1"],'
        '"sql_logic": "SELECT 1", "persistence": false}]}'
    )
    classified, chain = _make_classified()
    views = await design_chain_views(classified, chain, mock_llm)
    assert views[0].source_chains == ["c1"]


@pytest.mark.asyncio
async def test_design_chain_views_llm_failure_returns_fallback():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = None

    classified, chain = _make_classified()
    views = await design_chain_views(classified, chain, mock_llm)
    # Fallback should produce at least one view from heuristics
    assert len(views) >= 1
    assert views[0].technical_name != ""


# --- design_target_architecture tests ---


@pytest.mark.asyncio
async def test_design_target_architecture_returns_architecture():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"views": [{"technical_name": "02_RV_BILLING", "space": "SAP_ADMIN",'
        '"layer": "harmonization", "semantic_usage": "relational_dataset",'
        '"description": "Billing clean", "sql_logic": "SELECT 1",'
        '"persistence": false}]}'
    )

    classified, chain = _make_classified()
    chains_with_data = [(classified, chain)]
    arch = await design_target_architecture("Test Project", chains_with_data, mock_llm)

    assert isinstance(arch, TargetArchitecture)
    assert arch.project_name == "Test Project"
    assert len(arch.views) >= 1
    assert len(arch.migration_sequence) >= 1


@pytest.mark.asyncio
async def test_design_skips_drop_chains():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"views": [{"technical_name": "02_RV_TEST", "space": "SAP_ADMIN",'
        '"layer": "harmonization", "semantic_usage": "relational_dataset",'
        '"description": "Test", "sql_logic": "SELECT 1", "persistence": false}]}'
    )

    migrate_classified, chain1 = _make_classified(MigrationClassification.MIGRATE)
    drop_intent = _make_intent(chain_id="c2")
    drop_classified = ClassifiedChain(
        chain_id="c2",
        intent_card=drop_intent,
        classification=MigrationClassification.DROP,
        rationale="Dead chain",
        confidence=0.9,
    )
    chain2 = _make_chain()

    arch = await design_target_architecture(
        "Test",
        [(migrate_classified, chain1), (drop_classified, chain2)],
        mock_llm,
    )
    # Only the MIGRATE chain should produce views
    assert all("c2" not in v.source_chains for v in arch.views if v.source_chains)


@pytest.mark.asyncio
async def test_design_produces_migration_sequence_in_order():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"views": ['
        '  {"technical_name": "01_LT_SRC", "space": "SAP_ADMIN", "layer": "staging",'
        '   "semantic_usage": "relational_dataset", "description": "Source",'
        '   "sql_logic": "", "persistence": false},'
        '  {"technical_name": "02_RV_CLEAN", "space": "SAP_ADMIN", "layer": "harmonization",'
        '   "semantic_usage": "relational_dataset", "description": "Clean",'
        '   "sql_logic": "SELECT 1", "source_objects": ["01_LT_SRC"], "persistence": false},'
        '  {"technical_name": "03_FV_FACT", "space": "SAP_ADMIN", "layer": "mart",'
        '   "semantic_usage": "fact", "description": "Fact",'
        '   "sql_logic": "SELECT 1", "source_objects": ["02_RV_CLEAN"], "persistence": true}'
        "]}"
    )

    classified, chain = _make_classified()
    arch = await design_target_architecture("Test", [(classified, chain)], mock_llm)
    if arch.migration_sequence:
        orders = [s.order for s in arch.migration_sequence]
        assert orders == sorted(orders)


@pytest.mark.asyncio
async def test_design_prompt_includes_dsp_rules():
    """The architect prompt should inject DSP SQL rules and naming conventions."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"views": [{"technical_name": "02_RV_T", "space": "S", "layer": "harmonization",'
        '"semantic_usage": "relational_dataset", "description": "T",'
        '"sql_logic": "SELECT 1", "persistence": false}]}'
    )

    classified, chain = _make_classified()
    await design_chain_views(classified, chain, mock_llm)
    call_args = mock_llm.generate.call_args
    prompt = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    # Should mention DSP rules
    assert "no_cte" in prompt.lower() or "cte" in prompt.lower()
    assert "01_LT_" in prompt or "02_RV_" in prompt


@pytest.mark.asyncio
async def test_design_fallback_documents_collapse_rationale():
    """Heuristic fallback should document collapse rationale for merged views."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = None  # Force fallback

    classified, chain = _make_classified()
    views = await design_chain_views(classified, chain, mock_llm)
    # Fallback merges all steps — should document why
    for v in views:
        if v.collapsed_bw_steps:
            assert v.collapse_rationale != "", f"View {v.technical_name} missing collapse_rationale"


@pytest.mark.asyncio
async def test_design_migration_sequence_respects_dependencies():
    """Migration sequence should order views by dependency, not just layer."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"views": ['
        '  {"technical_name": "02_RV_A", "space": "SAP_ADMIN", "layer": "harmonization",'
        '   "semantic_usage": "relational_dataset", "description": "View A",'
        '   "sql_logic": "SELECT 1", "source_objects": ["01_LT_SRC"], "persistence": false},'
        '  {"technical_name": "02_RV_B", "space": "SAP_ADMIN", "layer": "harmonization",'
        '   "semantic_usage": "relational_dataset", "description": "View B depends on A",'
        '   "sql_logic": "SELECT 1", "source_objects": ["02_RV_A"], "persistence": false},'
        '  {"technical_name": "03_FV_C", "space": "SAP_ADMIN", "layer": "mart",'
        '   "semantic_usage": "fact", "description": "Fact depends on B",'
        '   "sql_logic": "SELECT 1", "source_objects": ["02_RV_B"], "persistence": true}'
        "]}"
    )

    classified, chain = _make_classified()
    arch = await design_target_architecture("Test", [(classified, chain)], mock_llm)
    # A must come before B, B must come before C
    names = [s.view_name for s in arch.migration_sequence]
    assert names.index("02_RV_A") < names.index("02_RV_B")
    assert names.index("02_RV_B") < names.index("03_FV_C")
