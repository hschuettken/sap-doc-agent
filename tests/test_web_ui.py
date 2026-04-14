import json
import os

import pytest
from fastapi.testclient import TestClient

from sap_doc_agent.web.server import create_app


@pytest.fixture
def output_dir(tmp_path):
    """Create output dir with test data."""
    graph = {
        "nodes": [
            {"id": "SP.V1", "name": "View 1", "type": "view", "layer": "harmonized", "source_system": "DSP"},
            {"id": "SP.T1", "name": "Table 1", "type": "table", "layer": "raw", "source_system": "DSP"},
        ],
        "edges": [{"source": "SP.V1", "target": "SP.T1", "type": "reads_from"}],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    view_dir = tmp_path / "objects" / "view"
    view_dir.mkdir(parents=True)
    (view_dir / "SP.V1.md").write_text("---\nobject_id: SP.V1\nname: View 1\n---\n# View 1\nTest view.")
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    (reports_dir / "summary.md").write_text("# Summary\nScore: 75%")
    return tmp_path


@pytest.fixture
def client(output_dir):
    # Use a hash that won't match any password so UI routes require auth
    os.environ["SAP_DOC_AGENT_UI_PASSWORD_HASH"] = "$2b$12$LJ3m5ZQmQz8I2Q7Q7Q7Q7O7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q"
    os.environ["SAP_DOC_AGENT_SECRET_KEY"] = "test-secret"
    app = create_app(output_dir=str(output_dir))
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def authed_client(output_dir):
    """Client with a valid session cookie obtained via login."""
    from sap_doc_agent.web.auth import hash_password

    pw_hash = hash_password("testpass")
    os.environ["SAP_DOC_AGENT_UI_PASSWORD_HASH"] = pw_hash
    os.environ["SAP_DOC_AGENT_SECRET_KEY"] = "test-secret"
    app = create_app(output_dir=str(output_dir))
    c = TestClient(app, follow_redirects=True)
    # Login to get session cookie
    c.post("/ui/login", data={"password": "testpass"}, follow_redirects=False)
    return c


def test_root_redirects_browser(client):
    resp = client.get("/", headers={"Accept": "text/html"})
    assert resp.status_code == 307
    assert "/ui/dashboard" in resp.headers["location"]


def test_root_returns_json_for_api(output_dir):
    """Root returns JSON when Accept header is application/json."""
    os.environ["SAP_DOC_AGENT_UI_PASSWORD_HASH"] = "$2b$12$LJ3m5ZQmQz8I2Q7Q7Q7Q7O7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q"
    os.environ["SAP_DOC_AGENT_SECRET_KEY"] = "test-secret"
    app = create_app(output_dir=str(output_dir))
    c = TestClient(app, follow_redirects=False)
    resp = c.get("/", headers={"Accept": "application/json"})
    assert resp.status_code == 200
    assert resp.json()["service"] == "SAP Doc Agent"


def test_dashboard_requires_auth(client):
    resp = client.get("/ui/dashboard")
    assert resp.status_code == 307
    assert "/ui/login" in resp.headers["location"]


def test_dashboard_renders(authed_client):
    resp = authed_client.get("/ui/dashboard")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text or "dashboard" in resp.text.lower()


def test_objects_page(authed_client):
    resp = authed_client.get("/ui/objects")
    assert resp.status_code == 200
    assert "View 1" in resp.text


def test_objects_filter(authed_client):
    resp = authed_client.get("/ui/objects?type=view")
    assert resp.status_code == 200
    assert "View 1" in resp.text


def test_graph_page(authed_client):
    resp = authed_client.get("/ui/graph")
    assert resp.status_code == 200


def test_api_still_works_without_auth(output_dir):
    """API endpoints bypass auth entirely."""
    os.environ["SAP_DOC_AGENT_UI_PASSWORD_HASH"] = "$2b$12$LJ3m5ZQmQz8I2Q7Q7Q7Q7O7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q7Q"
    os.environ["SAP_DOC_AGENT_SECRET_KEY"] = "test-secret"
    app = create_app(output_dir=str(output_dir))
    c = TestClient(app, follow_redirects=False)
    resp = c.get("/api/objects")
    assert resp.status_code == 200
    assert resp.json()["count"] == 2


def test_health_dots(authed_client):
    resp = authed_client.get("/ui/partials/health-dots")
    assert resp.status_code == 200
    assert "obj" in resp.text
