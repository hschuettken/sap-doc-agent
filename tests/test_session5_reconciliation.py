"""Tests for Session 5 Task 3: Data Reconciliation Engine.

All database calls are intercepted via patch("spec2sphere.factory.reconciliation._get_conn").
No real database is required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from spec2sphere.factory.reconciliation import (
    classify_delta,
    compute_aggregate_summary,
    run_reconciliation,
)
from spec2sphere.tenant.context import ContextEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ctx() -> ContextEnvelope:
    return ContextEnvelope.single_tenant(
        tenant_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )


def make_mock_conn():
    conn = AsyncMock()
    conn.close = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    return conn


class _DictRecord(dict):
    """Fake asyncpg Record — supports both dict[key] and attribute access."""

    pass


# ---------------------------------------------------------------------------
# Tests: classify_delta
# ---------------------------------------------------------------------------


def test_classify_delta_exact_match():
    """Identical baseline and candidate → 'pass'."""
    baseline = {"revenue": 1000, "cost": 200}
    candidate = {"revenue": 1000, "cost": 200}
    result = classify_delta(baseline, candidate, "exact", 0)
    assert result == "pass"


def test_classify_delta_within_absolute_tolerance():
    """diff=2, tolerance=5 (absolute) → 'within_tolerance'."""
    baseline = {"value": 100}
    candidate = {"value": 102}
    result = classify_delta(baseline, candidate, "absolute", 5)
    assert result == "within_tolerance"


def test_classify_delta_within_percentage_tolerance():
    """1.5% diff with 2.0% tolerance → 'within_tolerance'."""
    baseline = {"amount": 1000.0}
    candidate = {"amount": 1015.0}  # 1.5% higher
    result = classify_delta(baseline, candidate, "percentage", 2.0)
    assert result == "within_tolerance"


def test_classify_delta_exceeds_tolerance():
    """10% diff with 2% tolerance → 'probable_defect'."""
    baseline = {"amount": 1000.0}
    candidate = {"amount": 1100.0}  # 10% higher
    result = classify_delta(baseline, candidate, "percentage", 2.0)
    assert result == "probable_defect"


def test_classify_delta_expected_change():
    """Delta matches expected_delta → 'expected_change'."""
    baseline = {"count": 50}
    candidate = {"count": 55}
    expected_delta = {"count": 5}
    result = classify_delta(baseline, candidate, "absolute", 0, expected_delta=expected_delta)
    assert result == "expected_change"


def test_classify_delta_needs_review_mixed_keys():
    """Extra column in candidate → 'needs_review'."""
    baseline = {"revenue": 1000}
    candidate = {"revenue": 1000, "extra_col": 999}
    result = classify_delta(baseline, candidate, "exact", 0)
    assert result == "needs_review"


# ---------------------------------------------------------------------------
# Tests: run_reconciliation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_reconciliation_stores_results():
    """Mocked DB returns matching rows → result status is 'pass'."""
    ctx = make_ctx()
    conn = make_mock_conn()

    # Both queries return the same row
    row = _DictRecord({"total": 42, "count": 7})
    conn.fetchrow = AsyncMock(return_value=row)

    test_cases = [
        {
            "key": "tc_001",
            "title": "Revenue check",
            "baseline_query": "SELECT 42 AS total, 7 AS count",
            "candidate_query": "SELECT 42 AS total, 7 AS count",
            "tolerance_type": "exact",
            "tolerance_value": 0,
        }
    ]

    with patch("spec2sphere.factory.reconciliation._get_conn", return_value=conn):
        results = await run_reconciliation(ctx, str(uuid.uuid4()), test_cases)

    assert len(results) == 1
    assert results[0]["key"] == "tc_001"
    assert results[0]["delta_status"] == "pass"
    conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_run_reconciliation_query_failure_marks_needs_review():
    """When fetchrow raises an exception, result must be 'needs_review'."""
    ctx = make_ctx()
    conn = make_mock_conn()
    conn.fetchrow = AsyncMock(side_effect=RuntimeError("connection lost"))

    test_cases = [
        {
            "key": "tc_fail",
            "title": "Failing query",
            "baseline_query": "SELECT boom()",
            "candidate_query": "SELECT boom()",
            "tolerance_type": "exact",
            "tolerance_value": 0,
        }
    ]

    with patch("spec2sphere.factory.reconciliation._get_conn", return_value=conn):
        results = await run_reconciliation(ctx, str(uuid.uuid4()), test_cases)

    assert len(results) == 1
    assert results[0]["delta_status"] == "needs_review"
    assert "connection lost" in results[0]["explanation"]


# ---------------------------------------------------------------------------
# Tests: compute_aggregate_summary
# ---------------------------------------------------------------------------


def test_compute_aggregate_summary():
    """2 pass, 1 within_tolerance, 1 probable_defect → correct percentages."""
    results = [
        {"delta_status": "pass"},
        {"delta_status": "pass"},
        {"delta_status": "within_tolerance"},
        {"delta_status": "probable_defect"},
    ]
    summary = compute_aggregate_summary(results)

    assert summary["total"] == 4
    assert summary["pass_pct"] == pytest.approx(50.0)
    assert summary["tolerance_pct"] == pytest.approx(25.0)
    assert summary["defect_pct"] == pytest.approx(25.0)
    assert summary["expected_pct"] == pytest.approx(0.0)
    assert summary["review_pct"] == pytest.approx(0.0)
