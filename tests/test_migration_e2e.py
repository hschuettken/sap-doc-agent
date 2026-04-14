"""End-to-end integration test for the full migration pipeline.

Runs: graph → build chains → interpret (mocked LLM) → classify →
      design (heuristic) → generate SQL → estimate effort → generate report.
Uses the sample_bw_scan fixture with 3 chains.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sap_doc_agent.migration.architect import design_chain_views
from sap_doc_agent.migration.classifier import classify_chain
from sap_doc_agent.migration.diagram import generate_chain_diagram
from sap_doc_agent.migration.effort import estimate_project_effort
from sap_doc_agent.migration.generator import generate_sql_for_view
from sap_doc_agent.migration.interpreter import interpret_chain
from sap_doc_agent.migration.models import ClassifiedChain, MigrationClassification
from sap_doc_agent.migration.report import ReportData, generate_report_html
from sap_doc_agent.scanner.chain_builder import build_chains_from_graph
from sap_doc_agent.scanner.models import DataFlowChain

_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_bw_scan"


def _mock_llm() -> AsyncMock:
    """Create a mock LLM that returns deterministic responses."""
    llm = AsyncMock()

    # For interpreter: return a valid IntentCard JSON
    llm.generate_json = AsyncMock(
        return_value={
            "business_purpose": "Monthly revenue reporting by customer and material",
            "data_domain": "Sales",
            "source_systems": ["2LIS_11_VAITM"],
            "key_entities": ["KUNNR", "MATNR"],
            "key_measures": ["NETWR_EUR"],
            "grain": "Customer × Material × Month",
            "consumers": ["ZC_REVENUE"],
            "transformations": [
                {
                    "step_number": 1,
                    "intent": "Load raw billing data",
                    "implementation": "Direct load from DataSource",
                    "is_business_logic": False,
                },
                {
                    "step_number": 2,
                    "intent": "Convert currency to EUR",
                    "implementation": "TCURR lookup",
                    "is_business_logic": True,
                },
            ],
            "confidence": 0.85,
            "needs_human_review": False,
        }
    )

    # For classifier LLM fallback: return a valid classification JSON
    llm.generate = AsyncMock(return_value="SELECT 1 FROM source_table")

    return llm


@pytest.fixture
def graph():
    return json.loads((_FIXTURE_DIR / "graph.json").read_text())


@pytest.fixture
def chains(graph):
    return build_chains_from_graph(graph, objects_dir=_FIXTURE_DIR / "objects")


def test_chain_builder_finds_three_chains(chains):
    """The fixture graph should produce 3 chains."""
    assert len(chains) == 3


def test_chain_ids_are_unique(chains):
    ids = [c.chain_id for c in chains]
    assert len(ids) == len(set(ids))


@pytest.mark.asyncio
async def test_full_pipeline(chains):
    """Full pipeline: interpret → classify → design → generate → report."""
    llm = _mock_llm()

    # --- Phase 2: Interpret all chains ---
    intent_cards = {}
    for chain in chains:
        intent = await interpret_chain(chain, llm)
        assert intent.chain_id == chain.chain_id
        assert intent.business_purpose != ""
        intent_cards[chain.chain_id] = intent

    # --- Phase 3: Classify all chains ---
    classified_chains: list[tuple[ClassifiedChain, DataFlowChain]] = []
    for chain in chains:
        intent = intent_cards[chain.chain_id]

        # Build activity data from chain metadata
        from sap_doc_agent.migration.classifier import ActivityData

        activity = None
        for step in chain.steps:
            meta = step.model_dump().get("metadata") or {}
            last_run = meta.get("last_run")
            if last_run:
                activity = ActivityData(last_execution=last_run)
                break

        classified = await classify_chain(intent, chain, llm, activity)
        assert classified.chain_id == chain.chain_id
        assert classified.classification in MigrationClassification
        classified_chains.append((classified, chain))

    # Verify classification distribution
    classifications = {c.classification for c, _ in classified_chains}
    # At minimum we should have more than one classification type
    assert len(classified_chains) == 3

    # --- Phase 4: Design target views for MIGRATE/SIMPLIFY chains ---
    all_views = []
    for classified, chain in classified_chains:
        if classified.classification in (MigrationClassification.DROP, MigrationClassification.CLARIFY):
            continue
        views = await design_chain_views(classified, chain, llm)
        assert len(views) >= 1
        all_views.extend(views)

    # Should have at least some target views
    assert len(all_views) >= 1

    # --- Phase 5: Generate SQL for each view ---
    sql_results = []
    for view in all_views:
        result = await generate_sql_for_view(view, llm)
        assert result.sql != ""
        assert result.technical_name == view.technical_name
        sql_results.append(result)

    assert len(sql_results) == len(all_views)

    # --- Phase D1: Effort estimation ---
    efforts = estimate_project_effort(classified_chains)
    assert len(efforts) == 3
    # Each effort should have a category
    for e in efforts:
        assert e.category is not None
        assert e.rationale != ""

    # --- Phase D2: Diagrams ---
    diagrams = {}
    views_by_chain: dict[str, list] = {}
    for v in all_views:
        for sc in v.source_chains:
            views_by_chain.setdefault(sc, []).append(v)

    for classified, chain in classified_chains:
        chain_views = views_by_chain.get(classified.chain_id, [])
        mermaid = generate_chain_diagram(classified, chain, chain_views)
        assert "graph LR" in mermaid
        diagrams[classified.chain_id] = mermaid

    assert len(diagrams) == 3

    # --- Phase D3: Report ---
    from sap_doc_agent.migration.models import TargetArchitecture

    architecture = TargetArchitecture(project_name="E2E Test", views=all_views)
    generated_sql = {r.technical_name: r.sql for r in sql_results}

    report_data = ReportData(
        project_name="E2E Integration Test Project",
        chains=classified_chains,
        architecture=architecture,
        efforts=efforts,
        diagrams=diagrams,
        generated_sql=generated_sql,
    )

    html = generate_report_html(report_data)

    # Validate report structure
    assert "<!DOCTYPE html>" in html
    assert "Executive Summary" in html
    assert "Chain Inventory" in html
    assert "Technical Debt" in html
    assert "Target Architecture" in html
    assert "Effort" in html
    assert "mermaid" in html
    assert "View Specifications" in html or "Appendix" in html
    # Should contain actual chain data
    for classified, _ in classified_chains:
        assert classified.chain_id in html
    # Should contain target view names
    for view in all_views:
        assert view.technical_name in html
    # Should contain generated SQL
    for name, sql in generated_sql.items():
        assert name in html

    # Report should be self-contained HTML
    assert "</html>" in html
