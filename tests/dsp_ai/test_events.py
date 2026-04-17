"""Integration test — Postgres LISTEN/NOTIFY round trip.

Requires a reachable Postgres. Skipped when DATABASE_URL is unset
(so unit-test-only CI still passes); docker compose run `-e DATABASE_URL`
or the local `.env` enables it.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from spec2sphere.dsp_ai.events import emit, subscribe

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — integration test",
)


@pytest.mark.asyncio
async def test_notify_round_trip() -> None:
    received: list[dict] = []

    async def consumer() -> None:
        async for event in subscribe("dspai_test_events"):
            received.append(event)
            return  # one and done

    task = asyncio.create_task(consumer())
    # give the LISTEN connection time to attach before emitting
    await asyncio.sleep(0.3)
    await emit("dspai_test_events", {"hello": "world", "n": 1})

    await asyncio.wait_for(task, timeout=3.0)
    assert received == [{"hello": "world", "n": 1}]


@pytest.mark.asyncio
async def test_multiple_events_delivered_in_order() -> None:
    received: list[dict] = []

    async def consumer() -> None:
        async for event in subscribe("dspai_test_events_multi"):
            received.append(event)
            if len(received) == 3:
                return

    task = asyncio.create_task(consumer())
    await asyncio.sleep(0.3)
    for i in range(3):
        await emit("dspai_test_events_multi", {"i": i})

    await asyncio.wait_for(task, timeout=3.0)
    assert [e["i"] for e in received] == [0, 1, 2]
