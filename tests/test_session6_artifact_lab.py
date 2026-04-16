"""Session 6 — Artifact Lab unit tests.

All tests are pure unit tests: no DB connections, no async needed for the
build_* functions and compute_diff.
"""

from __future__ import annotations

import pytest

from spec2sphere.artifact_lab.mutation_catalog import (
    get_mutations,
    is_safe_mutation,
)
from spec2sphere.artifact_lab.lab_runner import compute_diff, run_experiment  # noqa: F401
from spec2sphere.artifact_lab.experiment_tracker import build_experiment_record
from spec2sphere.artifact_lab.template_store import build_template_from_experiment


# ---------------------------------------------------------------------------
# Mutation Catalog (5 tests)
# ---------------------------------------------------------------------------


def test_dsp_relational_view_has_add_field():
    mutations = get_mutations("dsp", "relational_view")
    names = [m["name"] for m in mutations]
    assert "add_field" in names


def test_sac_story_has_add_page():
    mutations = get_mutations("sac", "story")
    names = [m["name"] for m in mutations]
    assert "add_page" in names


def test_add_field_is_safe_for_dsp_relational_view():
    assert is_safe_mutation("dsp", "relational_view", "add_field") is True


def test_drop_table_is_not_safe_for_dsp_relational_view():
    assert is_safe_mutation("dsp", "relational_view", "drop_table") is False


def test_unknown_platform_returns_empty_list():
    mutations = get_mutations("unknown_platform", "relational_view")
    assert mutations == []


# ---------------------------------------------------------------------------
# Experiment Tracker (2 tests)
# ---------------------------------------------------------------------------


def test_build_experiment_record_basic():
    rec = build_experiment_record(
        customer_id="cust-001",
        platform="dsp",
        object_type="relational_view",
        experiment_type="add_field",
        input_definition={"name": "SalesView", "fields": ["id", "amount"]},
        output_definition={"name": "SalesView", "fields": ["id", "amount"]},
        route_used="cdp",
        success=True,
    )
    assert rec.platform == "dsp"
    assert rec.success is True
    assert rec.diff is not None
    assert isinstance(rec.diff, dict)


def test_build_experiment_record_diff_shows_changes():
    rec = build_experiment_record(
        customer_id="cust-001",
        platform="dsp",
        object_type="relational_view",
        experiment_type="modify",
        input_definition={"name": "OldView", "version": 1},
        output_definition={"name": "NewView", "version": 1, "extra_field": "added"},
        route_used="cdp",
        success=True,
    )
    assert rec.diff["changed"] is True
    assert "name" in rec.diff["modifications"]
    assert "extra_field" in rec.diff["additions"]


# ---------------------------------------------------------------------------
# Template Store (1 test)
# ---------------------------------------------------------------------------


def test_build_template_from_experiment():
    exp = build_experiment_record(
        customer_id="cust-002",
        platform="sac",
        object_type="story",
        experiment_type="add_page",
        input_definition={"title": "My Story", "pages": 1},
        output_definition={"title": "My Story", "pages": 2},
        route_used="cdp",
        success=True,
    )
    tmpl = build_template_from_experiment(exp)
    assert tmpl.approved is False
    assert tmpl.confidence == 0.5
    assert tmpl.platform == "sac"
    assert tmpl.customer_id == "cust-002"


# ---------------------------------------------------------------------------
# Lab Runner — compute_diff (3 tests)
# ---------------------------------------------------------------------------


def test_compute_diff_identical_dicts():
    before = {"a": 1, "b": "hello"}
    after = {"a": 1, "b": "hello"}
    diff = compute_diff(before, after)
    assert diff["changed"] is False
    assert diff["additions"] == {}
    assert diff["modifications"] == {}
    assert diff["removals"] == {}


def test_compute_diff_with_changes():
    before = {"a": 1, "b": "old"}
    after = {"a": 1, "b": "new", "c": "brand_new"}
    diff = compute_diff(before, after)
    assert diff["changed"] is True
    assert "b" in diff["modifications"]
    assert diff["modifications"]["b"]["before"] == "old"
    assert diff["modifications"]["b"]["after"] == "new"
    assert "c" in diff["additions"]
    assert diff["additions"]["c"] == "brand_new"


def test_compute_diff_with_removals():
    before = {"keep": 1, "gone": "bye"}
    after = {"keep": 1}
    diff = compute_diff(before, after)
    assert diff["changed"] is True
    assert "gone" in diff["removals"]
    assert diff["removals"]["gone"] == "bye"
    assert diff["additions"] == {}


# ---------------------------------------------------------------------------
# Lab Runner — run_experiment (2 tests)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_experiment_with_cdp_fallback():
    """run_experiment falls back to simulation when Chrome is not available."""
    result = await run_experiment(
        platform="dsp",
        object_type="relational_view",
        experiment_type="create",
        input_definition={"name": "V_TEST", "test_url": "https://example.com"},
        route="cdp",
        environment="sandbox",
    )
    assert result.success is True
    assert result.diff["changed"] is True
    # Whether real CDP or simulation, we get a valid result
    assert result.route_used == "cdp"


@pytest.mark.asyncio
async def test_run_experiment_rejects_production():
    """run_experiment refuses to run in production environment."""
    result = await run_experiment(
        platform="dsp",
        object_type="relational_view",
        experiment_type="create",
        input_definition={"name": "V_TEST"},
        route="cdp",
        environment="production",
    )
    assert result.success is False
    assert "sandbox" in result.error.lower()
