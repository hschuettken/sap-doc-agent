"""Tests for Session 5 Task 2: Route Router with fitness scoring + safety multipliers.

All database calls are intercepted via patch("spec2sphere.factory.route_router._get_conn").
No real database is required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from spec2sphere.factory.route_router import (
    RouteDecision,
    get_supported_routes,
    select_route,
    update_route_fitness,
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
    conn.execute = AsyncMock(return_value="UPDATE 1")
    return conn


class _DictRecord(dict):
    """Fake asyncpg Record — supports both dict[key] and attribute access."""

    pass


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_route_returns_best_fitness():
    """cdp=0.9 in DB beats api=0.6 in DB → primary must be cdp."""
    ctx = make_ctx()
    conn = make_mock_conn()
    conn.fetch = AsyncMock(
        return_value=[
            _DictRecord({"route": "cdp", "fitness_score": 0.9}),
            _DictRecord({"route": "api", "fitness_score": 0.6}),
        ]
    )

    with patch("spec2sphere.factory.route_router._get_conn", return_value=conn):
        decision = await select_route(ctx, "relational_view", "deploy", "sandbox")

    assert decision.primary_route == "cdp"
    assert decision.scores["cdp"] == pytest.approx(0.9)
    assert decision.scores["api"] == pytest.approx(0.6)
    assert "api" in decision.fallback_chain or "csn_import" in decision.fallback_chain


@pytest.mark.asyncio
async def test_select_route_production_safety_multiplier():
    """In production: api (0.7*1.2=0.84) beats cdp (0.9*0.8=0.72)."""
    ctx = make_ctx()
    conn = make_mock_conn()
    conn.fetch = AsyncMock(
        return_value=[
            _DictRecord({"route": "cdp", "fitness_score": 0.9}),
            _DictRecord({"route": "api", "fitness_score": 0.7}),
        ]
    )

    with patch("spec2sphere.factory.route_router._get_conn", return_value=conn):
        decision = await select_route(ctx, "relational_view", "deploy", "production")

    assert decision.primary_route == "api"
    assert decision.scores["api"] == pytest.approx(0.7 * 1.2)
    assert decision.scores["cdp"] == pytest.approx(0.9 * 0.8)
    assert "cdp" in decision.fallback_chain


@pytest.mark.asyncio
async def test_select_route_no_fitness_data_uses_defaults():
    """Empty DB returns a valid RouteDecision using default scores."""
    ctx = make_ctx()
    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=[])

    with patch("spec2sphere.factory.route_router._get_conn", return_value=conn):
        decision = await select_route(ctx, "relational_view", "deploy", "sandbox")

    assert isinstance(decision, RouteDecision)
    assert decision.primary_route in {"cdp", "api", "csn_import"}
    # cdp default=0.7 is highest for DSP views in sandbox
    assert decision.primary_route == "cdp"
    assert len(decision.fallback_chain) >= 1
    assert decision.reason != ""


@pytest.mark.asyncio
async def test_select_route_sac_artifact():
    """story gets cdp/click_guide/manifest/api — csn_import must NOT appear."""
    ctx = make_ctx()
    conn = make_mock_conn()
    conn.fetch = AsyncMock(return_value=[])

    with patch("spec2sphere.factory.route_router._get_conn", return_value=conn):
        decision = await select_route(ctx, "story", "deploy", "sandbox")

    all_routes = [decision.primary_route] + decision.fallback_chain
    assert "csn_import" not in all_routes
    assert set(all_routes) <= {"cdp", "click_guide", "manifest", "api"}
    assert len(all_routes) == 4


@pytest.mark.asyncio
async def test_update_route_fitness_success():
    """Existing row: attempts+1, successes+1, EMA duration, fitness recalculated."""
    ctx = make_ctx()
    conn = make_mock_conn()
    existing_id = uuid.uuid4()
    conn.fetchrow = AsyncMock(
        return_value=_DictRecord(
            {
                "id": existing_id,
                "attempts": 10,
                "successes": 8,
                "avg_duration_seconds": 5.0,
            }
        )
    )

    with patch("spec2sphere.factory.route_router._get_conn", return_value=conn):
        await update_route_fitness(ctx, "relational_view", "deploy", "cdp", True, 3.0)

    conn.execute.assert_awaited_once()
    call_args = conn.execute.call_args
    sql = call_args[0][0]
    # Should be an UPDATE not an INSERT
    assert "UPDATE" in sql.upper()
    positional = call_args[0]
    # new_attempts = 11, new_successes = 9
    assert positional[1] == 11  # attempts
    assert positional[2] == 9  # successes
    # EMA: 0.3*3.0 + 0.7*5.0 = 0.9 + 3.5 = 4.4
    assert positional[3] == pytest.approx(4.4, rel=1e-4)
    # fitness = 9/11
    assert positional[4] == pytest.approx(9 / 11, rel=1e-4)


@pytest.mark.asyncio
async def test_update_route_fitness_failure_records_reason():
    """New row (no existing): INSERT with failure_reason recorded."""
    ctx = make_ctx()
    conn = make_mock_conn()
    conn.fetchrow = AsyncMock(return_value=None)  # no existing row

    with patch("spec2sphere.factory.route_router._get_conn", return_value=conn):
        await update_route_fitness(ctx, "story", "deploy", "cdp", False, 12.5, "timeout after 12s")

    conn.execute.assert_awaited_once()
    call_args = conn.execute.call_args
    sql = call_args[0][0]
    assert "INSERT" in sql.upper()
    positional = call_args[0]
    # fitness = 0/1 = 0.0 for failure, failure_reason should be in args
    assert "timeout after 12s" in positional


def test_get_supported_routes_dsp():
    """relational_view supports cdp, api, csn_import."""
    routes = get_supported_routes("relational_view", "deploy")
    assert set(routes) == {"cdp", "api", "csn_import"}


def test_get_supported_routes_sac():
    """story supports cdp and click_guide (and manifest/api) — csn_import absent."""
    routes = get_supported_routes("story", "deploy")
    assert "csn_import" not in routes
    assert "cdp" in routes
    assert "click_guide" in routes


def test_route_decision_dataclass():
    """RouteDecision holds all required fields with correct types."""
    decision = RouteDecision(
        primary_route="cdp",
        fallback_chain=["api", "csn_import"],
        scores={"cdp": 0.9, "api": 0.6, "csn_import": 0.5},
        reason="cdp has highest fitness",
    )
    assert decision.primary_route == "cdp"
    assert decision.fallback_chain == ["api", "csn_import"]
    assert decision.scores["cdp"] == 0.9
    assert "highest" in decision.reason
