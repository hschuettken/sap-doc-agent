"""Tests for chain API routes."""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sap_doc_agent.web.server import create_app

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_bw_scan"


@pytest.fixture
def output_with_chains(tmp_path):
    """Copy fixture and build chains so the API can serve them."""
    fixture_copy = tmp_path / "output"
    shutil.copytree(FIXTURE_DIR, fixture_copy)

    # Build chains from fixture graph
    from sap_doc_agent.scanner.chain_builder import build_chains_from_graph
    from sap_doc_agent.scanner.output import render_chain_markdown

    with open(fixture_copy / "graph.json") as f:
        graph = json.load(f)

    chains = build_chains_from_graph(graph)
    chains_dir = fixture_copy / "chains"
    chains_dir.mkdir(exist_ok=True)
    for chain in chains:
        (chains_dir / f"{chain.chain_id}.json").write_text(chain.model_dump_json(indent=2))
        (chains_dir / f"{chain.chain_id}.md").write_text(render_chain_markdown(chain))
    return fixture_copy


@pytest.fixture
def client(output_with_chains):
    app = create_app(output_dir=str(output_with_chains))
    return TestClient(app)


def test_api_chains_returns_list(client):
    resp = client.get("/api/chains")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 3


def test_api_chains_contains_expected_fields(client):
    resp = client.get("/api/chains")
    data = resp.json()
    for chain in data:
        assert "chain_id" in chain
        assert "name" in chain
        assert "step_count" in chain
        assert "terminal_object_id" in chain
        assert "confidence" in chain


def test_api_chain_detail_returns_chain(client):
    # Get list first
    chains = client.get("/api/chains").json()
    chain_id = chains[0]["chain_id"]

    resp = client.get(f"/api/chains/{chain_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["chain_id"] == chain_id
    assert "steps" in data
    assert "all_object_ids" in data


def test_api_chain_detail_404_for_missing(client):
    resp = client.get("/api/chains/nonexistent")
    assert resp.status_code == 404


def test_api_chains_empty_when_no_chains(tmp_path):
    """No chains dir → empty list, not error."""
    app = create_app(output_dir=str(tmp_path))
    c = TestClient(app)
    resp = c.get("/api/chains")
    assert resp.status_code == 200
    assert resp.json() == []
