"""Tests for migration API and UI routes."""

import json

from fastapi.testclient import TestClient


def _get_client(output_dir="tests/fixtures/sample_bw_scan"):
    import os

    from sap_doc_agent.web.auth import hash_password
    from sap_doc_agent.web.server import create_app

    pw_hash = hash_password("testpass")
    os.environ["SAP_DOC_AGENT_UI_PASSWORD_HASH"] = pw_hash
    os.environ["SAP_DOC_AGENT_SECRET_KEY"] = "test-secret"
    app = create_app(output_dir=output_dir)
    client = TestClient(app, follow_redirects=True)
    client.post("/ui/login", data={"password": "testpass"}, follow_redirects=False)
    return client


# --- API route tests ---


def test_api_migration_projects_list():
    client = _get_client()
    resp = client.get("/api/migration/projects")
    # May return empty list (no DB) or 200
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_migration_intent_cards_empty():
    client = _get_client()
    resp = client.get("/api/migration/projects/fake-id/intent-cards")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_migration_classifications_empty():
    client = _get_client()
    resp = client.get("/api/migration/projects/fake-id/classifications")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_migration_intent_cards_reads_files(tmp_path):
    """Intent cards endpoint falls back to reading _intent.json files."""
    chains_dir = tmp_path / "chains"
    chains_dir.mkdir()
    intent = {
        "chain_id": "chain_001",
        "business_purpose": "Revenue reporting",
        "data_domain": "SD",
        "confidence": 0.8,
    }
    (chains_dir / "chain_001_intent.json").write_text(json.dumps(intent))

    client = _get_client(output_dir=str(tmp_path))
    resp = client.get("/api/migration/projects/fake-id/intent-cards")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["chain_id"] == "chain_001"


def test_api_migration_classifications_reads_files(tmp_path):
    """Classifications endpoint falls back to reading _classified.json files."""
    chains_dir = tmp_path / "chains"
    chains_dir.mkdir()
    classified = {
        "chain_id": "chain_001",
        "classification": "simplify",
        "rationale": "TCURR pattern",
        "confidence": 0.85,
    }
    (chains_dir / "chain_001_classified.json").write_text(json.dumps(classified))

    client = _get_client(output_dir=str(tmp_path))
    resp = client.get("/api/migration/projects/fake-id/classifications")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["classification"] == "simplify"


# --- UI route tests ---


def test_ui_migration_projects_page():
    client = _get_client()
    resp = client.get("/ui/migration/projects")
    assert resp.status_code == 200
    assert "Migration Projects" in resp.text


def test_ui_migration_intent_page():
    client = _get_client()
    resp = client.get("/ui/migration/intent")
    assert resp.status_code == 200
    assert "Intent Cards" in resp.text


def test_ui_migration_classify_page():
    client = _get_client()
    resp = client.get("/ui/migration/classify")
    assert resp.status_code == 200
    assert "Classifications" in resp.text


def test_review_request_rejects_invalid_decision():
    """ReviewRequest should only accept approve/reject/clarify."""
    from pydantic import ValidationError

    from sap_doc_agent.web.migration_routes import ReviewRequest

    # Valid decisions work
    ReviewRequest(decision="approve", reviewer="test")
    ReviewRequest(decision="reject", notes="wrong")
    ReviewRequest(decision="clarify")

    # Invalid decision raises
    try:
        ReviewRequest(decision="invalid_value")
        assert False, "Should have raised ValidationError"
    except ValidationError:
        pass


# --- Router registration ---


def test_migration_routes_registered():
    from sap_doc_agent.web.server import create_app

    app = create_app()
    route_paths = [r.path for r in app.routes]
    assert "/api/migration/projects" in route_paths or any("/api/migration" in str(r.path) for r in app.routes)
