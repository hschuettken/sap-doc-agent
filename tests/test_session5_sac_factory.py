"""Tests for Task 5: SAC Factory — click guide, manifest, adapters, screenshot, QA engines.

All browser/network calls are mocked — no real SAC or browser required.
"""

from __future__ import annotations


from spec2sphere.sac_factory.click_guide_generator import generate_click_guide
from spec2sphere.sac_factory.design_qa import score_design
from spec2sphere.sac_factory.interaction_qa import generate_interaction_tests
from spec2sphere.sac_factory.manifest_builder import build_manifest
from spec2sphere.sac_factory.screenshot_engine import compute_pixel_diff


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SIMPLE_BLUEPRINT = {
    "title": "Revenue Dashboard",
    "archetype": "management_cockpit",
    "artifact_type": "story",
    "pages": [
        {
            "id": "page_1",
            "title": "Monitor Revenue",
            "widgets": [
                {"type": "kpi_tile", "title": "Total Revenue", "binding": "Revenue"},
                {"type": "kpi_tile", "title": "YTD Revenue", "binding": "RevYTD"},
                {"type": "kpi_tile", "title": "Budget Attainment", "binding": "BudgetAtt"},
                {"type": "bar_chart", "title": "Revenue by Region", "binding": "Region/Revenue"},
                {"type": "variance_chart", "title": "Actuals vs Plan", "binding": "ActvsPlan"},
            ],
            "filters": [
                {"dimension": "FiscalYear", "type": "dropdown"},
                {"dimension": "Region", "type": "dropdown"},
            ],
        }
    ],
    "interactions": {
        "navigation": [
            {"from": "page_1", "to": "page_2", "trigger": "click"},
        ]
    },
}


# ---------------------------------------------------------------------------
# 1. generate_click_guide produces markdown
# ---------------------------------------------------------------------------


def test_generate_click_guide_produces_markdown():
    guide = generate_click_guide(SIMPLE_BLUEPRINT)
    assert isinstance(guide, str)
    assert "Revenue Dashboard" in guide
    assert "Monitor Revenue" in guide
    # Widget reference
    assert "Total Revenue" in guide or "kpi_tile" in guide.lower() or "KPI Tile" in guide


# ---------------------------------------------------------------------------
# 2. generate_click_guide includes rollback hints
# ---------------------------------------------------------------------------


def test_generate_click_guide_includes_rollback_hints():
    guide = generate_click_guide(SIMPLE_BLUEPRINT)
    lower = guide.lower()
    assert "rollback" in lower or "undo" in lower


# ---------------------------------------------------------------------------
# 3. build_manifest from blueprint
# ---------------------------------------------------------------------------


def test_build_manifest_from_blueprint():
    manifest = build_manifest(SIMPLE_BLUEPRINT)

    assert manifest["artifact_type"] == "story"
    assert manifest["title"] == "Revenue Dashboard"
    assert len(manifest["pages"]) == 1
    assert manifest["total_widgets"] == 5
    assert manifest["pages"][0]["widget_count"] == 5
    assert manifest["transport_hints"]["package_format"] == "tgz"


# ---------------------------------------------------------------------------
# 4. compute_pixel_diff — identical images → 0%
# ---------------------------------------------------------------------------


def test_pixel_diff_identical_returns_zero():
    pixels = [100, 150, 200, 50, 75]
    result = compute_pixel_diff(pixels, pixels)
    assert result == 0.0


# ---------------------------------------------------------------------------
# 5. compute_pixel_diff — completely different → 100%
# ---------------------------------------------------------------------------


def test_pixel_diff_different():
    # All pixels differ by more than threshold (10)
    a = [0] * 100
    b = [255] * 100
    result = compute_pixel_diff(a, b)
    assert result == 100.0


# ---------------------------------------------------------------------------
# 6. compute_pixel_diff — partial difference
# ---------------------------------------------------------------------------


def test_pixel_diff_partial():
    # First 50 identical, last 50 differ by 200 (well above threshold)
    a = [100] * 50 + [0] * 50
    b = [100] * 50 + [200] * 50
    result = compute_pixel_diff(a, b)
    # Expect ~50% diff
    assert 45.0 <= result <= 55.0


# ---------------------------------------------------------------------------
# 7. generate_interaction_tests extracts tests
# ---------------------------------------------------------------------------


def test_generate_interaction_tests():
    test_spec = {
        "test_cases": {
            "interaction": [
                {
                    "title": "Filter by Year",
                    "test_type": "filter",
                    "dimension": "FiscalYear",
                },
                {
                    "title": "Navigate to Detail",
                    "test_type": "navigation",
                    "from_page": "page_1",
                    "to_page": "page_2",
                },
            ]
        }
    }
    tests = generate_interaction_tests(test_spec)
    assert len(tests) == 2
    assert tests[0]["title"] == "Filter by Year"
    assert tests[0]["test_type"] == "filter"
    assert tests[1]["title"] == "Navigate to Detail"
    assert tests[1]["test_type"] == "navigation"


# ---------------------------------------------------------------------------
# 8. score_design — good management_cockpit → >= 60
# ---------------------------------------------------------------------------


def test_score_design_good_dashboard():
    page = {
        "title": "Monitor Revenue",
        "widgets": [
            {"type": "kpi_tile", "title": "Revenue"},
            {"type": "kpi_tile", "title": "EBIT"},
            {"type": "kpi_tile", "title": "Budget"},
            {"type": "bar_chart", "title": "Revenue by Region"},
            {"type": "variance_chart", "title": "Actuals vs Plan"},
        ],
        "filters": [
            {"dimension": "FiscalYear", "type": "dropdown"},
        ],
    }
    result = score_design(page, archetype="management_cockpit")
    assert result["total_score"] >= 60
    assert "breakdown" in result
    assert "violations" in result


# ---------------------------------------------------------------------------
# 9. score_design — too many KPIs → < 70, kpi mention in violations
# ---------------------------------------------------------------------------


def test_score_design_too_many_kpis():
    page = {
        "title": "Analyze Revenue",
        "widgets": [{"type": "kpi_tile", "title": f"KPI {i}"} for i in range(15)],
        "filters": [{"dimension": "Year", "type": "dropdown"}],
    }
    result = score_design(page, archetype="management_cockpit")
    assert result["total_score"] < 70
    violation_text = " ".join(result["violations"]).lower()
    assert "kpi" in violation_text


# ---------------------------------------------------------------------------
# 10. score_design — bad title ("Page 1") → violation about title
# ---------------------------------------------------------------------------


def test_score_design_bad_title():
    page = {
        "title": "Page 1",
        "widgets": [
            {"type": "kpi_tile", "title": "Revenue"},
            {"type": "bar_chart", "title": "Sales"},
        ],
        "filters": [],
    }
    result = score_design(page, archetype="exec_overview")
    violation_text = " ".join(result["violations"]).lower()
    assert "title" in violation_text or "page 1" in violation_text
