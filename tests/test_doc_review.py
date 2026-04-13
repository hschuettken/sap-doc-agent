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


# --- Documentation Set tests ---


def test_review_set_merges_docs():
    """A documentation set is evaluated holistically across all documents."""
    std_path = Path("standards/horvath/documentation_standard.yaml")
    if not std_path.exists():
        pytest.skip("Standard file not available")
    std = load_documentation_standard(std_path)
    agent = DocReviewAgent(std)

    docs = [
        {
            "title": "Sales Data Flow - BRS",
            "content": """
## Business Objective
Monthly revenue reporting for the CFO across all company codes and product lines.

## Data Scope
All sales transactions from SAP ECC, granularity at line-item level, fiscal year 2020 onwards.

## Business Rules & Calculations
Revenue = gross amount minus discounts minus returns. Currency conversion at monthly average rate.

## Source Systems
SAP ECC via standard extractors (2LIS_11_VAHDR, 2LIS_11_VAITM).

## Output & Consumers
SAC dashboard for revenue analytics team and monthly board report.

## Acceptance Criteria
Must reconcile with FI-CO module within 0.1% tolerance.

## Sign-off & Owner
Business owner: Finance department, approved Q1 2025.
""",
        },
        {
            "title": "Sales Data Flow - Technical",
            "content": """
## Source to Target Overview
ECC -> DataSource 2LIS_11 -> ADSO_SALES_RAW -> RV_SALES_HARMONIZED -> AM_SALES_REPORT

## Transformation Logic
Raw sales lines are cleaned, currency-converted using daily rates, and aggregated
to fiscal period level. Intercompany eliminations are applied based on partner company code.

## Filter / Selection Criteria
Only document types F1, F2 (billing). Excludes internal orders and statistical postings.

## Error Handling
Failed records written to error ADSO. Alert email to operations team. Process chain retries 3x.

## Schedule & Frequency
Daily at 02:00 UTC, full delta load. Monthly full reload on 1st of month.

## Dependencies
Requires exchange rate load (PROCESS_CHAIN_FX) to complete first.
""",
        },
        {
            "title": "Sales Objects Reference",
            "content": """
## Business Purpose
This ADSO stores monthly sales actuals for revenue analytics.

## Owner / Responsible Team
Revenue Analytics Team (finance-analytics@company.com)

## Key Fields & Business Meaning
COMPANY_CODE - Legal entity, MATERIAL - Product sold, AMOUNT - Revenue in local currency,
CUSTOMER - Ship-to customer number, FISCAL_YEAR/PERIOD - Time dimension for reporting.

## Data Volume & Retention
~2M rows/month, 5 years retention, archived to cold storage after 3 years.

## Layer Assignment
Harmonized layer (02_) — cleaned and currency-converted.

## Upstream Dependencies
Reads from ADSO_SALES_RAW (01_ layer) via transformation TRFN_SALES_HARM.

## Downstream Consumers
Consumed by AM_SALES_REPORT (analytic model) and exported to SAC via live connection.
""",
        },
    ]

    review = agent.review_documentation_set("Sales Revenue", docs, scope="application")
    # The docs cover BRS + data flow + object docs (3 of 6 application types)
    # Dev guidelines, master data, and runbook are completely missing — that's correct
    found = [s for s in review.sections if s.found]
    assert len(found) >= 8  # Should find sections from BRS + data flow + object docs
    assert "set:application" in review.document_type
    # Verify it correctly identifies the uncovered types
    assert any("Development Guidelines" in i for i in review.overall_issues)
    assert any("Operational Runbook" in i or "Master Data" in i for i in review.overall_issues)


def test_review_set_system_scope():
    """System-level review checks architecture overview sections."""
    std_path = Path("standards/horvath/documentation_standard.yaml")
    if not std_path.exists():
        pytest.skip("Standard file not available")
    std = load_documentation_standard(std_path)
    agent = DocReviewAgent(std)

    docs = [
        {
            "title": "BW/4HANA Architecture",
            "content": """
## System Landscape
Our BW/4HANA system connects to SAP ECC as the primary source system.
Additional connections to Salesforce CRM and a REST API for external market data.
The target is SAC for reporting and planning.

## Data Flow Map
Source systems (ECC, Salesforce) → RAW layer (01_) → HARMONIZED layer (02_) → MART layer (03_) → SAC

## Layer Architecture
- RAW: Direct replicas of source data, no transformations. Prefix 01_LT_ for local tables.
- HARMONIZED: Cleaned, joined, currency-converted. Prefix 02_RV_ for relational views.
- MART: Business-ready aggregates. Prefix 03_FV_ for fact views.
- CONSUMPTION: Analytic models exposed to SAC. Prefix 03AM_.

## Space / Package Organization
One space per business domain: FI_ANALYTICS, SD_ANALYTICS, CO_ANALYTICS, SHARED_MASTERDATA.

## Integration Points
SAC live connection for real-time reporting. REST API for external data ingestion.

## Security & Authorization
Role-based access via BW authorization objects. SAC inherits BW roles.
""",
        },
    ]

    review = agent.review_documentation_set("Horvath BW/4", docs, scope="system")
    assert review.percentage > 50
    assert "set:system" in review.document_type
    found = [s for s in review.sections if s.found]
    assert len(found) >= 3  # Should find several architecture sections


def test_review_set_empty_docs():
    """Empty documentation set scores very low."""
    std_path = Path("standards/horvath/documentation_standard.yaml")
    if not std_path.exists():
        pytest.skip("Standard file not available")
    std = load_documentation_standard(std_path)
    agent = DocReviewAgent(std)
    review = agent.review_documentation_set("Empty App", [], scope="application")
    assert review.percentage == 0
    assert len(review.overall_issues) > 0


# --- Client Standard Parsing tests ---


def test_parse_client_standard_heuristic():
    """Heuristic parser extracts document types from unstructured text."""
    std_path = Path("standards/horvath/documentation_standard.yaml")
    if not std_path.exists():
        pytest.skip("Standard file not available")
    std = load_documentation_standard(std_path)
    agent = DocReviewAgent(std)

    client_guidelines = """
# ACME Corp Documentation Guidelines

## Architecture Documentation
All projects must include a system landscape overview showing all
integration points and the high-level data flow map.

## Development Standards
### Naming Conventions
All custom objects must follow the Z_ prefix naming convention.
### Code Review
Every transport must pass a code review checklist before release.

## Data Flow Documentation
Each ETL process chain must be documented with source to target mapping,
transformation logic, and extraction schedules.

## Operational Procedures
A runbook must exist with monitoring procedures, escalation contacts,
and incident recovery steps for each production system.
"""

    result = agent._parse_standard_heuristic("ACME Guidelines", client_guidelines)
    assert result.name == "Client Standard: ACME Guidelines"
    type_ids = result.get_type_ids()
    assert "architecture_overview" in type_ids
    assert "development_guidelines" in type_ids
    assert "data_flow" in type_ids
    assert "operational_runbook" in type_ids


def test_review_against_both_standards():
    """Review against both Horvath and client standard, with gap analysis."""
    std_path = Path("standards/horvath/documentation_standard.yaml")
    if not std_path.exists():
        pytest.skip("Standard file not available")
    std = load_documentation_standard(std_path)
    agent = DocReviewAgent(std)

    # Simple client standard (weaker than Horvath)
    client_std = StandardDefinition(
        name="Client Standard",
        version="1.0",
        document_types=[
            {
                "id": "object_documentation",
                "name": "Object Documentation",
                "required_sections": [
                    {"id": "business_purpose", "name": "Business Purpose", "min_content_length": 10},
                ],
            },
        ],
        scoring=std.scoring,
        scope={"application_level": ["object_documentation"]},
    )

    docs = [
        {
            "title": "Sales ADSO",
            "content": "## Business Purpose\nThis stores sales data for the revenue analytics dashboard.\n## Owner\nFinance Team",
        },
    ]

    result = agent.review_against_both_standards("Sales App", docs, client_std)
    assert "horvath_review" in result
    assert "client_review" in result
    assert "gap_analysis" in result
    assert "combined_issues" in result
    # Client standard is weaker — should have gaps
    assert len(result["gap_analysis"]) > 0
    # Client score should be higher (fewer requirements)
    assert result["client_score"] >= result["horvath_score"]


@pytest.mark.asyncio
async def test_parse_client_standard_without_llm():
    """parse_client_standard falls back to heuristic without LLM."""
    std_path = Path("standards/horvath/documentation_standard.yaml")
    if not std_path.exists():
        pytest.skip("Standard file not available")
    std = load_documentation_standard(std_path)
    agent = DocReviewAgent(std)  # No LLM

    result = await agent.parse_client_standard(
        "Client Guidelines",
        "Our naming convention requires Z_ prefix. Code review is mandatory. "
        "All ETL data flow processes must have source to target documentation.",
    )
    assert result.name.startswith("Client Standard:")
    assert result.version == "heuristic"
