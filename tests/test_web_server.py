import pytest
import json
from fastapi.testclient import TestClient
from sap_doc_agent.web.server import create_app


@pytest.fixture
def output_dir(tmp_path):
    """Create a minimal output directory with test data."""
    # Create graph.json
    graph = {
        "nodes": [
            {"id": "SPACE.OBJ1", "name": "OBJ1", "type": "view", "layer": "harmonized", "source_system": "DSP"},
            {"id": "SPACE.OBJ2", "name": "OBJ2", "type": "table", "layer": "raw", "source_system": "DSP"},
        ],
        "edges": [
            {"source": "SPACE.OBJ1", "target": "SPACE.OBJ2", "type": "reads_from"},
        ],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))

    # Create object markdown files
    view_dir = tmp_path / "objects" / "view"
    view_dir.mkdir(parents=True)
    (view_dir / "SPACE.OBJ1.md").write_text("---\nobject_id: SPACE.OBJ1\nname: OBJ1\n---\n# OBJ1\nA test view.")

    table_dir = tmp_path / "objects" / "table"
    table_dir.mkdir(parents=True)
    (table_dir / "SPACE.OBJ2.md").write_text("---\nobject_id: SPACE.OBJ2\nname: OBJ2\n---\n# OBJ2\nA test table.")

    # Create reports
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "summary.md").write_text("# Quality Summary\nScore: 75%")

    return tmp_path


@pytest.fixture
def client(output_dir):
    app = create_app(output_dir=str(output_dir))
    return TestClient(app)


def test_landing_page(client):
    # Root returns JSON for programmatic/API access (no text/html Accept header).
    # Browsers are redirected to /ui/dashboard.
    resp = client.get("/", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["service"] == "SAP Doc Agent"
    assert data["ui"] == "/ui/dashboard"


def test_serve_object(client):
    resp = client.get("/docs/objects/view/SPACE.OBJ1")
    assert resp.status_code == 200
    assert "OBJ1" in resp.text


def test_serve_object_not_found(client):
    resp = client.get("/docs/objects/view/NONEXISTENT")
    assert resp.status_code == 404


def test_serve_report(client):
    resp = client.get("/reports/summary.md")
    assert resp.status_code == 200
    assert "Quality Summary" in resp.text


def test_sitemap(client):
    resp = client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "urlset" in resp.text
    assert "SPACE.OBJ1" in resp.text


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["objects"] == 2


def test_api_list_objects(client):
    resp = client.get("/api/objects")
    data = resp.json()
    assert data["count"] == 2
    ids = [o["id"] for o in data["objects"]]
    assert "SPACE.OBJ1" in ids


def test_api_get_object(client):
    resp = client.get("/api/objects/SPACE.OBJ1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object_id"] == "SPACE.OBJ1"


def test_api_search(client):
    resp = client.get("/api/search?q=test+view")
    data = resp.json()
    assert data["count"] >= 1
    assert data["results"][0]["object_id"] == "SPACE.OBJ1"


def test_api_quality(client):
    resp = client.get("/api/quality")
    data = resp.json()
    assert data["status"] == "ok"
    assert "75%" in data["summary"]


def test_api_dependencies(client):
    resp = client.get("/api/dependencies/SPACE.OBJ1")
    data = resp.json()
    assert len(data["downstream"]) == 1
    assert data["downstream"][0]["target"] == "SPACE.OBJ2"


def test_api_audit(client):
    resp = client.post(
        "/api/audit",
        json={
            "documents": [{"title": "Sales Doc", "content": "## Business Objective\nMonthly revenue reporting."}],
            "application_name": "Sales",
        },
    )
    data = resp.json()
    assert "score" in data or "horvath_score" in data
    assert "issues" in data or "horvath_issues" in data


def test_openapi_spec(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    assert spec["info"]["title"] == "SAP Doc Agent API"
    paths = spec["paths"]
    assert "/api/audit" in paths
    assert "/api/objects" in paths
    assert "/api/search" in paths


def test_api_dashboard_stats(client):
    resp = client.get("/api/dashboard/stats")
    data = resp.json()
    assert data["object_count"] == 2
    assert "view" in data["type_counts"]


def test_api_scanner_status(client):
    resp = client.get("/api/scanner/status")
    data = resp.json()
    assert len(data["scanners"]) == 3


def test_api_start_scan(client):
    resp = client.post("/api/scanner/start", json={"scanner": "cdp"})
    data = resp.json()
    assert data["status"] == "started"


def test_api_validate_settings_invalid(client):
    resp = client.post("/api/settings/validate", json={"yaml_content": "invalid: {not: valid"})
    data = resp.json()
    assert data["valid"] is False
