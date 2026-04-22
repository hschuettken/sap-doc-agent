"""Unit tests for cost_guard.py — pure logic that doesn't touch the DB."""

from __future__ import annotations

import os

import pytest

from spec2sphere.dsp_ai.cost_guard import (
    CostExceeded,
    DEFAULT_CAP_USD,
    GLOBAL_CAP_USD,
)


def _ensure_no_db():
    """Skip if DATABASE_URL is set — we don't want to hit a real DB in unit tests."""
    if os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL set — use integration suite for DB tests")


class TestCostGuardConstants:
    def test_default_cap_positive(self):
        assert DEFAULT_CAP_USD > 0

    def test_global_cap_positive(self):
        assert GLOBAL_CAP_USD > 0

    def test_global_cap_gte_default(self):
        # Global cap should generally be >= per-enhancement cap
        assert GLOBAL_CAP_USD >= DEFAULT_CAP_USD

    def test_cost_exceeded_is_exception(self):
        exc = CostExceeded("test")
        assert isinstance(exc, Exception)
        assert "test" in str(exc)


class TestCostExceededException:
    def test_message_includes_detail(self):
        exc = CostExceeded("enh-123: 10.00 > cap 5.00")
        assert "10.00" in str(exc)
        assert "5.00" in str(exc)

    def test_is_catchable_as_exception(self):
        try:
            raise CostExceeded("over cap")
        except Exception as exc:
            assert "over cap" in str(exc)
