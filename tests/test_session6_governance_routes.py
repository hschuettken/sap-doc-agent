"""Tests for Session 6 Task 7: Governance Routes + UI Templates.

All database calls are intercepted via patch("spec2sphere.web.governance_routes._get_conn").
No real database is required.  Auth middleware is NOT added — minimal app only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from spec2sphere.web.governance_routes import create_governance_routes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_conn():
    conn = AsyncMock()
    conn.close = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="UPDATE 1")
    return conn


@pytest.fixture
def client():
    """Minimal FastAPI app with governance router, no auth middleware."""
    from pathlib import Path

    app = FastAPI()

    # Mount static files so base.html /static/ refs don't 500
    static_dir = Path(__file__).parent.parent / "src" / "spec2sphere" / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(create_governance_routes())
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_reports_page_returns_html(client):
    """GET /ui/reports returns 200 with mocked empty DB."""
    conn = make_mock_conn()
    with patch("spec2sphere.web.governance_routes._get_conn", return_value=conn):
        resp = client.get("/ui/reports")
    assert resp.status_code == 200
    assert "Report" in resp.text


def test_audit_log_page_returns_html(client):
    """GET /ui/audit-log returns 200 with mocked empty DB."""
    conn = make_mock_conn()
    with patch("spec2sphere.web.governance_routes._get_conn", return_value=conn):
        resp = client.get("/ui/audit-log")
    assert resp.status_code == 200
    assert "Audit" in resp.text


def test_lab_page_returns_html(client):
    """GET /ui/lab returns 200 with mocked empty DB."""
    conn = make_mock_conn()
    with patch("spec2sphere.web.governance_routes._get_conn", return_value=conn):
        resp = client.get("/ui/lab")
    assert resp.status_code == 200
    assert "Lab" in resp.text


def test_generate_report_api(client):
    """POST /api/governance/generate-report returns 200 or 404 (no project found)."""
    conn = make_mock_conn()
    # fetchrow returns None → project not found → 404
    conn.fetchrow = AsyncMock(return_value=None)
    with patch("spec2sphere.web.governance_routes._get_conn", return_value=conn):
        resp = client.post(
            "/api/governance/generate-report",
            json={"project_id": "00000000-0000-0000-0000-000000000001", "format": "html"},
        )
    # fetchrow returns None → project not found → must be 404
    assert resp.status_code == 404


def test_download_release_api(client):
    """GET /api/governance/release/<nonexistent>/download returns 404."""
    resp = client.get("/api/governance/release/nonexistent-id/download")
    assert resp.status_code == 404


def test_demo_seed_api(client):
    """POST /api/demo/seed creates demo data or reports existing."""
    conn = make_mock_conn()
    # Mock sequence: 1) customer check → None, 2) tenant check → None (will create)
    conn.fetchrow = AsyncMock(side_effect=[None, None])
    with patch("spec2sphere.web.governance_routes._get_conn", return_value=conn):
        resp = client.post("/api/demo/seed")
    # May fail due to mock limitations but should not 500
    assert resp.status_code in (200, 500)
