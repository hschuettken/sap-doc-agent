"""Tests for LLM-powered chain analysis (2-pass: step summaries + chain summary)."""

import pytest
from unittest.mock import AsyncMock

from sap_doc_agent.scanner.chain_analyzer import analyze_chain_steps, summarize_chain
from sap_doc_agent.scanner.models import ChainStep, DataFlowChain, ObjectType


@pytest.mark.asyncio
async def test_analyze_chain_steps_calls_llm_per_step():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "Converts all amounts from source currency to EUR using daily TCURR rates."

    chain = DataFlowChain(
        chain_id="c1",
        name="",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="TR_CONV",
                source_code="* currency conversion routine\nSELECT * FROM tcurr...",
            ),
        ],
        all_object_ids=["S", "TR1", "T"],
    )

    result = await analyze_chain_steps(chain, mock_llm)
    assert result.steps[0].step_summary != ""
    assert mock_llm.generate.call_count >= 1


@pytest.mark.asyncio
async def test_summarize_chain_produces_name_and_summary():
    mock_llm = AsyncMock()
    mock_llm.generate_json.return_value = {
        "name": "Monthly Net Revenue by Customer",
        "summary": "Processes billing documents into monthly EUR revenue aggregated by customer hierarchy.",
        "observations": ["Currency conversion uses hardcoded target EUR"],
        "confidence": 0.85,
    }

    chain = DataFlowChain(
        chain_id="c1",
        name="",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="TR_CONV",
                step_summary="Converts currency to EUR",
            ),
        ],
        all_object_ids=["S", "TR1", "T"],
    )

    result = await summarize_chain(chain, mock_llm)
    assert result.name == "Monthly Net Revenue by Customer"
    assert result.summary != ""
    assert result.confidence == 0.85
    assert len(result.observations) == 1


@pytest.mark.asyncio
async def test_analyze_empty_source_code_skips_llm():
    mock_llm = AsyncMock()

    chain = DataFlowChain(
        chain_id="c1",
        name="",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="TR_EMPTY",
                source_code="",
            ),
        ],
        all_object_ids=["S", "TR1", "T"],
    )

    result = await analyze_chain_steps(chain, mock_llm)
    assert result.steps[0].step_summary == ""
    assert mock_llm.generate.call_count == 0


@pytest.mark.asyncio
async def test_analyze_multiple_steps():
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = [
        "Filters test orders by order type.",
        "Converts currency to EUR.",
        "Aggregates revenue by customer hierarchy.",
    ]

    chain = DataFlowChain(
        chain_id="c1",
        name="",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
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
                source_code="SELECT * FROM tcurr...",
            ),
            ChainStep(
                position=3,
                object_id="TR3",
                object_type=ObjectType.TRANSFORMATION,
                name="Aggregate",
                source_code="COLLECT wa INTO lt_result.",
            ),
        ],
        all_object_ids=["S", "TR1", "TR2", "TR3", "T"],
    )

    result = await analyze_chain_steps(chain, mock_llm)
    assert mock_llm.generate.call_count == 3
    assert "Filters test orders" in result.steps[0].step_summary
    assert "Converts currency" in result.steps[1].step_summary
    assert "Aggregates revenue" in result.steps[2].step_summary


@pytest.mark.asyncio
async def test_summarize_chain_handles_none_response():
    mock_llm = AsyncMock()
    mock_llm.generate_json.return_value = None

    chain = DataFlowChain(
        chain_id="c1",
        name="",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=[],
        all_object_ids=["S", "T"],
    )

    result = await summarize_chain(chain, mock_llm)
    assert result.name == ""
    assert result.summary == ""


@pytest.mark.asyncio
async def test_original_chain_not_mutated():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "Does something."

    chain = DataFlowChain(
        chain_id="c1",
        name="",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=[
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="TR",
                source_code="* some code",
            ),
        ],
        all_object_ids=["S", "TR1", "T"],
    )

    result = await analyze_chain_steps(chain, mock_llm)
    assert chain.steps[0].step_summary == ""  # original unchanged
    assert result.steps[0].step_summary == "Does something."
