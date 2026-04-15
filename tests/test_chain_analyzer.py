"""Tests for LLM-powered chain analysis (2-pass: step summaries + chain summary)."""

import pytest
from unittest.mock import AsyncMock

from spec2sphere.scanner.chain_analyzer import analyze_chain_steps, summarize_chain
from spec2sphere.scanner.models import ChainStep, DataFlowChain, ObjectType


def _make_chain(steps):
    """Helper to build a DataFlowChain with given steps."""
    return DataFlowChain(
        chain_id="c1",
        name="",
        terminal_object_id="T",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["S"],
        steps=steps,
        all_object_ids=["S"] + [s.object_id for s in steps] + ["T"],
    )


@pytest.mark.asyncio
async def test_analyze_chain_steps_calls_llm_per_step():
    mock_llm = AsyncMock()
    mock_llm.generate_json.return_value = {
        "summary": "Converts all amounts from source currency to EUR using daily TCURR rates.",
        "confidence": 0.9,
    }

    chain = _make_chain(
        [
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="TR_CONV",
                source_code="* currency conversion\nSELECT * FROM tcurr...",
            ),
        ]
    )

    result = await analyze_chain_steps(chain, mock_llm)
    assert result.steps[0].step_summary != ""
    assert result.steps[0].confidence == 0.9
    assert mock_llm.generate_json.call_count == 1


@pytest.mark.asyncio
async def test_summarize_chain_produces_name_and_summary():
    mock_llm = AsyncMock()
    mock_llm.generate_json.return_value = {
        "name": "Monthly Net Revenue by Customer",
        "summary": "Processes billing documents into monthly EUR revenue aggregated by customer hierarchy.",
        "observations": ["Currency conversion uses hardcoded target EUR"],
        "confidence": 0.85,
    }

    chain = _make_chain(
        [
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="TR_CONV",
                step_summary="Converts currency to EUR",
            ),
        ]
    )

    result = await summarize_chain(chain, mock_llm)
    assert result.name == "Monthly Net Revenue by Customer"
    assert result.summary != ""
    assert result.confidence == 0.85
    assert len(result.observations) == 1


@pytest.mark.asyncio
async def test_analyze_empty_source_code_skips_llm():
    mock_llm = AsyncMock()

    chain = _make_chain(
        [
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="TR_EMPTY",
                source_code="",
            ),
        ]
    )

    result = await analyze_chain_steps(chain, mock_llm)
    assert result.steps[0].step_summary == ""
    assert mock_llm.generate_json.call_count == 0
    assert mock_llm.generate.call_count == 0


@pytest.mark.asyncio
async def test_analyze_multiple_steps_with_confidence():
    mock_llm = AsyncMock()
    mock_llm.generate_json.side_effect = [
        {"summary": "Filters test orders by order type.", "confidence": 0.95},
        {"summary": "Converts currency to EUR.", "confidence": 0.88},
        {"summary": "Aggregates revenue by customer hierarchy.", "confidence": 0.75},
    ]

    chain = _make_chain(
        [
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
        ]
    )

    result = await analyze_chain_steps(chain, mock_llm)
    assert mock_llm.generate_json.call_count == 3
    assert "Filters test orders" in result.steps[0].step_summary
    assert result.steps[0].confidence == 0.95
    assert result.steps[1].confidence == 0.88
    assert result.steps[2].confidence == 0.75


@pytest.mark.asyncio
async def test_upstream_context_accumulated():
    """Each step should see summaries of all prior steps as upstream_context."""
    mock_llm = AsyncMock()
    mock_llm.generate_json.side_effect = [
        {"summary": "Filters test orders.", "confidence": 0.9},
        {"summary": "Converts currency.", "confidence": 0.85},
        {"summary": "Aggregates by hierarchy.", "confidence": 0.8},
    ]

    chain = _make_chain(
        [
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Filter",
                source_code="DELETE...",
            ),
            ChainStep(
                position=2,
                object_id="TR2",
                object_type=ObjectType.TRANSFORMATION,
                name="Convert",
                source_code="SELECT...",
            ),
            ChainStep(
                position=3,
                object_id="TR3",
                object_type=ObjectType.TRANSFORMATION,
                name="Aggregate",
                source_code="COLLECT...",
            ),
        ]
    )

    result = await analyze_chain_steps(chain, mock_llm)
    # Step 1 has no upstream
    assert result.steps[0].upstream_context == ""
    # Step 2 sees step 1
    assert "Filters test orders" in result.steps[1].upstream_context
    # Step 3 sees steps 1+2
    assert "Filters test orders" in result.steps[2].upstream_context
    assert "Converts currency" in result.steps[2].upstream_context


@pytest.mark.asyncio
async def test_downstream_context_filled():
    """Each step should see summaries of all following steps as downstream_context."""
    mock_llm = AsyncMock()
    mock_llm.generate_json.side_effect = [
        {"summary": "Filters test orders.", "confidence": 0.9},
        {"summary": "Converts currency.", "confidence": 0.85},
        {"summary": "Aggregates by hierarchy.", "confidence": 0.8},
    ]

    chain = _make_chain(
        [
            ChainStep(
                position=1,
                object_id="TR1",
                object_type=ObjectType.TRANSFORMATION,
                name="Filter",
                source_code="DELETE...",
            ),
            ChainStep(
                position=2,
                object_id="TR2",
                object_type=ObjectType.TRANSFORMATION,
                name="Convert",
                source_code="SELECT...",
            ),
            ChainStep(
                position=3,
                object_id="TR3",
                object_type=ObjectType.TRANSFORMATION,
                name="Aggregate",
                source_code="COLLECT...",
            ),
        ]
    )

    result = await analyze_chain_steps(chain, mock_llm)
    # Step 1 sees steps 2+3 downstream
    assert "Converts currency" in result.steps[0].downstream_context
    assert "Aggregates by hierarchy" in result.steps[0].downstream_context
    # Step 2 sees step 3
    assert "Aggregates by hierarchy" in result.steps[1].downstream_context
    # Step 3 has no downstream
    assert result.steps[2].downstream_context == ""


@pytest.mark.asyncio
async def test_summarize_chain_handles_none_response():
    mock_llm = AsyncMock()
    mock_llm.generate_json.return_value = None

    chain = _make_chain([])

    result = await summarize_chain(chain, mock_llm)
    assert result.name == ""
    assert result.summary == ""


@pytest.mark.asyncio
async def test_original_chain_not_mutated():
    mock_llm = AsyncMock()
    mock_llm.generate_json.return_value = {
        "summary": "Does something.",
        "confidence": 0.7,
    }

    chain = _make_chain(
        [
            ChainStep(
                position=1, object_id="TR1", object_type=ObjectType.TRANSFORMATION, name="TR", source_code="* some code"
            ),
        ]
    )

    result = await analyze_chain_steps(chain, mock_llm)
    assert chain.steps[0].step_summary == ""  # original unchanged
    assert chain.steps[0].confidence == 0.0
    assert result.steps[0].step_summary == "Does something."
    assert result.steps[0].confidence == 0.7


@pytest.mark.asyncio
async def test_generate_json_fallback_to_generate():
    """If generate_json returns None, falls back to plain generate."""
    mock_llm = AsyncMock()
    mock_llm.generate_json.return_value = None
    mock_llm.generate.return_value = "Fallback text summary."

    chain = _make_chain(
        [
            ChainStep(
                position=1, object_id="TR1", object_type=ObjectType.TRANSFORMATION, name="TR", source_code="* code here"
            ),
        ]
    )

    result = await analyze_chain_steps(chain, mock_llm)
    assert result.steps[0].step_summary == "Fallback text summary."
    assert result.steps[0].confidence == 0.0  # no confidence from fallback


@pytest.mark.asyncio
async def test_summarize_chain_sets_analyzed_at():
    mock_llm = AsyncMock()
    mock_llm.generate_json.return_value = {
        "name": "Test Chain",
        "summary": "Does stuff.",
        "observations": [],
        "confidence": 0.9,
    }

    chain = _make_chain([])
    assert chain.analyzed_at is None

    result = await summarize_chain(chain, mock_llm)
    assert result.analyzed_at is not None
