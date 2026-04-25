"""Dual-read graph_repo: file vs Brain paths + write-both trigger on scanner output.

Session C semantics:
  - read_from_brain() defaults True (Brain is the primary source).
  - GRAPH_LEGACY_FILE_FALLBACK=true reads from graph.json instead.
  - write_scan_output() feeds Brain directly; graph.json only written when BRAIN_WRITE_BOTH=true.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from spec2sphere.scanner import graph_repo


@pytest.mark.asyncio
async def test_read_from_brain_by_default(monkeypatch):
    """Brain is the default read source — no env var needed."""
    monkeypatch.delenv("GRAPH_LEGACY_FILE_FALLBACK", raising=False)
    fake = AsyncMock(return_value=[{"id": "seed.obj", "kind": "view", "name": "Seed", "column_ids": []}])
    with patch("spec2sphere.dsp_ai.brain.client.run", fake):
        out = await graph_repo.list_objects("horvath")
    assert out and out[0]["id"] == "seed.obj"


@pytest.mark.asyncio
async def test_read_from_file_when_legacy_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_LEGACY_FILE_FALLBACK", "true")
    (tmp_path / "graph.json").write_text(json.dumps({"nodes": [{"id": "x", "type": "view"}], "edges": []}))
    out = await graph_repo.list_objects("any", output_dir=tmp_path)
    assert any(o["id"] == "x" for o in out)


@pytest.mark.asyncio
async def test_read_from_file_missing_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_LEGACY_FILE_FALLBACK", "true")
    out = await graph_repo.list_objects(output_dir=tmp_path)
    assert out == []


@pytest.mark.asyncio
async def test_read_from_brain_when_flag_on(monkeypatch):
    """Explicit GRAPH_LEGACY_FILE_FALLBACK=false still reads from Brain."""
    monkeypatch.setenv("GRAPH_LEGACY_FILE_FALLBACK", "false")
    fake = AsyncMock(return_value=[{"id": "seed.obj", "kind": "view", "name": "Seed", "column_ids": []}])
    with patch("spec2sphere.dsp_ai.brain.client.run", fake):
        out = await graph_repo.list_objects("horvath")
    assert out and out[0]["id"] == "seed.obj"
    args, kwargs = fake.call_args
    assert "customer" in kwargs
    assert kwargs["customer"] == "horvath"


@pytest.mark.asyncio
async def test_list_edges_from_brain_by_default(monkeypatch):
    """list_edges() defaults to Brain in Session C."""
    monkeypatch.delenv("GRAPH_LEGACY_FILE_FALLBACK", raising=False)
    fake = AsyncMock(return_value=[{"source": "a", "target": "b", "type": "reads_from"}])
    with patch("spec2sphere.dsp_ai.brain.client.run", fake):
        out = await graph_repo.list_edges("horvath")
    assert out == [{"source": "a", "target": "b", "type": "reads_from"}]


@pytest.mark.asyncio
async def test_list_edges_from_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPH_LEGACY_FILE_FALLBACK", "true")
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


def test_write_both_false_feeds_brain_skips_file(tmp_path, monkeypatch):
    """Default (BRAIN_WRITE_BOTH unset): Brain is fed, graph.json NOT written."""
    monkeypatch.delenv("BRAIN_WRITE_BOTH", raising=False)
    from spec2sphere.scanner.output import write_scan_output
    from spec2sphere.scanner.models import ScanResult

    result = ScanResult(source_system="testco", objects=[], dependencies=[])

    with patch("spec2sphere.scanner.output._feed_brain_from_data") as feed_brain, \
         patch("spec2sphere.scanner.output._feed_brain_from_graph") as feed_file:
        write_scan_output(result, tmp_path)

    assert not (tmp_path / "graph.json").exists(), "graph.json should NOT be written by default"
    feed_brain.assert_called_once()
    feed_file.assert_not_called()


def test_write_both_true_writes_file_and_feeds_brain(tmp_path, monkeypatch):
    """BRAIN_WRITE_BOTH=true: graph.json written AND Brain fed from data."""
    monkeypatch.setenv("BRAIN_WRITE_BOTH", "true")
    from spec2sphere.scanner.output import write_scan_output
    from spec2sphere.scanner.models import ScanResult

    result = ScanResult(source_system="testco", objects=[], dependencies=[])

    with patch("spec2sphere.scanner.output._feed_brain_from_data") as feed_brain, \
         patch("spec2sphere.scanner.output._emit_scan_completed"):
        write_scan_output(result, tmp_path)

    assert (tmp_path / "graph.json").exists(), "graph.json should be written when BRAIN_WRITE_BOTH=true"
    feed_brain.assert_called_once()


def test_read_from_brain_flag_default():
    """read_from_brain() returns True by default (no env vars set)."""
    import os
    old = os.environ.pop("GRAPH_LEGACY_FILE_FALLBACK", None)
    try:
        assert graph_repo.read_from_brain() is True
    finally:
        if old is not None:
            os.environ["GRAPH_LEGACY_FILE_FALLBACK"] = old


def test_read_from_brain_flag_disabled_by_legacy_fallback(monkeypatch):
    """GRAPH_LEGACY_FILE_FALLBACK=true disables Brain reads."""
    monkeypatch.setenv("GRAPH_LEGACY_FILE_FALLBACK", "true")
    assert graph_repo.read_from_brain() is False
