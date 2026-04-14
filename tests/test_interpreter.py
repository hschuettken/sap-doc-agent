"""Tests for the Semantic Interpreter (chain → IntentCard)."""

import pytest
from unittest.mock import AsyncMock

from sap_doc_agent.migration.interpreter import interpret_chain
from sap_doc_agent.migration.models import IntentCard
from sap_doc_agent.scanner.models import ChainStep, DataFlowChain, ObjectType


def _make_chain(steps=None, summary=""):
    return DataFlowChain(
        chain_id="chain_001",
        name="Revenue Chain",
        terminal_object_id="CMP_REV",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["DS_BILLING"],
        steps=steps or [],
        all_object_ids=["DS_BILLING", "CMP_REV"],
        summary=summary,
    )


@pytest.mark.asyncio
async def test_interpret_chain_returns_intent_card():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = None
    mock_llm.generate_json = None  # force generate_json_with_retry to use generate
    # Simulate generate_json_with_retry returning structured data
    # We mock at the provider level
    mock_llm.generate.return_value = '{"business_purpose": "Monthly revenue", "data_domain": "SD", "confidence": 0.85}'

    # Actually, generate_json_with_retry calls provider.generate() then parses.
    # Let's set up the mock properly.
    mock_llm.generate.return_value = (
        '{"business_purpose": "Monthly revenue by customer in EUR",'
        '"data_domain": "Sales & Distribution",'
        '"source_systems": ["ECC SD"],'
        '"key_entities": ["Customer", "Material"],'
        '"key_measures": ["Net Revenue (EUR)"],'
        '"grain": "Customer × Material × Month",'
        '"consumers": ["BEx Query ZQ_REV"],'
        '"transformations": [{"step_number": 1, "intent": "Filter test orders",'
        '"implementation": "DELETE SOURCE_PACKAGE", "is_business_logic": true}],'
        '"confidence": 0.85,'
        '"review_notes": ["Verify customer hierarchy"]}'
    )

    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Filter",
                source_code="DELETE SOURCE_PACKAGE WHERE auart = 'ZT'.",
                step_summary="Filters test orders",
            ),
        ]
    )

    result = await interpret_chain(chain, mock_llm)
    assert isinstance(result, IntentCard)
    assert result.chain_id == "chain_001"
    assert "revenue" in result.business_purpose.lower()
    assert result.data_domain == "Sales & Distribution"
    assert result.confidence == 0.85
    assert result.needs_human_review is False


@pytest.mark.asyncio
async def test_interpret_chain_low_confidence_flags_review():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"business_purpose": "Unclear purpose",'
        '"data_domain": "Unknown",'
        '"confidence": 0.4,'
        '"review_notes": ["Cannot determine business intent"]}'
    )

    chain = _make_chain()
    result = await interpret_chain(chain, mock_llm)
    assert result.needs_human_review is True
    assert result.confidence == 0.4


@pytest.mark.asyncio
async def test_interpret_chain_with_transformations():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"business_purpose": "Revenue reporting",'
        '"data_domain": "SD",'
        '"transformations": ['
        '  {"step_number": 1, "intent": "Filter test orders",'
        '   "implementation": "Start routine DELETE", "is_business_logic": true},'
        '  {"step_number": 2, "intent": "Convert to EUR",'
        '   "implementation": "TCURR lookup", "is_business_logic": true,'
        '   "simplification_note": "Use CASE WHEN in DSP"}'
        "],"
        '"confidence": 0.9}'
    )

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
                name="Convert",
                source_code="SELECT * FROM tcurr INTO TABLE lt_tcurr.",
            ),
        ]
    )

    result = await interpret_chain(chain, mock_llm)
    assert len(result.transformations) == 2
    assert result.transformations[1].simplification_note == "Use CASE WHEN in DSP"


@pytest.mark.asyncio
async def test_interpret_chain_detects_bw_patterns():
    """Pattern detection from ABAP source should feed into prompt."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = '{"business_purpose": "Revenue","data_domain": "SD","confidence": 0.8}'

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

    result = await interpret_chain(chain, mock_llm)
    # The LLM was called — verify pattern detection ran
    assert mock_llm.generate.call_count >= 1
    # Check the prompt included patterns
    call_args = mock_llm.generate.call_args
    prompt = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "tcurr_conversion" in prompt


@pytest.mark.asyncio
async def test_interpret_chain_fallback_on_none():
    """If LLM returns None for JSON, try plain generate."""
    mock_llm = AsyncMock()
    # generate_json_with_retry calls generate multiple times; all return None
    mock_llm.generate.side_effect = [None, None, None, "Fallback: revenue chain for monthly reporting"]

    chain = _make_chain()
    result = await interpret_chain(chain, mock_llm)
    assert result.chain_id == "chain_001"
    assert result.confidence == 0.0
    assert result.needs_human_review is True


@pytest.mark.asyncio
async def test_interpret_chain_empty_steps():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"business_purpose": "Data passthrough","data_domain": "General","confidence": 0.6}'
    )

    chain = _make_chain(steps=[])
    result = await interpret_chain(chain, mock_llm)
    assert result.business_purpose == "Data passthrough"
    assert result.transformations == []


@pytest.mark.asyncio
async def test_interpret_chain_json_round_trip():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        '{"business_purpose": "Test","data_domain": "SD","key_entities": ["Customer"],"confidence": 0.9}'
    )

    chain = _make_chain()
    result = await interpret_chain(chain, mock_llm)
    json_str = result.model_dump_json()
    restored = IntentCard.model_validate_json(json_str)
    assert restored.business_purpose == result.business_purpose


@pytest.mark.asyncio
async def test_interpret_chain_truncates_large_source():
    """Large ABAP source code should be truncated to fit context window."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = '{"business_purpose": "Revenue","data_domain": "SD","confidence": 0.8}'

    # Create a step with very large source code (~5000 lines)
    large_code = "\n".join(f"DATA: lv_var{i} TYPE i. lv_var{i} = {i}." for i in range(5000))
    chain = _make_chain(
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="BigRoutine",
                source_code=large_code,
            ),
        ]
    )

    result = await interpret_chain(chain, mock_llm)
    assert result.chain_id == "chain_001"
    # The prompt should have been sent — verify LLM was called
    assert mock_llm.generate.call_count >= 1
    # The prompt should NOT contain the full 5000-line source
    call_args = mock_llm.generate.call_args
    prompt = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    assert "truncated" in prompt or len(prompt) < len(large_code)
