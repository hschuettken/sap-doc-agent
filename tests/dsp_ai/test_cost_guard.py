"""Cost guardrails — logic-level tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from spec2sphere.dsp_ai.cost_guard import (
    CostExceeded,
    check_before_call,
    estimate_cost,
)


def test_estimate_unknown_model_returns_zero():
    assert estimate_cost("unknown-model", 1000, 500) == 0.0


def test_estimate_known_model_scales():
    # claude-haiku-4-5 = 0.0008 / 1K tokens; 2000 tokens → 0.0016
    cost = estimate_cost("claude-haiku-4-5", 1000, 1000)
    assert cost == pytest.approx(0.0016, rel=1e-3)


def test_estimate_gpt_4o():
    # 0.005 / 1K tokens * 1500 tokens = 0.0075
    assert estimate_cost("gpt-4o", 1000, 500) == pytest.approx(0.0075, rel=1e-3)


@pytest.mark.asyncio
async def test_check_raises_on_global_cap_breach(monkeypatch):
    monkeypatch.setenv("COST_GUARD_GLOBAL_CAP_USD", "0.01")
    monkeypatch.setenv("COST_GUARD_ENFORCED", "true")
    with patch(
        "spec2sphere.dsp_ai.cost_guard.month_total_global",
        new=AsyncMock(return_value=0.02),
    ):
        with pytest.raises(CostExceeded) as exc_info:
            await check_before_call(None, 0.001)
        assert exc_info.value.scope == "global"


@pytest.mark.asyncio
async def test_check_log_only_does_not_raise(monkeypatch, caplog):
    monkeypatch.setenv("COST_GUARD_GLOBAL_CAP_USD", "0.01")
    monkeypatch.setenv("COST_GUARD_ENFORCED", "false")
    with patch(
        "spec2sphere.dsp_ai.cost_guard.month_total_global",
        new=AsyncMock(return_value=0.02),
    ):
        # must NOT raise in log-only mode
        await check_before_call(None, 0.001)


@pytest.mark.asyncio
async def test_check_passes_when_under_cap(monkeypatch):
    monkeypatch.setenv("COST_GUARD_GLOBAL_CAP_USD", "1.00")
    with patch(
        "spec2sphere.dsp_ai.cost_guard.month_total_global",
        new=AsyncMock(return_value=0.10),
    ):
        await check_before_call(None, 0.05)  # 0.15 < 1.0, no raise


@pytest.mark.asyncio
async def test_disabled_global_cap_skips_check(monkeypatch):
    """COST_GUARD_GLOBAL_CAP_USD=0 disables the global check entirely."""
    monkeypatch.setenv("COST_GUARD_GLOBAL_CAP_USD", "0")
    with patch(
        "spec2sphere.dsp_ai.cost_guard.month_total_global",
        new=AsyncMock(return_value=99999.0),
    ):
        await check_before_call(None, 1000.0)  # must not raise
