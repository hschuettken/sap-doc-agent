"""Tests for the Migration Classifier (rules + LLM hybrid)."""

import pytest
from unittest.mock import AsyncMock

from sap_doc_agent.migration.classifier import (
    ActivityData,
    classify_by_rules,
    classify_chain,
    classify_with_llm,
)
from sap_doc_agent.migration.models import (
    ClassifiedChain,
    IntentCard,
    MigrationClassification,
)
from sap_doc_agent.scanner.models import ChainStep, DataFlowChain, ObjectType


def _make_chain(steps=None):
    return DataFlowChain(
        chain_id="c1",
        name="Test",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=steps or [],
        all_object_ids=["S", "T"],
    )


def _make_intent(chain_id="c1", transformations=None):
    return IntentCard(
        chain_id=chain_id,
        business_purpose="Test chain",
        data_domain="SD",
        transformations=transformations or [],
        confidence=0.8,
    )


# --- Rule-based classification tests ---


def test_rule_classify_tcurr_as_simplify():
    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="CurrConv",
                source_code="SELECT * FROM tcurr INTO TABLE lt_tcurr WHERE kurst = 'M'.",
            ),
        ]
    )
    intent = _make_intent()
    result = classify_by_rules(intent, chain)
    assert result is not None
    assert result.classification == MigrationClassification.SIMPLIFY
    assert "tcurr_conversion" in result.rationale


def test_rule_classify_authority_as_replace():
    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="AuthCheck",
                source_code="AUTHORITY-CHECK OBJECT 'S_RS_AUTH' ID 'ACTVT' FIELD '03'.",
            ),
        ]
    )
    intent = _make_intent()
    result = classify_by_rules(intent, chain)
    assert result is not None
    assert result.classification == MigrationClassification.REPLACE


def test_rule_classify_drop_with_activity():
    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Dead",
                source_code="DATA: lv_x TYPE i.",
            ),
        ]
    )
    intent = _make_intent()
    activity = ActivityData(last_execution="2024-01-15", query_usage_count=0)
    result = classify_by_rules(intent, chain, activity)
    assert result is not None
    assert result.classification == MigrationClassification.DROP
    assert result.needs_human_review is True
    assert result.last_execution == "2024-01-15"


def test_rule_classify_returns_none_no_patterns():
    """Chain with no pattern matches returns None (needs LLM)."""
    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Custom",
                source_code="DATA: lv_custom TYPE i.\nlv_custom = 42.",
            ),
        ]
    )
    intent = _make_intent()
    result = classify_by_rules(intent, chain)
    assert result is None


def test_rule_classify_multiple_patterns():
    """Chain with TCURR + READ TABLE should get SIMPLIFY (majority)."""
    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Mixed",
                source_code=(
                    "SELECT * FROM tcurr INTO TABLE lt_tcurr.\n"
                    "READ TABLE lt_customer INTO DATA(ls) WITH KEY kunnr = <s>-kunnr.\n"
                    "LOOP AT SOURCE_PACKAGE ASSIGNING FIELD-SYMBOL(<s>).\nENDLOOP."
                ),
            ),
        ]
    )
    intent = _make_intent()
    result = classify_by_rules(intent, chain)
    assert result is not None
    assert result.classification == MigrationClassification.SIMPLIFY


def test_rule_classify_effort_trivial():
    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Simple",
                source_code="DELETE SOURCE_PACKAGE WHERE auart = 'ZT'.",
            ),
        ]
    )
    intent = _make_intent()
    result = classify_by_rules(intent, chain)
    assert result is not None
    assert result.effort_category == "trivial"


def test_rule_classify_step_classifications():
    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Filter",
                source_code="DELETE SOURCE_PACKAGE WHERE bukrs = '1000'.",
            ),
            ChainStep(
                position=2,
                object_id="TR2",
                object_type=ObjectType.TRANSFORMATION,
                name="Convert",
                source_code="SELECT * FROM tcurr INTO TABLE lt_tcurr.",
            ),
        ]
    )
    intent = _make_intent()
    result = classify_by_rules(intent, chain)
    assert result is not None
    assert len(result.step_classifications) == 2
    assert all(sc.classification == MigrationClassification.SIMPLIFY for sc in result.step_classifications)


# --- LLM classification tests ---


@pytest.mark.asyncio
async def test_llm_classify_returns_classified_chain():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"classification": "migrate",'
        '"rationale": "Real business need, complex logic",'
        '"step_classifications": [{"step_number": 1, "classification": "migrate",'
        '"rationale": "Custom business logic", "dsp_equivalent": "SQL view"}],'
        '"effort_category": "moderate",'
        '"effort_rationale": "3 steps with moderate complexity",'
        '"confidence": 0.82,'
        '"needs_human_review": false}'
    )

    chain = _make_chain()
    intent = _make_intent()
    result = await classify_with_llm(intent, chain, mock_llm)
    assert isinstance(result, ClassifiedChain)
    assert result.classification == MigrationClassification.MIGRATE
    assert result.effort_category == "moderate"


@pytest.mark.asyncio
async def test_llm_classify_none_becomes_clarify():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = None

    chain = _make_chain()
    intent = _make_intent()
    result = await classify_with_llm(intent, chain, mock_llm)
    assert result.classification == MigrationClassification.CLARIFY
    assert result.needs_human_review is True
    assert result.confidence == 0.0


@pytest.mark.asyncio
async def test_llm_classify_low_confidence_flags_review():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"classification": "simplify",'
        '"rationale": "Probably simplifiable",'
        '"confidence": 0.5,'
        '"needs_human_review": false}'
    )

    chain = _make_chain()
    intent = _make_intent()
    result = await classify_with_llm(intent, chain, mock_llm, confidence_threshold=0.7)
    assert result.needs_human_review is True  # overridden by low confidence


# --- Hybrid classify_chain tests ---


@pytest.mark.asyncio
async def test_classify_chain_prefers_rules():
    """If rules match, LLM should not be called."""
    mock_llm = AsyncMock()

    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="CurrConv",
                source_code="SELECT * FROM tcurr INTO TABLE lt_tcurr.",
            ),
        ]
    )
    intent = _make_intent()
    result = await classify_chain(intent, chain, mock_llm)
    assert result.classification == MigrationClassification.SIMPLIFY
    # LLM should NOT have been called
    mock_llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_classify_chain_falls_back_to_llm():
    """If rules return None, LLM is used."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"classification": "migrate","rationale": "Custom business logic","confidence": 0.9}'
    )

    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Custom",
                source_code="DATA: lv_x TYPE i.\nlv_x = 42.",
            ),
        ]
    )
    intent = _make_intent()
    result = await classify_chain(intent, chain, mock_llm)
    assert result.classification == MigrationClassification.MIGRATE
    assert mock_llm.generate.call_count >= 1


def test_migrate_classification_not_in_rule_patterns():
    """MIGRATE is only reachable via LLM — no rule pattern defaults to it.

    This is by design (spec §5.3): rules handle SIMPLIFY/REPLACE/DROP/CLARIFY,
    LLM handles 'real business need, design fresh for DSP' (MIGRATE).
    """
    from sap_doc_agent.migration.bw_patterns import BW_PATTERNS

    rule_classifications = {p.classification for p in BW_PATTERNS}
    assert MigrationClassification.MIGRATE not in rule_classifications
