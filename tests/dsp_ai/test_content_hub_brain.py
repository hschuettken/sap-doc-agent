"""ContentHub Brain-backed methods — best-effort Neo4j lookups with fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from spec2sphere.copilot.content_hub import ContentHub


@pytest.mark.asyncio
async def test_list_topics_returns_empty_when_brain_down() -> None:
    hub = ContentHub()
    with patch(
        "spec2sphere.dsp_ai.brain.client.run",
        AsyncMock(side_effect=ConnectionError("no brain")),
    ):
        topics = await hub.list_topics()
    assert topics == []


@pytest.mark.asyncio
async def test_list_topics_returns_brain_rows() -> None:
    hub = ContentHub()
    with patch(
        "spec2sphere.dsp_ai.brain.client.run",
        AsyncMock(return_value=[{"name": "Sales", "vector": None}]),
    ):
        topics = await hub.list_topics()
    assert topics == [{"name": "Sales", "vector": None}]


@pytest.mark.asyncio
async def test_objects_for_topic_passes_name_param() -> None:
    hub = ContentHub()
    fake = AsyncMock(return_value=[{"id": "s.sales", "name": "Sales daily", "kind": "view"}])
    with patch("spec2sphere.dsp_ai.brain.client.run", fake):
        out = await hub.objects_for_topic("Sales")
    assert out and out[0]["id"] == "s.sales"
    args, kwargs = fake.call_args
    assert kwargs.get("t") == "Sales"


@pytest.mark.asyncio
async def test_lookup_object_prefers_brain() -> None:
    hub = ContentHub()
    fake = AsyncMock(return_value=[{"id": "x", "name": "X", "kind": "view", "column_ids": []}])
    with patch("spec2sphere.dsp_ai.brain.client.run", fake):
        obj = await hub.lookup_object("x")
    assert obj and obj["id"] == "x"
    fake.assert_awaited_once()


@pytest.mark.asyncio
async def test_lookup_object_falls_back_to_graph_repo(monkeypatch, tmp_path) -> None:
    """Brain returns no rows → graph_repo resolves from the legacy file."""
    hub = ContentHub()
    # Brain returns empty list
    fake_brain = AsyncMock(return_value=[])
    fake_repo = AsyncMock(return_value=[{"id": "x", "name": "X", "type": "view"}])
    monkeypatch.delenv("GRAPH_READ_FROM_BRAIN", raising=False)
    with (
        patch("spec2sphere.dsp_ai.brain.client.run", fake_brain),
        patch("spec2sphere.scanner.graph_repo.list_objects", fake_repo),
    ):
        obj = await hub.lookup_object("x")
    assert obj and obj["id"] == "x"


@pytest.mark.asyncio
async def test_lookup_object_none_when_unknown() -> None:
    hub = ContentHub()
    with (
        patch("spec2sphere.dsp_ai.brain.client.run", AsyncMock(return_value=[])),
        patch("spec2sphere.scanner.graph_repo.list_objects", AsyncMock(return_value=[])),
    ):
        obj = await hub.lookup_object("nope")
    assert obj is None
