"""Tests for the DSP Code Generator (view specs → DSP SQL)."""

import pytest
from unittest.mock import AsyncMock

from sap_doc_agent.migration.generator import (
    generate_sql_for_view,
    generate_sql_for_architecture,
    GeneratedSQL,
)
from sap_doc_agent.migration.models import (
    ColumnSpec,
    TargetArchitecture,
    ViewSpec,
)


def _make_simple_view():
    return ViewSpec(
        technical_name="02_RV_BILLING_CLEAN",
        space="SAP_ADMIN",
        layer="harmonization",
        semantic_usage="relational_dataset",
        description="Filter test orders and map fields",
        source_chains=["c1"],
        source_objects=["01_LT_BILLING"],
        columns=[
            ColumnSpec(name="KUNNR", data_type="VARCHAR(10)", source_field="KUNNR"),
            ColumnSpec(name="MATNR", data_type="VARCHAR(18)", source_field="MATNR"),
            ColumnSpec(name="NETWR", data_type="DECIMAL(15,2)", source_field="NETWR", is_measure=True),
            ColumnSpec(name="BUKRS", data_type="VARCHAR(4)", source_field="BUKRS"),
        ],
        sql_logic="SELECT KUNNR, MATNR, NETWR, BUKRS FROM 01_LT_BILLING WHERE AUART <> 'ZT'",
        collapse_rationale="Collapses BW steps 1-2 (filter + field mapping)",
        collapsed_bw_steps=["TR1", "TR2"],
    )


def _make_complex_view():
    return ViewSpec(
        technical_name="03_FV_REVENUE_MONTHLY",
        space="SAP_ADMIN",
        layer="mart",
        semantic_usage="fact",
        description="Monthly revenue aggregated by customer and material",
        source_chains=["c1"],
        source_objects=["02_RV_BILLING_CLEAN"],
        columns=[
            ColumnSpec(name="KUNNR", data_type="VARCHAR(10)", is_key=True),
            ColumnSpec(name="MATNR", data_type="VARCHAR(18)", is_key=True),
            ColumnSpec(name="CALMONTH", data_type="VARCHAR(6)", is_key=True),
            ColumnSpec(name="NETWR_EUR", data_type="DECIMAL(15,2)", is_measure=True, aggregation="SUM"),
        ],
        sql_logic="SELECT KUNNR, MATNR, LEFT(BUDAT, 6) AS CALMONTH, SUM(NETWR) AS NETWR_EUR FROM source GROUP BY ...",
        persistence=True,
        persistence_rationale="Large aggregation, multiple consumers",
    )


# --- Template-based generation (simple views) ---


@pytest.mark.asyncio
async def test_generate_simple_view_produces_sql():
    mock_llm = AsyncMock()
    # LLM should NOT be called for simple views
    view = _make_simple_view()
    result = await generate_sql_for_view(view, mock_llm)

    assert isinstance(result, GeneratedSQL)
    assert result.technical_name == "02_RV_BILLING_CLEAN"
    assert result.sql != ""
    assert "SELECT" in result.sql.upper()


@pytest.mark.asyncio
async def test_generated_sql_has_traceability_comments():
    mock_llm = AsyncMock()
    view = _make_simple_view()
    result = await generate_sql_for_view(view, mock_llm)

    # Must include source traceability
    assert "Source:" in result.sql or "source:" in result.sql.lower()
    assert "TR1" in result.sql or "c1" in result.sql


@pytest.mark.asyncio
async def test_generated_sql_passes_validation():
    mock_llm = AsyncMock()
    view = _make_simple_view()
    result = await generate_sql_for_view(view, mock_llm)

    assert result.validation_result is not None
    # Template-generated SQL should be valid
    assert result.validation_result.error_count == 0


# --- LLM-based generation (complex views) ---


@pytest.mark.asyncio
async def test_generate_complex_view_uses_llm():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = (
        "-- Source: BW chain c1 (revenue aggregation)\n"
        "SELECT\n"
        '  "KUNNR",\n'
        '  "MATNR",\n'
        '  LEFT("BUDAT", 6) AS "CALMONTH",\n'
        '  SUM("NETWR") AS "NETWR_EUR"\n'
        'FROM "02_RV_BILLING_CLEAN"\n'
        'GROUP BY "KUNNR", "MATNR", LEFT("BUDAT", 6)'
    )

    view = _make_complex_view()
    result = await generate_sql_for_view(view, mock_llm)
    assert result.sql != ""
    assert mock_llm.generate.call_count >= 1


@pytest.mark.asyncio
async def test_generate_complex_view_prompt_includes_sql_rules():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "SELECT 1"

    view = _make_complex_view()
    await generate_sql_for_view(view, mock_llm)
    call_args = mock_llm.generate.call_args
    prompt = call_args[0][0] if call_args[0] else call_args[1].get("prompt", "")
    # Should contain DSP SQL rules
    assert "CTE" in prompt or "cte" in prompt.lower()
    assert "UNION" in prompt or "union" in prompt.lower()


@pytest.mark.asyncio
async def test_generate_llm_failure_returns_fallback():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = None

    view = _make_complex_view()
    result = await generate_sql_for_view(view, mock_llm)
    # Should still produce something (the sql_logic from the spec)
    assert result.sql != ""
    assert result.needs_manual_edit is True


# --- Full architecture generation ---


@pytest.mark.asyncio
async def test_generate_sql_for_architecture():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "SELECT 1 -- generated"

    arch = TargetArchitecture(
        project_name="Test",
        views=[_make_simple_view(), _make_complex_view()],
    )
    results = await generate_sql_for_architecture(arch, mock_llm)
    assert len(results) == 2
    assert all(isinstance(r, GeneratedSQL) for r in results)


# --- Validation integration ---


@pytest.mark.asyncio
async def test_generated_sql_validated_against_rules():
    mock_llm = AsyncMock()
    # Return SQL with a CTE violation
    mock_llm.generate.return_value = "WITH cte AS (SELECT 1) SELECT * FROM cte"

    view = _make_complex_view()
    result = await generate_sql_for_view(view, mock_llm)
    assert result.validation_result is not None
    assert result.validation_result.error_count > 0


@pytest.mark.asyncio
async def test_generated_result_fields():
    mock_llm = AsyncMock()
    view = _make_simple_view()
    result = await generate_sql_for_view(view, mock_llm)

    assert result.technical_name == view.technical_name
    assert result.space == view.space
    assert result.layer == view.layer
    assert isinstance(result.needs_manual_edit, bool)
