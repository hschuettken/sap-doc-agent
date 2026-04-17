"""Unit tests for the behavior feeder (Task 3).

All tests are fully mocked — no live Postgres or Neo4j required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spec2sphere.dsp_ai.adapters.live import TelemetryEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_conn() -> MagicMock:
    """Return a mock asyncpg connection that supports async context manager."""
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.close = AsyncMock()
    return conn


# ---------------------------------------------------------------------------
# record_event tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rendered_event_upserts_user_state_and_opened_edge() -> None:
    """widget.rendered → upserts user_state and writes OPENED edge."""
    conn = _fake_conn()
    brain = AsyncMock(return_value=[])

    with (
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.asyncpg.connect", AsyncMock(return_value=conn)),
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.brain_run", brain),
    ):
        from spec2sphere.dsp_ai.brain.feeders.behavior import record_event

        event = TelemetryEvent(kind="widget.rendered", user_id="h@x", object_id="s.sales")
        await record_event(event)

    # Postgres upsert was called
    conn.execute.assert_awaited_once()
    sql_arg = conn.execute.call_args[0][0]
    assert "INSERT INTO dsp_ai.user_state" in sql_arg
    assert "ON CONFLICT" in sql_arg

    # Brain got one call containing OPENED
    brain.assert_awaited_once()
    cypher = brain.call_args[0][0]
    assert "OPENED" in cypher


@pytest.mark.asyncio
async def test_dwelled_event_records_duration() -> None:
    """widget.dwelled → DWELLED_ON edge with duration param."""
    conn = _fake_conn()
    brain = AsyncMock(return_value=[])

    with (
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.asyncpg.connect", AsyncMock(return_value=conn)),
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.brain_run", brain),
    ):
        from spec2sphere.dsp_ai.brain.feeders.behavior import record_event

        event = TelemetryEvent(kind="widget.dwelled", user_id="h@x", object_id="s.sales", duration_s=3.5)
        await record_event(event)

    brain.assert_awaited_once()
    cypher = brain.call_args[0][0]
    assert "DWELLED_ON" in cypher
    kwargs = brain.call_args[1]
    assert kwargs["d"] == 3.5


@pytest.mark.asyncio
async def test_clicked_event_increments_count() -> None:
    """widget.clicked → CLICKED edge with count increment."""
    conn = _fake_conn()
    brain = AsyncMock(return_value=[])

    with (
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.asyncpg.connect", AsyncMock(return_value=conn)),
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.brain_run", brain),
    ):
        from spec2sphere.dsp_ai.brain.feeders.behavior import record_event

        event = TelemetryEvent(kind="widget.clicked", user_id="h@x", object_id="s.sales")
        await record_event(event)

    brain.assert_awaited_once()
    cypher = brain.call_args[0][0]
    assert "CLICKED" in cypher
    assert "count" in cypher


@pytest.mark.asyncio
async def test_no_object_id_skips_brain_write() -> None:
    """Events without object_id still upsert user_state but skip brain write."""
    conn = _fake_conn()
    brain = AsyncMock(return_value=[])

    with (
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.asyncpg.connect", AsyncMock(return_value=conn)),
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.brain_run", brain),
    ):
        from spec2sphere.dsp_ai.brain.feeders.behavior import record_event

        event = TelemetryEvent(kind="widget.rendered", user_id="h@x")
        await record_event(event)

    conn.execute.assert_awaited_once()
    brain.assert_not_awaited()


@pytest.mark.asyncio
async def test_brain_write_failure_does_not_propagate() -> None:
    """Brain failure is swallowed; record_event must not raise."""
    conn = _fake_conn()
    brain = AsyncMock(side_effect=RuntimeError("neo4j down"))

    with (
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.asyncpg.connect", AsyncMock(return_value=conn)),
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.brain_run", brain),
    ):
        from spec2sphere.dsp_ai.brain.feeders.behavior import record_event

        event = TelemetryEvent(kind="widget.rendered", user_id="h@x", object_id="s.sales")
        # Must not raise even though brain_run blows up
        await record_event(event)

    # Postgres upsert still happened
    conn.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# synthesize_topics_async tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesize_topics_writes_interested_in_edges() -> None:
    """One user with objects → LLM clusters → INTERESTED_IN edge written."""
    user_row = {"email": "h@x", "objects": ["s.sales", "s.finance"]}

    # brain_run is called twice: once for the query, once for the MERGE
    brain_calls: list[str] = []

    async def brain_side_effect(cypher: str, **_kwargs):
        brain_calls.append(cypher)
        if "MATCH (u:User)" in cypher:
            return [user_row]
        return []

    llm_result = ({"topics": [{"name": "Sales", "members": ["s.sales"], "weight": 0.8}]}, {})

    with (
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.brain_run", side_effect=brain_side_effect),
        patch("spec2sphere.llm.quality_router.resolve_and_call", AsyncMock(return_value=llm_result)),
    ):
        from spec2sphere.dsp_ai.brain.feeders.behavior import synthesize_topics_async

        result = await synthesize_topics_async()

    assert result == {"users_seen": 1, "topics_written": 1}
    # The last brain_run call must contain INTERESTED_IN
    assert any("INTERESTED_IN" in c for c in brain_calls)


@pytest.mark.asyncio
async def test_synthesize_topics_handles_empty_users() -> None:
    """No active users → early return, LLM never called."""
    llm_mock = AsyncMock()

    with (
        patch("spec2sphere.dsp_ai.brain.feeders.behavior.brain_run", AsyncMock(return_value=[])),
        patch("spec2sphere.llm.quality_router.resolve_and_call", llm_mock),
    ):
        from spec2sphere.dsp_ai.brain.feeders.behavior import synthesize_topics_async

        result = await synthesize_topics_async()

    assert result == {"users_seen": 0, "topics_written": 0}
    llm_mock.assert_not_awaited()
