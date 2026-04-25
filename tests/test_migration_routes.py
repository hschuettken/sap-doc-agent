"""Tests for migration API and UI routes."""

import json

from fastapi.testclient import TestClient


def _get_client(output_dir="tests/fixtures/sample_bw_scan"):
    import os

    from spec2sphere.web.auth import hash_password
    from spec2sphere.web.server import create_app

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

    from spec2sphere.web.migration_routes import ReviewRequest

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


# --- BRS Reconciliation routes (Phase 4) ---


def test_api_brs_deltas_empty_no_chains():
    """GET /brs-deltas returns empty list when no brs_recon files exist."""
    client = _get_client()
    resp = client.get("/api/migration/projects/fake-id/brs-deltas")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_api_brs_deltas_reads_recon_files(tmp_path):
    """brs-deltas endpoint falls back to reading *_brs_recon.json files."""
    chains_dir = tmp_path / "chains"
    chains_dir.mkdir()
    recon = [
        {
            "chain_id": "chain_001",
            "brs_document": "BRS_Revenue.md",
            "brs_says": "Revenue for DE",
            "bw_does": "Revenue for DE, AT, CH",
            "deltas": [{"delta_type": "scope_creep", "notes": "Added in CR-2019"}],
            "confidence": 0.85,
        }
    ]
    (chains_dir / "chain_001_brs_recon.json").write_text(json.dumps(recon))

    client = _get_client(output_dir=str(tmp_path))
    resp = client.get("/api/migration/projects/fake-id/brs-deltas")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["chain_id"] == "chain_001"
    assert data[0]["brs_document"] == "BRS_Revenue.md"


def test_api_reconcile_returns_404_for_missing_project():
    """POST /reconcile returns 404 when project_id is not in DB."""
    client = _get_client()
    resp = client.post("/api/migration/projects/nonexistent-project-id/reconcile")
    # 404 or 400 (no DB) — both are acceptable non-500
    assert resp.status_code in (400, 404, 422)


def test_ui_migration_reconcile_page():
    """UI reconcile page renders without error."""
    client = _get_client()
    resp = client.get("/ui/migration/reconcile")
    assert resp.status_code == 200
    assert "BRS Reconciliation" in resp.text


def test_ui_migration_reconcile_page_with_project_id():
    """UI reconcile page with project_id renders without error."""
    client = _get_client()
    resp = client.get("/ui/migration/reconcile?project_id=some-id")
    assert resp.status_code == 200
    assert "BRS Reconciliation" in resp.text


# --- Router registration ---


def test_migration_routes_registered():
    from spec2sphere.web.server import create_app

    app = create_app()
    route_paths = [r.path for r in app.routes]
    assert "/api/migration/projects" in route_paths or any("/api/migration" in str(r.path) for r in app.routes)


def test_reconcile_and_brs_delta_routes_registered():
    """Verify Phase 4 reconcile endpoints are registered."""
    from spec2sphere.web.server import create_app

    app = create_app()
    paths = [str(r.path) for r in app.routes]
    assert any("/reconcile" in p for p in paths), "POST /reconcile endpoint not registered"
    assert any("/brs-deltas" in p for p in paths), "GET /brs-deltas endpoint not registered"
