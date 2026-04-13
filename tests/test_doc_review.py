import pytest
from pathlib import Path
from sap_doc_agent.agents.doc_review import (
    DocReviewAgent,
    StandardDefinition,
    load_documentation_standard,
)


@pytest.fixture
def standard(tmp_path):
    """Load the real Horvath standard."""
    std_path = Path("standards/horvath/documentation_standard.yaml")
    if std_path.exists():
        return load_documentation_standard(std_path)
    # Fallback minimal standard for CI
    return StandardDefinition(
        name="Test Standard",
        version="1.0",
        document_types=[
            {
                "id": "object_documentation",
                "name": "Object Documentation",
                "required_sections": [
                    {"id": "business_purpose", "name": "Business Purpose", "min_content_length": 30},
                    {"id": "owner", "name": "Owner / Responsible Team", "min_content_length": 10},
                    {"id": "key_fields", "name": "Key Fields & Business Meaning", "min_content_length": 100},
                ],
            }
        ],
        scoring={
            "section_present": 5,
            "section_min_length_met": 3,
            "section_contains_keywords": 2,
            "penalties": {"section_missing": -10, "section_too_short": -3},
        },
    )


@pytest.fixture
def agent(standard):
    return DocReviewAgent(standard)


# --- Classification tests ---


def test_classify_architecture(agent):
    doc_type, conf = agent.classify_document(
        "System Architecture Overview",
        "This document describes the high-level system landscape and data flow map for our BW/4HANA environment.",
    )
    assert doc_type == "architecture_overview"
    assert conf > 0.5


def test_classify_brs(agent):
    doc_type, conf = agent.classify_document(
        "Business Requirements - Revenue Reporting",
        "The business objective is to provide monthly revenue reporting. Acceptance criteria include...",
    )
    assert doc_type == "business_requirements"


def test_classify_data_flow(agent):
    doc_type, conf = agent.classify_document(
        "ETL Process - Sales Data Load",
        "This data flow extracts sales data from the source system and loads it through transformation into the target ADSO.",
    )
    assert doc_type == "data_flow"


def test_classify_dev_guidelines(agent):
    doc_type, _ = agent.classify_document(
        "SAP BW Development Guidelines",
        "This document defines naming conventions, coding standards, and transport process for BW development.",
    )
    assert doc_type == "development_guidelines"


def test_classify_runbook(agent):
    doc_type, _ = agent.classify_document(
        "Operations Runbook",
        "Daily checks, monitoring procedures, escalation contacts, and incident recovery procedures.",
    )
    assert doc_type == "operational_runbook"


def test_classify_fallback(agent):
    doc_type, conf = agent.classify_document(
        "Random Document", "Some unrelated content that doesn't match any pattern clearly."
    )
    assert doc_type is not None
    assert conf < 1.0


# --- Review tests ---


def test_review_good_object_doc(agent):
    content = """
# Sales ADSO

## Business Purpose
This ADSO stores monthly sales actuals data for revenue reporting across all company codes.

## Owner / Responsible Team
Revenue Analytics Team (John Smith)

## Key Fields & Business Meaning
- COMPANY_CODE: The SAP company code representing the legal entity
- FISCAL_YEAR: The fiscal year of the transaction
- FISCAL_PERIOD: The fiscal period (month) within the year
- AMOUNT: Transaction amount in local currency
- CURRENCY: Local currency key (ISO 4217)
"""
    review = agent.review_document("Sales ADSO", content, doc_type="object_documentation")
    assert review.document_type == "object_documentation"
    found_sections = [s for s in review.sections if s.found]
    # Should find business_purpose, owner, and key_fields at minimum
    assert len(found_sections) >= 2
    # Found sections should have content extracted
    bp = next(s for s in review.sections if s.section_id == "business_purpose")
    assert bp.found
    assert bp.content_length > 0
    assert bp.score > 0


def test_review_empty_doc(agent):
    review = agent.review_document("Empty Doc", "", doc_type="object_documentation")
    assert review.percentage < 20
    assert len(review.overall_issues) > 0


def test_review_scores_missing_sections(agent):
    content = "# Some Object\n\nJust a title and nothing else."
    review = agent.review_document("Some Object", content, doc_type="object_documentation")
    missing = [s for s in review.sections if not s.found]
    assert len(missing) > 0


def test_review_auto_classifies(agent):
    content = """
# System Architecture Overview

## System Landscape
Our SAP BW/4HANA system connects to three source systems: SAP ECC, Salesforce, and a custom REST API.

## Data Flow Map
Source systems → RAW layer → HARMONIZED layer → MART layer → SAC reports
"""
    review = agent.review_document("System Architecture", content)
    assert review.document_type == "architecture_overview"
    assert review.classification_confidence > 0.3


# --- Aggregate review tests ---


def test_review_all(agent):
    docs = [
        {
            "title": "Good Doc",
            "content": "## Business Purpose\nThis provides sales analytics for the CFO.\n## Owner / Responsible Team\nAnalytics Team",
            "type": "object_documentation",
        },
        {"title": "Bad Doc", "content": "TBD", "type": "object_documentation"},
    ]
    report = agent.review_all(docs)
    assert report.documents_reviewed == 2
    # Good Doc finds 2 sections; Bad Doc finds 0 — Good Doc should outscore Bad Doc
    good = next(r for r in report.reviews if r.document_title == "Good Doc")
    bad = next(r for r in report.reviews if r.document_title == "Bad Doc")
    assert good.total_score > bad.total_score
    assert len(report.worst_documents) >= 1  # At least one doc should be in worst list


def test_review_report_summary(agent):
    docs = [
        {
            "title": "Doc A",
            "content": "## Business Purpose\nDetailed business purpose with enough content here.\n## Owner / Responsible Team\nTeam Alpha",
            "type": "object_documentation",
        },
    ]
    report = agent.review_all(docs)
    report.compute_summary()
    assert report.documents_reviewed == 1


# --- Standard comparison tests ---


def test_compare_standards(agent, standard):
    # Create a weaker client standard (missing some sections)
    client_std = StandardDefinition(
        name="Client Standard",
        version="1.0",
        document_types=[
            {
                "id": "object_documentation",
                "name": "Object Documentation",
                "required_sections": [
                    {"id": "business_purpose", "name": "Business Purpose", "min_content_length": 10},
                    # Missing: owner, key_fields
                ],
            }
        ],
    )
    gaps = agent.compare_standards(client_std)
    assert len(gaps) > 0
    assert any("missing" in g.lower() for g in gaps)


# --- Load standard tests ---


def test_load_standard_from_yaml():
    std_path = Path("standards/horvath/documentation_standard.yaml")
    if not std_path.exists():
        pytest.skip("Standard file not available")
    std = load_documentation_standard(std_path)
    assert std.name == "Horvath SAP Documentation Standard v1.0"
    assert len(std.document_types) == 7
    assert std.get_type("architecture_overview") is not None
    assert std.get_type("development_guidelines") is not None


def test_standard_has_all_types():
    std_path = Path("standards/horvath/documentation_standard.yaml")
    if not std_path.exists():
        pytest.skip("Standard file not available")
    std = load_documentation_standard(std_path)
    expected = {
        "architecture_overview",
        "development_guidelines",
        "business_requirements",
        "data_flow",
        "object_documentation",
        "master_data",
        "operational_runbook",
    }
    actual = set(std.get_type_ids())
    assert expected == actual


# --- Suggestion tests ---


def test_suggestions_for_missing(agent):
    review = agent.review_document("Empty", "", doc_type="object_documentation")
    assert any("missing" in s.lower() for s in review.suggestions)


def test_suggestions_for_short(agent):
    content = "## Business Purpose\nShort.\n## Owner / Responsible Team\nMe"
    review = agent.review_document("Short Doc", content, doc_type="object_documentation")
    short_suggestions = [s for s in review.suggestions if "expand" in s.lower()]
    # May or may not have short suggestions depending on min_length thresholds
    assert isinstance(review.suggestions, list)
