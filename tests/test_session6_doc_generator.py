"""Tests for Session 6: as-built documentation generator.

Covers all public functions in spec2sphere.governance.doc_generator.
"""

from __future__ import annotations

import pytest

from spec2sphere.governance.doc_generator import (
    generate_decision_log,
    generate_functional_doc,
    generate_reconciliation_report,
    generate_technical_doc,
    generate_traceability_matrix,
    render_html_report,
    render_markdown_report,
)


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_project_data() -> dict:
    """Minimal but representative Spec2Sphere pipeline context for tests."""
    return {
        "project": {
            "id": "proj-001",
            "name": "Lindt Revenue Analytics",
            "slug": "lindt-revenue",
        },
        "customer": {
            "name": "Lindt & Sprüngli AG",
        },
        "requirements": [
            {
                "id": "req-001",
                "title": "Revenue KPI Dashboard",
                "business_domain": "Finance",
                "status": "approved",
                "parsed_entities": {
                    "measures": ["Net Revenue", "Gross Revenue"],
                    "dimensions": ["Time", "Region"],
                },
                "parsed_kpis": [
                    {"name": "Net Revenue", "formula": "Gross Revenue - Deductions"},
                    {"name": "Revenue Growth", "formula": "(Current - Prior) / Prior * 100"},
                ],
            }
        ],
        "hla_documents": [
            {
                "id": "hla-001",
                "narrative": "Revenue data flows from S/4HANA via SDI into DSP harmonization layer.",
                "content": {
                    "layers": ["staging", "harmonization", "mart"],
                    "decisions": ["Use DSP for all transforms"],
                },
                "status": "approved",
            }
        ],
        "tech_specs": [
            {
                "id": "spec-001",
                "objects": [
                    {
                        "name": "V_RAW_REVENUE",
                        "object_type": "view",
                        "platform": "DSP",
                        "layer": "staging",
                        "status": "approved",
                        "generated_artifact": "SELECT * FROM REVENUE_HEADER",
                    },
                    {
                        "name": "V_NET_REVENUE",
                        "object_type": "view",
                        "platform": "DSP",
                        "layer": "mart",
                        "status": "approved",
                        "generated_artifact": "SELECT SUM(NET_AMT) AS NET_REVENUE FROM V_RAW_REVENUE",
                    },
                ],
                "deployment_order": ["V_RAW_REVENUE", "V_NET_REVENUE"],
                "status": "approved",
            }
        ],
        "architecture_decisions": [
            {
                "topic": "Platform Placement",
                "choice": "DSP for all data transforms",
                "rationale": "Centralised governance and lineage tracking required by customer.",
                "alternatives": ["BW/4HANA", "Databricks"],
                "platform_placement": "DSP",
            }
        ],
        "reconciliation_results": [
            {
                "test_case_key": "TC_NET_REVENUE_TOTAL",
                "delta_status": "pass",
                "baseline_value": {"NET_REVENUE": 1000000.0},
                "candidate_value": {"NET_REVENUE": 1000000.0},
            }
        ],
        "technical_objects": [
            {
                "name": "V_RAW_REVENUE",
                "object_type": "view",
                "platform": "DSP",
                "layer": "staging",
                "status": "approved",
                "generated_artifact": "SELECT * FROM REVENUE_HEADER",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_generate_technical_doc(sample_project_data):
    result = generate_technical_doc(sample_project_data)

    assert result["title"].startswith("Technical Documentation")
    assert "V_RAW_REVENUE" in result["content"]
    assert isinstance(result["deployment_order"], list)
    assert len(result["deployment_order"]) > 0
    assert result["object_count"] >= 1


def test_generate_functional_doc(sample_project_data):
    result = generate_functional_doc(sample_project_data)

    assert result["title"].startswith("Functional Documentation")
    assert "Net Revenue" in result["content"]
    assert "Finance" in result["content"]


def test_generate_traceability_matrix(sample_project_data):
    result = generate_traceability_matrix(sample_project_data)

    assert "rows" in result
    assert len(result["rows"]) >= 1

    row = result["rows"][0]
    assert "requirement" in row
    assert "tech_objects" in row
    assert isinstance(row["tech_objects"], list)
    assert "result" in row
    assert "result_class" in row


def test_generate_decision_log(sample_project_data):
    log = generate_decision_log(sample_project_data)

    assert isinstance(log, list)
    assert len(log) == 1

    entry = log[0]
    assert "topic" in entry
    assert "choice" in entry
    assert entry["topic"] == "Platform Placement"
    assert entry["choice"] == "DSP for all data transforms"


def test_generate_reconciliation_report(sample_project_data):
    result = generate_reconciliation_report(sample_project_data)

    assert result["total_tests"] == 1
    assert result["passed"] == 1
    assert result["failed"] == 0
    assert result["tolerance"] == 0


def test_render_html_report(sample_project_data):
    html = render_html_report(sample_project_data)

    assert "<!DOCTYPE html>" in html
    assert "Lindt Revenue Analytics" in html
    assert "V_RAW_REVENUE" in html


def test_render_markdown_report(sample_project_data):
    md = render_markdown_report(sample_project_data)

    assert md.startswith("# ")
    assert "## Traceability Matrix" in md
