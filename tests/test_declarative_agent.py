"""Tests for the Declarative Agent endpoints.

Hits:
  GET /api/copilot/agent/manifest.yaml
  GET /api/copilot/agent/openapi.yaml
  POST /api/copilot/agent/actions/search_specs
  GET  /api/copilot/agent/actions/list_governance_rules
  GET  /api/copilot/agent/actions/get_route/{route_id}
"""

from __future__ import annotations

import json

import pytest
import yaml
from fastapi.testclient import TestClient

from spec2sphere.web.server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def output_dir(tmp_path):
    """Minimal output directory so create_app succeeds."""
    graph = {
        "nodes": [{"id": "SPACE.OBJ1", "name": "OBJ1", "type": "view", "layer": "harmonized", "source_system": "DSP"}],
        "edges": [],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    obj_dir = tmp_path / "objects" / "view"
    obj_dir.mkdir(parents=True)
    (obj_dir / "SPACE.OBJ1.md").write_text("---\nobject_id: SPACE.OBJ1\nname: OBJ1\n---\n# OBJ1\nA test view.")
    (tmp_path / "reports").mkdir()
    return tmp_path


@pytest.fixture
def client(output_dir):
    app = create_app(output_dir=str(output_dir))
    return TestClient(app)


# ---------------------------------------------------------------------------
# manifest.yaml
# ---------------------------------------------------------------------------


def test_manifest_yaml_returns_200(client):
    resp = client.get("/api/copilot/agent/manifest.yaml")
    assert resp.status_code == 200


def test_manifest_yaml_content_type(client):
    resp = client.get("/api/copilot/agent/manifest.yaml")
    ct = resp.headers.get("content-type", "")
    assert "yaml" in ct or "text" in ct  # application/yaml or text/plain both acceptable


def test_manifest_yaml_parseable(client):
    resp = client.get("/api/copilot/agent/manifest.yaml")
    manifest = yaml.safe_load(resp.text)
    assert isinstance(manifest, dict)


def test_manifest_yaml_required_fields(client):
    resp = client.get("/api/copilot/agent/manifest.yaml")
    manifest = yaml.safe_load(resp.text)

    assert "schema_version" in manifest
    assert "name_for_human" in manifest
    assert "name_for_model" in manifest
    assert "description_for_human" in manifest
    assert "description_for_model" in manifest
    assert "api" in manifest
    assert "auth" in manifest
    assert "capabilities" in manifest


def test_manifest_name_is_spec2sphere(client):
    resp = client.get("/api/copilot/agent/manifest.yaml")
    manifest = yaml.safe_load(resp.text)
    assert manifest["name_for_human"] == "Spec2Sphere"
    assert manifest["name_for_model"] == "spec2sphere"


def test_manifest_capabilities_have_expected_actions(client):
    resp = client.get("/api/copilot/agent/manifest.yaml")
    manifest = yaml.safe_load(resp.text)
    capability_names = {c["name"] for c in manifest["capabilities"]}
    assert "search_specs" in capability_names
    assert "list_governance_rules" in capability_names
    assert "get_route" in capability_names


def test_manifest_api_points_to_openapi(client):
    resp = client.get("/api/copilot/agent/manifest.yaml")
    manifest = yaml.safe_load(resp.text)
    assert manifest["api"]["type"] == "openapi"
    assert "openapi.yaml" in manifest["api"]["url"]


# ---------------------------------------------------------------------------
# openapi.yaml
# ---------------------------------------------------------------------------


def test_openapi_yaml_returns_200(client):
    resp = client.get("/api/copilot/agent/openapi.yaml")
    assert resp.status_code == 200


def test_openapi_yaml_parseable(client):
    resp = client.get("/api/copilot/agent/openapi.yaml")
    spec = yaml.safe_load(resp.text)
    assert isinstance(spec, dict)


def test_openapi_yaml_has_openapi_field(client):
    resp = client.get("/api/copilot/agent/openapi.yaml")
    spec = yaml.safe_load(resp.text)
    assert "openapi" in spec
    assert spec["openapi"].startswith("3.")


def test_openapi_yaml_has_paths(client):
    resp = client.get("/api/copilot/agent/openapi.yaml")
    spec = yaml.safe_load(resp.text)
    assert "paths" in spec
    paths = spec["paths"]
    # All three action endpoints must be declared
    assert any("search_specs" in p for p in paths)
    assert any("list_governance_rules" in p for p in paths)
    assert any("get_route" in p for p in paths)


def test_openapi_yaml_search_specs_has_post(client):
    resp = client.get("/api/copilot/agent/openapi.yaml")
    spec = yaml.safe_load(resp.text)
    search_path = next(p for p in spec["paths"] if "search_specs" in p)
    assert "post" in spec["paths"][search_path]
    op = spec["paths"][search_path]["post"]
    assert op["operationId"] == "search_specs"
    # Must declare requestBody with query property
    schema = op["requestBody"]["content"]["application/json"]["schema"]
    assert "query" in schema["properties"]
    assert "query" in schema.get("required", [])


def test_openapi_yaml_get_route_has_path_param(client):
    resp = client.get("/api/copilot/agent/openapi.yaml")
    spec = yaml.safe_load(resp.text)
    route_path = next(p for p in spec["paths"] if "get_route" in p)
    op = spec["paths"][route_path]["get"]
    assert op["operationId"] == "get_route"
    param_names = [p["name"] for p in op.get("parameters", [])]
    assert "route_id" in param_names


# ---------------------------------------------------------------------------
# POST /api/copilot/agent/actions/search_specs
# ---------------------------------------------------------------------------


def test_search_specs_happy_path(client):
    resp = client.post("/api/copilot/agent/actions/search_specs", json={"query": "architecture"})
    assert resp.status_code == 200
    data = resp.json()
    assert "query" in data
    assert data["query"] == "architecture"
    assert "count" in data
    assert "results" in data
    assert isinstance(data["results"], list)
    assert data["count"] >= 1


def test_search_specs_result_shape(client):
    resp = client.post("/api/copilot/agent/actions/search_specs", json={"query": "layer"})
    assert resp.status_code == 200
    data = resp.json()
    if data["count"] > 0:
        result = data["results"][0]
        assert "section_id" in result
        assert "page_id" in result
        assert "title" in result
        assert "snippet" in result
        assert "url" in result


def test_search_specs_with_section_filter(client):
    resp = client.post(
        "/api/copilot/agent/actions/search_specs",
        json={"query": "layer", "section": "architecture"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("section") == "architecture"
    for r in data["results"]:
        assert r["section_id"] == "architecture"


def test_search_specs_empty_query_returns_zero(client):
    resp = client.post("/api/copilot/agent/actions/search_specs", json={"query": ""})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["results"] == []


def test_search_specs_no_results(client):
    resp = client.post(
        "/api/copilot/agent/actions/search_specs",
        json={"query": "xyznonexistentterm999abc"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0


# ---------------------------------------------------------------------------
# GET /api/copilot/agent/actions/list_governance_rules
# ---------------------------------------------------------------------------


def test_list_governance_rules_returns_200(client):
    resp = client.get("/api/copilot/agent/actions/list_governance_rules")
    assert resp.status_code == 200


def test_list_governance_rules_has_sections(client):
    resp = client.get("/api/copilot/agent/actions/list_governance_rules")
    data = resp.json()
    assert "sections" in data
    assert isinstance(data["sections"], list)


def test_list_governance_rules_standards_present(client):
    resp = client.get("/api/copilot/agent/actions/list_governance_rules")
    data = resp.json()
    section_ids = {s["section_id"] for s in data["sections"]}
    # standards and/or quality sections should be present
    assert section_ids & {"standards", "quality"}


def test_list_governance_rules_page_shape(client):
    resp = client.get("/api/copilot/agent/actions/list_governance_rules")
    data = resp.json()
    for section in data["sections"]:
        assert "section_id" in section
        assert "section_title" in section
        assert "pages" in section
        for page in section["pages"]:
            assert "id" in page
            assert "title" in page
            assert "url" in page


# ---------------------------------------------------------------------------
# GET /api/copilot/agent/actions/get_route/{route_id}
# ---------------------------------------------------------------------------


def test_get_route_architecture_overview(client):
    resp = client.get("/api/copilot/agent/actions/get_route/architecture__overview")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "overview"
    assert data["section_id"] == "architecture"
    assert "content_md" in data
    assert len(data["content_md"]) > 0
    assert "layer" in data["content_md"].lower()


def test_get_route_migration_page(client):
    resp = client.get("/api/copilot/agent/actions/get_route/migration__bw-to-datasphere")
    assert resp.status_code == 200
    data = resp.json()
    assert data["section_id"] == "migration"


def test_get_route_not_found_returns_404(client):
    resp = client.get("/api/copilot/agent/actions/get_route/architecture__nonexistent-page-xyz")
    assert resp.status_code == 404


def test_get_route_bad_format_returns_400(client):
    """route_id without __ separator should return 400."""
    resp = client.get("/api/copilot/agent/actions/get_route/architectureoverview")
    assert resp.status_code == 400


def test_get_route_response_has_url(client):
    resp = client.get("/api/copilot/agent/actions/get_route/architecture__overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "url" in data
    assert "/copilot/" in data["url"]
