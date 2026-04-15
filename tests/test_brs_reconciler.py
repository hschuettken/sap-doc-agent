"""Tests for BRS Reconciler."""

import pytest
from unittest.mock import AsyncMock

from spec2sphere.migration.brs_reconciler import reconcile_brs, reconcile_brs_folder
from spec2sphere.migration.models import BRSDelta, BRSReference, IntentCard, TransformationIntent


def _make_intent_card():
    return IntentCard(
        chain_id="chain_001",
        business_purpose="Monthly net revenue by customer in EUR",
        data_domain="Sales & Distribution",
        grain="Customer × Material × Month",
        key_measures=["Net Revenue (EUR)"],
        transformations=[
            TransformationIntent(
                step_number=1,
                intent="Filter test orders",
                implementation="DELETE SOURCE_PACKAGE",
            ),
            TransformationIntent(
                step_number=2,
                intent="Convert to EUR",
                implementation="TCURR lookup",
            ),
        ],
        confidence=0.85,
    )


@pytest.mark.asyncio
async def test_reconcile_brs_returns_structure():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"brs_says": "Monthly revenue for DE company codes",'
        '"bw_does": "Monthly revenue for DE, AT, and CH",'
        '"deltas": [{"area": "scope", "brs_requirement": "DE only",'
        '"bw_implementation": "DE + AT + CH", "delta_type": "scope_creep",'
        '"impact": "medium", "notes": "Added in CR-2019-047"}],'
        '"matched_requirements": ["REQ-001", "REQ-002"],'
        '"unmatched_requirements": ["REQ-005"],'
        '"confidence": 0.8}'
    )

    card = _make_intent_card()
    result = await reconcile_brs(card, "BRS_Revenue.md", "# Revenue BRS\n...", mock_llm)

    assert result["brs_says"] == "Monthly revenue for DE company codes"
    assert result["bw_does"] == "Monthly revenue for DE, AT, and CH"
    assert len(result["deltas"]) == 1
    assert isinstance(result["deltas"][0], BRSDelta)
    assert result["deltas"][0].delta_type == "scope_creep"
    assert len(result["brs_references"]) == 2
    assert isinstance(result["brs_references"][0], BRSReference)
    assert result["unmatched_requirements"] == ["REQ-005"]
    assert result["confidence"] == 0.8


@pytest.mark.asyncio
async def test_reconcile_brs_no_deltas():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"brs_says": "Revenue by customer",'
        '"bw_does": "Revenue by customer",'
        '"deltas": [],'
        '"matched_requirements": ["REQ-001"],'
        '"unmatched_requirements": [],'
        '"confidence": 0.95}'
    )

    card = _make_intent_card()
    result = await reconcile_brs(card, "BRS.md", "content", mock_llm)
    assert result["deltas"] == []
    assert result["confidence"] == 0.95


@pytest.mark.asyncio
async def test_reconcile_brs_none_response():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = None

    card = _make_intent_card()
    result = await reconcile_brs(card, "BRS.md", "content", mock_llm)
    assert result["confidence"] == 0.0
    assert result["deltas"] == []


@pytest.mark.asyncio
async def test_reconcile_brs_folder(tmp_path):
    """Test folder-level reconciliation reads all .md files."""
    brs_dir = tmp_path / "brs"
    brs_dir.mkdir()
    (brs_dir / "BRS_Revenue.md").write_text("# Revenue Spec\nMonthly revenue reporting")
    (brs_dir / "BRS_Inventory.md").write_text("# Inventory Spec\nDaily stock levels")
    (brs_dir / "notes.txt").write_text("Not a BRS")  # should be ignored

    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"brs_says": "Some spec","bw_does": "Some impl","deltas": [],"matched_requirements": [],"confidence": 0.7}'
    )

    card = _make_intent_card()
    results = await reconcile_brs_folder(card, brs_dir, mock_llm)
    assert len(results) == 2  # only .md files


@pytest.mark.asyncio
async def test_reconcile_brs_folder_missing_dir(tmp_path):
    """Missing BRS folder returns empty list."""
    mock_llm = AsyncMock()
    card = _make_intent_card()
    results = await reconcile_brs_folder(card, tmp_path / "nonexistent", mock_llm)
    assert results == []
