"""Tests for Session 5: Visual QA + Design QA integration.

Tests visual diff classification, noVNC viewer access control, and design scoring.
All tests are synchronous unit tests with no network calls.
"""

from __future__ import annotations

import uuid


from spec2sphere.browser.novnc import (
    get_viewer_count,
    register_viewer,
    unregister_viewer,
    validate_viewer_access,
)
from spec2sphere.sac_factory.design_qa import score_design
from spec2sphere.sac_factory.screenshot_engine import classify_visual_diff
from spec2sphere.tenant.context import ContextEnvelope


def make_ctx():
    """Create a minimal context envelope for testing."""
    return ContextEnvelope.single_tenant(
        tenant_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )


# ---------------------------------------------------------------------------
# Visual comparison tests (screenshot_engine.py)
# ---------------------------------------------------------------------------


def test_classify_visual_diff_pass():
    """Test that very small diff percentage (0.5%) classifies as pass."""
    result = classify_visual_diff(0.5)
    assert result == "pass"


def test_classify_visual_diff_minor():
    """Test that small diff percentage (5.0%) classifies as minor_diff."""
    result = classify_visual_diff(5.0)
    assert result == "minor_diff"


def test_classify_visual_diff_major():
    """Test that large diff percentage (25.0%) classifies as major_diff."""
    result = classify_visual_diff(25.0)
    assert result == "major_diff"


def test_classify_visual_diff_missing_element():
    """Test that missing elements take precedence over diff percentage."""
    result = classify_visual_diff(5.0, elements_missing=2)
    assert result == "missing_element"


# ---------------------------------------------------------------------------
# noVNC viewer access tests (browser/novnc.py)
# ---------------------------------------------------------------------------


def test_validate_viewer_access_admin():
    """Test that admin role has access to viewer."""
    tid = uuid.uuid4()
    uid = uuid.uuid4()
    assert validate_viewer_access(tid, "sandbox", uid, "admin") is True


def test_validate_viewer_access_viewer():
    """Test that viewer role has access to viewer."""
    tid = uuid.uuid4()
    uid = uuid.uuid4()
    assert validate_viewer_access(tid, "sandbox", uid, "viewer") is True


def test_validate_viewer_access_invalid_role():
    """Test that invalid roles are rejected."""
    tid = uuid.uuid4()
    uid = uuid.uuid4()
    assert validate_viewer_access(tid, "sandbox", uid, "unknown_role") is False


def test_validate_viewer_access_no_tenant():
    """Test that missing tenant_id is rejected."""
    uid = uuid.uuid4()
    assert validate_viewer_access(None, "sandbox", uid, "admin") is False


def test_viewer_count_tracking():
    """Test viewer registration, count tracking, and unregistration.

    Verifies:
    - Initial count is 0
    - Count increments on registration
    - Count decrements on unregistration
    - Count returns to 0 when all viewers unregistered
    """
    tid = uuid.uuid4()
    environment = "sandbox"
    user1 = "user1"
    user2 = "user2"

    assert get_viewer_count(tid, environment) == 0

    count = register_viewer(tid, environment, user1)
    assert count == 1

    count = register_viewer(tid, environment, user2)
    assert count == 2

    assert get_viewer_count(tid, environment) == 2

    count = unregister_viewer(tid, environment, user1)
    assert count == 1

    count = unregister_viewer(tid, environment, user2)
    assert count == 0


# ---------------------------------------------------------------------------
# Design QA integration tests (sac_factory/design_qa.py)
# ---------------------------------------------------------------------------


def test_design_qa_full_blueprint():
    """Test comprehensive design QA scoring with good and bad page designs.

    Good page:
    - Has correct archetype-appropriate widget distribution
    - Has descriptive action-oriented title
    - Has reasonable number of widgets
    - Has filters configured

    Bad page:
    - Has mismatched widget distribution (too many KPI tiles)
    - Has generic title
    - Has no filters
    """
    good_page = {
        "archetype": "management_cockpit",
        "title": "Analyze Revenue Trends by Product Line",
        "widgets": [
            {"type": "kpi_tile"},
            {"type": "kpi_tile"},
            {"type": "kpi_tile"},
            {"type": "kpi_tile"},
            {"type": "bar_chart"},
            {"type": "variance_chart"},
        ],
        "filters": [{"dimension": "Year"}, {"dimension": "Region"}],
    }
    result = score_design(good_page, "management_cockpit")

    # Good design should score well
    assert result["total_score"] >= 70
    assert result["breakdown"]["archetype_compliance"] >= 80
    assert isinstance(result["violations"], list)

    bad_page = {
        "archetype": "exec_overview",
        "title": "Page 1",
        "widgets": [{"type": "pie_chart"}] * 3 + [{"type": "kpi_tile"}] * 12,
        "filters": [],
    }
    bad_result = score_design(bad_page, "exec_overview")

    # Bad design should score lower
    assert bad_result["total_score"] < result["total_score"]
    assert len(bad_result["violations"]) > len(result["violations"])
