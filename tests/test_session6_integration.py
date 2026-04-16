"""Session 6 E2E integration test — Governance + Artifact Lab + Style Learning.

All tests are pure Python: no DB, no mocks, no network calls.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

# ---------------------------------------------------------------------------
# Modules under test
# ---------------------------------------------------------------------------
from spec2sphere.governance.doc_generator import (
    generate_decision_log,
    generate_functional_doc,
    generate_reconciliation_report,
    generate_technical_doc,
    generate_traceability_matrix,
    render_html_report,
    render_markdown_report,
)
from spec2sphere.governance.release import assemble_release_package
from spec2sphere.governance.promotion import anonymize_content
from spec2sphere.sac_factory.style_learning import get_style_profile, update_preference
from spec2sphere.artifact_lab.lab_runner import compute_diff
from spec2sphere.artifact_lab.experiment_tracker import build_experiment_record
from spec2sphere.artifact_lab.template_store import build_template_from_experiment
from spec2sphere.artifact_lab.mutation_catalog import get_mutations, is_safe_mutation


# ---------------------------------------------------------------------------
# Shared demo fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def demo_project() -> dict:
    """Self-contained demo project data dict — mirrors a real pipeline context."""
    return {
        "project": {"name": "Sales Planning", "slug": "sales-planning"},
        "customer": {"name": "Horvath Demo", "slug": "horvath-demo"},
        "requirements": [
            {
                "id": "REQ-001",
                "title": "Revenue KPI Model",
                "business_domain": "Finance",
                "status": "approved",
                "parsed_kpis": [
                    {"name": "Net Revenue", "formula": "gross_sales - discounts - returns"},
                    {"name": "Gross Margin", "formula": "(net_revenue - cogs) / net_revenue"},
                ],
                "parsed_entities": {
                    "dimensions": ["Time", "Product", "Geography"],
                },
            }
        ],
        "hla_documents": [
            {
                "id": "HLA-001",
                "narrative": "Three-layer architecture: raw ingestion, harmonisation, mart.",
                "layers": ["raw", "harmonisation", "mart"],
            }
        ],
        "tech_specs": [
            {
                "id": "SPEC-001",
                "objects": [
                    {"name": "V_RAW_REVENUE", "object_type": "relational_view", "platform": "DSP", "layer": "raw"},
                    {
                        "name": "V_HARM_REVENUE",
                        "object_type": "relational_view",
                        "platform": "DSP",
                        "layer": "harmonisation",
                    },
                    {"name": "V_MART_REVENUE", "object_type": "fact_view", "platform": "DSP", "layer": "mart"},
                ],
                "deployment_order": ["V_RAW_REVENUE", "V_HARM_REVENUE", "V_MART_REVENUE"],
            }
        ],
        "architecture_decisions": [
            {
                "topic": "Aggregation",
                "choice": "Pre-aggregate at mart layer",
                "rationale": "Reduces query time for executive dashboards",
                "alternatives": ["Aggregate at runtime", "No aggregation"],
                "platform_placement": "DSP",
            },
            {
                "topic": "Time Hierarchy",
                "choice": "DSP hierarchy view",
                "rationale": "Native DSP hierarchy for calendar week support",
                "alternatives": ["BW time dimension"],
                "platform_placement": "DSP",
            },
        ],
        "reconciliation_results": [
            {
                "test_case_key": "revenue_total",
                "delta_status": "pass",
                "expected": 1_000_000,
                "actual": 1_000_000,
            },
            {
                "test_case_key": "margin_avg",
                "delta_status": "tolerance",
                "expected": 0.35,
                "actual": 0.351,
            },
        ],
        "technical_objects": [
            {
                "name": "V_RAW_REVENUE",
                "object_type": "relational_view",
                "platform": "DSP",
                "layer": "raw",
                "status": "deployed",
                "generated_artifact": "CREATE VIEW V_RAW_REVENUE AS SELECT * FROM VBAK JOIN VBAP ON VBAK.VBELN = VBAP.VBELN;",
            },
            {
                "name": "V_HARM_REVENUE",
                "object_type": "relational_view",
                "platform": "DSP",
                "layer": "harmonisation",
                "status": "deployed",
                "generated_artifact": "CREATE VIEW V_HARM_REVENUE AS SELECT VBELN, NETWR, WAERK FROM V_RAW_REVENUE;",
            },
            {
                "name": "V_MART_REVENUE",
                "object_type": "fact_view",
                "platform": "DSP",
                "layer": "mart",
                "status": "deployed",
                "generated_artifact": "CREATE VIEW V_MART_REVENUE AS SELECT SUM(NETWR) AS NET_REVENUE, WAERK FROM V_HARM_REVENUE GROUP BY WAERK;",
            },
        ],
        "approvals": [
            {"approver": "h.schuettken@example.com", "stage": "technical", "status": "approved"},
            {"approver": "sponsor@example.com", "stage": "business", "status": "approved"},
        ],
    }


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


class TestE2EPipeline:
    # ------------------------------------------------------------------
    # 1. Technical documentation
    # ------------------------------------------------------------------

    def test_01_generate_all_docs(self, demo_project):
        tech = generate_technical_doc(demo_project)
        func = generate_functional_doc(demo_project)

        # Technical doc should reference all 3 objects
        assert tech["object_count"] == 3
        assert "V_RAW_REVENUE" in tech["content"]
        assert "V_HARM_REVENUE" in tech["content"]
        assert "V_MART_REVENUE" in tech["content"]

        # Functional doc should reference both KPIs
        assert "Net Revenue" in func["content"]
        assert "Gross Margin" in func["content"]
        assert "Finance" in func["content"]

    # ------------------------------------------------------------------
    # 2. Traceability matrix
    # ------------------------------------------------------------------

    def test_02_traceability(self, demo_project):
        result = generate_traceability_matrix(demo_project)
        rows = result["rows"]

        # 1 requirement → 1 row
        assert len(rows) == 1

        row = rows[0]
        # Result is PASS or PARTIAL/tolerance (tolerance because margin_avg is tolerance)
        assert row["result"] in ("pass", "tolerance", "PASS", "PARTIAL")

    # ------------------------------------------------------------------
    # 3. Decision log
    # ------------------------------------------------------------------

    def test_03_decision_log(self, demo_project):
        log = generate_decision_log(demo_project)

        assert len(log) == 2
        topics = [d["topic"] for d in log]
        assert "Aggregation" in topics

    # ------------------------------------------------------------------
    # 4. Reconciliation summary
    # ------------------------------------------------------------------

    def test_04_reconciliation_summary(self, demo_project):
        summary = generate_reconciliation_report(demo_project)

        assert summary["total_tests"] == 2
        assert summary["passed"] == 1
        assert summary["tolerance"] == 1
        assert summary["failed"] == 0

    # ------------------------------------------------------------------
    # 5. HTML report
    # ------------------------------------------------------------------

    def test_05_html_report(self, demo_project):
        html = render_html_report(demo_project)

        assert "<!DOCTYPE html" in html or "<!doctype html" in html.lower()
        assert "Sales Planning" in html
        assert "V_RAW_REVENUE" in html
        assert "Horvath Demo" in html
        assert "Traceability Matrix" in html

    # ------------------------------------------------------------------
    # 6. Markdown report
    # ------------------------------------------------------------------

    def test_06_markdown_report(self, demo_project):
        md = render_markdown_report(demo_project)

        assert "# " in md and "Sales Planning" in md
        assert "## Traceability Matrix" in md
        assert "## Architecture Decision" in md

    # ------------------------------------------------------------------
    # 7. Release package
    # ------------------------------------------------------------------

    def test_07_release_package(self, demo_project):
        pkg_bytes = assemble_release_package(demo_project, version="1.0.0")

        zf = zipfile.ZipFile(io.BytesIO(pkg_bytes))
        names = zf.namelist()

        assert "manifest.json" in names
        assert "docs/technical.html" in names
        assert "docs/functional.md" in names
        assert "reconciliation/summary.json" in names

        # At least one artifact SQL file
        artifact_files = [n for n in names if n.startswith("artifacts/")]
        assert len(artifact_files) >= 1

        # Manifest contents
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["version"] == "1.0.0"
        assert manifest["object_count"] == 3

    # ------------------------------------------------------------------
    # 8. Artifact lab flow: build_experiment_record → build_template_from_experiment
    # ------------------------------------------------------------------

    def test_08_artifact_lab_flow(self, demo_project):
        input_def = {"select_fields": ["VBELN", "NETWR"], "source": "VBAK"}
        output_def = {"select_fields": ["VBELN", "NETWR", "WAERK"], "source": "VBAK", "_experiment": "add_field"}

        record = build_experiment_record(
            customer_id="cust-001",
            platform="dsp",
            object_type="relational_view",
            experiment_type="add_field",
            input_definition=input_def,
            output_definition=output_def,
            route_used="cdp",
            success=True,
            notes="Integration test experiment",
        )

        assert record.success is True
        assert record.platform == "dsp"
        assert record.diff["changed"] is True

        template = build_template_from_experiment(record)

        # Template is unapproved, confidence=0.5
        assert template.approved is False
        assert template.confidence == 0.5
        assert template.customer_id == "cust-001"
        assert template.platform == "dsp"

    # ------------------------------------------------------------------
    # 9. Mutation catalog
    # ------------------------------------------------------------------

    def test_09_mutation_catalog(self, demo_project):
        dsp_mutations = get_mutations("dsp", "relational_view")
        sac_mutations = get_mutations("sac", "story")

        assert len(dsp_mutations) >= 5
        assert len(sac_mutations) >= 4

        # add_field is safe
        assert is_safe_mutation("dsp", "relational_view", "add_field") is True
        # drop_table is unsafe
        assert is_safe_mutation("dsp", "relational_view", "drop_table") is False

    # ------------------------------------------------------------------
    # 10. Promotion anonymisation
    # ------------------------------------------------------------------

    def test_10_promotion_anonymization(self, demo_project):
        content = {
            "customer_name": "Horvath Demo",
            "description": "Revenue model built for Horvath Demo Finance division",
            "kpi_names": ["Net Revenue", "Gross Margin"],
            "pattern": "SELECT amount FROM sales_orders",
        }

        anon = anonymize_content(content, customer_terms=["Horvath Demo"])

        # customer_name field is stripped entirely
        assert "customer_name" not in anon
        # kpi_names field is stripped entirely
        assert "kpi_names" not in anon
        # Customer name in description is redacted
        assert "Horvath Demo" not in anon.get("description", "")
        assert "[REDACTED]" in anon.get("description", "")
        # Non-PII pattern field is preserved (no overlapping tokens)
        assert "pattern" in anon

    # ------------------------------------------------------------------
    # 11. Style learning
    # ------------------------------------------------------------------

    def test_11_style_learning(self, demo_project):
        prefs: dict = {}

        # Train: grid layout wins over table
        prefs = update_preference(prefs, "layout", "grid", approved=True)
        prefs = update_preference(prefs, "layout", "grid", approved=True)
        prefs = update_preference(prefs, "layout", "table", approved=True)

        # Train: bar chart wins over pie
        prefs = update_preference(prefs, "chart", "bar", approved=True)
        prefs = update_preference(prefs, "chart", "bar", approved=True)
        prefs = update_preference(prefs, "chart", "pie", approved=False)

        profile = get_style_profile(prefs)

        # grid should rank above table (higher score)
        preferred_layouts = profile["preferred_layouts"]
        assert "grid" in preferred_layouts
        assert "table" in preferred_layouts
        assert preferred_layouts.index("grid") < preferred_layouts.index("table")

        # bar should appear, pie should not (score <= 0)
        preferred_charts = profile["preferred_charts"]
        assert "bar" in preferred_charts
        assert "pie" not in preferred_charts

    # ------------------------------------------------------------------
    # 12. Diff engine
    # ------------------------------------------------------------------

    def test_12_diff_engine(self, demo_project):
        before = {
            "select_fields": ["VBELN", "NETWR"],
            "source": "VBAK",
            "filter": "MANDT = '100'",
        }
        after = {
            "select_fields": ["VBELN", "NETWR", "WAERK"],  # modified
            "source": "VBAK",
            "join": "VBAP ON VBAK.VBELN = VBAP.VBELN",  # added
            # filter removed
        }

        diff = compute_diff(before, after)

        assert diff["changed"] is True
        assert "join" in diff["additions"]
        assert "filter" in diff["removals"]
        assert "select_fields" in diff["modifications"]
        assert diff["modifications"]["select_fields"]["before"] == ["VBELN", "NETWR"]
        assert diff["modifications"]["select_fields"]["after"] == ["VBELN", "NETWR", "WAERK"]
