"""Dual-read graph_repo: file vs Brain paths + write-both trigger on scanner output."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from spec2sphere.scanner import graph_repo


@pytest.mark.asyncio
async def test_read_from_file_when_flag_off(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPH_READ_FROM_BRAIN", raising=False)
    (tmp_path / "graph.json").write_text(json.dumps({"nodes": [{"id": "x", "type": "view"}], "edges": []}))
    out = await graph_repo.list_objects("any", output_dir=tmp_path)
    assert any(o["id"] == "x" for o in out)


@pytest.mark.asyncio
async def test_read_from_file_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPH_READ_FROM_BRAIN", raising=False)
    out = await graph_repo.list_objects(output_dir=tmp_path)
    assert out == []


@pytest.mark.asyncio
async def test_read_from_brain_when_flag_on(monkeypatch):
    monkeypatch.setenv("GRAPH_READ_FROM_BRAIN", "true")
    fake = AsyncMock(return_value=[{"id": "seed.obj", "kind": "view", "name": "Seed", "column_ids": []}])
    with patch("spec2sphere.dsp_ai.brain.client.run", fake):
        out = await graph_repo.list_objects("horvath")
    assert out and out[0]["id"] == "seed.obj"
    # Cypher includes customer filter when provided
    args, kwargs = fake.call_args
    assert "customer" in kwargs
    assert kwargs["customer"] == "horvath"


@pytest.mark.asyncio
async def test_list_edges_from_file(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPH_READ_FROM_BRAIN", raising=False)
    (tmp_path / "graph.json").write_text(
        json.dumps(
            {
                "nodes": [],
                "edges": [{"source": "a", "target": "b", "type": "reads_from"}],
            }
        )
    )
    out = await graph_repo.list_edges(output_dir=tmp_path)
    assert out == [{"source": "a", "target": "b", "type": "reads_from"}]


def test_write_both_flag_off_skips_brain_feed(tmp_path, monkeypatch):
    """When BRAIN_WRITE_BOTH is unset, scanner only writes the file."""
    monkeypatch.delenv("BRAIN_WRITE_BOTH", raising=False)
    from spec2sphere.scanner.output import write_scan_output
    from spec2sphere.scanner.models import ScanResult

    result = ScanResult(source_system="testco", objects=[], dependencies=[])

    with patch("spec2sphere.scanner.output._feed_brain_from_graph") as feed:
        write_scan_output(result, tmp_path)
    assert (tmp_path / "graph.json").exists()
    feed.assert_not_called()


def test_write_both_flag_on_calls_brain_feed(tmp_path, monkeypatch):
    monkeypatch.setenv("BRAIN_WRITE_BOTH", "true")
    from spec2sphere.scanner.output import write_scan_output
    from spec2sphere.scanner.models import ScanResult

    result = ScanResult(source_system="testco", objects=[], dependencies=[])

    with patch("spec2sphere.scanner.output._feed_brain_from_graph") as feed:
        write_scan_output(result, tmp_path)
    feed.assert_called_once()
    args, kwargs = feed.call_args
    # First positional is the graph_file path, customer kwarg is "testco"
    assert kwargs.get("customer") == "testco"
