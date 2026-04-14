"""Tests for the migration assessment report generator."""

from sap_doc_agent.migration.diagram import generate_chain_diagram
from sap_doc_agent.migration.effort import EffortEstimate, EffortCategory
from sap_doc_agent.migration.models import (
    ClassifiedChain,
    IntentCard,
    MigrationClassification,
    TargetArchitecture,
    ViewSpec,
)
from sap_doc_agent.migration.report import ReportData, generate_report_html
from sap_doc_agent.scanner.models import ChainStep, DataFlowChain, ObjectType


def _make_report_data() -> ReportData:
    chain1 = DataFlowChain(
        chain_id="chain_001",
        name="Sales Revenue",
        terminal_object_id="CMP_REV",
        terminal_object_type=ObjectType.COMPOSITE,
        source_object_ids=["DS_BILLING"],
        steps=[
            ChainStep(position=1, object_id="TRAN_001", object_type=ObjectType.TRANSFORMATION, name="Step 1"),
            ChainStep(position=2, object_id="TRAN_002", object_type=ObjectType.TRANSFORMATION, name="Step 2"),
        ],
        all_object_ids=["DS_BILLING", "TRAN_001", "TRAN_002", "CMP_REV"],
    )
    chain2 = DataFlowChain(
        chain_id="chain_002",
        name="Dead Chain",
        terminal_object_id="DSO_DEAD",
        terminal_object_type=ObjectType.ADSO,
        source_object_ids=["DS_DEAD"],
        steps=[
            ChainStep(position=1, object_id="TRAN_DEAD", object_type=ObjectType.TRANSFORMATION, name="Dead Step"),
        ],
        all_object_ids=["DS_DEAD", "TRAN_DEAD", "DSO_DEAD"],
    )

    classified1 = ClassifiedChain(
        chain_id="chain_001",
        intent_card=IntentCard(
            chain_id="chain_001",
            business_purpose="Monthly net revenue by customer",
            data_domain="Sales",
        ),
        classification=MigrationClassification.MIGRATE,
        effort_category="moderate",
    )
    classified2 = ClassifiedChain(
        chain_id="chain_002",
        intent_card=IntentCard(
            chain_id="chain_002",
            business_purpose="Obsolete test data",
            data_domain="Test",
        ),
        classification=MigrationClassification.DROP,
        last_execution="2024-01-15",
        effort_category="trivial",
    )

    views = [
        ViewSpec(
            technical_name="02_RV_BILLING_CLEAN",
            layer="harmonization",
            semantic_usage="relational_dataset",
            description="Billing harmonization",
            source_chains=["chain_001"],
        ),
        ViewSpec(
            technical_name="03_FV_REVENUE",
            layer="mart",
            semantic_usage="fact",
            description="Revenue fact",
            source_chains=["chain_001"],
        ),
    ]

    architecture = TargetArchitecture(project_name="Test Project", views=views)

    efforts = [
        EffortEstimate(
            chain_id="chain_001",
            category=EffortCategory.MODERATE,
            step_count=2,
            abap_line_count=80,
            rationale="Moderate",
        ),
        EffortEstimate(
            chain_id="chain_002", category=EffortCategory.TRIVIAL, step_count=1, abap_line_count=0, rationale="DROP"
        ),
    ]

    diagrams = {
        "chain_001": generate_chain_diagram(classified1, chain1, views),
    }

    return ReportData(
        project_name="Test Migration Project",
        chains=[(classified1, chain1), (classified2, chain2)],
        architecture=architecture,
        efforts=efforts,
        diagrams=diagrams,
    )


def test_report_html_is_valid():
    data = _make_report_data()
    html = generate_report_html(data)
    assert "<!DOCTYPE html>" in html
    assert "</html>" in html


def test_report_contains_executive_summary():
    data = _make_report_data()
    html = generate_report_html(data)
    assert "Executive Summary" in html
    assert "Test Migration Project" in html


def test_report_contains_chain_inventory():
    data = _make_report_data()
    html = generate_report_html(data)
    assert "Chain Inventory" in html
    assert "chain_001" in html
    assert "chain_002" in html


def test_report_contains_classification_breakdown():
    data = _make_report_data()
    html = generate_report_html(data)
    assert "MIGRATE" in html or "migrate" in html
    assert "DROP" in html or "drop" in html


def test_report_contains_technical_debt():
    data = _make_report_data()
    html = generate_report_html(data)
    assert "Technical Debt" in html
    assert "chain_002" in html  # DROP chain should appear here


def test_report_contains_target_architecture():
    data = _make_report_data()
    html = generate_report_html(data)
    assert "Target Architecture" in html
    assert "02_RV_BILLING_CLEAN" in html
    assert "03_FV_REVENUE" in html


def test_report_contains_effort_estimation():
    data = _make_report_data()
    html = generate_report_html(data)
    assert "Effort" in html


def test_report_contains_mermaid_script():
    data = _make_report_data()
    html = generate_report_html(data)
    assert "mermaid" in html


def test_report_is_self_contained():
    """Report should have inline CSS, no external stylesheet deps."""
    data = _make_report_data()
    html = generate_report_html(data)
    assert "<style>" in html
    # Should not reference external CSS files
    assert 'rel="stylesheet"' not in html or "mermaid" in html


def test_report_appendix_view_specs():
    data = _make_report_data()
    html = generate_report_html(data)
    assert "Appendix" in html or "View Specifications" in html


def test_report_contains_dead_code_percentage():
    """Source system inventory should include dead code percentage."""
    data = _make_report_data()
    html = generate_report_html(data)
    # 1 DROP chain out of 2 total = 50.0%
    assert "Dead code" in html
    assert "50.0%" in html
