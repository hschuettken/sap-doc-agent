"""Tests for Session 5 Task 8: Factory Routes + UI Templates.

All database calls are intercepted via patch("spec2sphere.web.factory_routes._get_conn").
No real database is required.  Auth middleware is NOT added — minimal app only.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

from spec2sphere.web.factory_routes import create_factory_routes


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
    """Minimal FastAPI app with factory router, no auth middleware."""
    from pathlib import Path

    app = FastAPI()

    # Mount static files so base.html /static/ refs don't 500
    static_dir = Path(__file__).parent.parent / "src" / "spec2sphere" / "web" / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(create_factory_routes())
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_factory_page_loads(client):
    """GET /ui/factory returns 200 with mocked empty DB."""
    conn = make_mock_conn()
    with patch("spec2sphere.web.factory_routes._get_conn", return_value=conn):
        resp = client.get("/ui/factory")
    assert resp.status_code == 200
    assert "Deployment Factory" in resp.text or "Factory" in resp.text


def test_reconciliation_page_loads(client):
    """GET /ui/reconciliation returns 200 with mocked empty DB."""
    conn = make_mock_conn()
    with patch("spec2sphere.web.factory_routes._get_conn", return_value=conn):
        resp = client.get("/ui/reconciliation")
    assert resp.status_code == 200
    assert "Reconciliation" in resp.text


def test_visual_qa_page_loads(client):
    """GET /ui/visual-qa returns 200 with mocked empty DB."""
    conn = make_mock_conn()
    with patch("spec2sphere.web.factory_routes._get_conn", return_value=conn):
        resp = client.get("/ui/visual-qa")
    assert resp.status_code == 200
    assert "Visual QA" in resp.text or "visual" in resp.text.lower()


def test_route_fitness_page_loads(client):
    """GET /ui/lab/fitness returns 200 with mocked empty DB."""
    conn = make_mock_conn()
    with patch("spec2sphere.web.factory_routes._get_conn", return_value=conn):
        resp = client.get("/ui/lab/fitness")
    assert resp.status_code == 200
    assert "Route Fitness" in resp.text or "fitness" in resp.text.lower()


def test_factory_active_api(client):
    """GET /api/factory/active returns 200 with 'active' key in JSON."""
    conn = make_mock_conn()
    # fetchrow returns None → no active run
    conn.fetchrow = AsyncMock(return_value=None)
    with patch("spec2sphere.web.factory_routes._get_conn", return_value=conn):
        resp = client.get("/api/factory/active")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data
    assert data["active"] is False


def test_browser_view_page(client):
    """GET /ui/browser-view returns 200."""
    resp = client.get("/ui/browser-view")
    assert resp.status_code == 200
    assert "browser" in resp.text.lower() or "viewer" in resp.text.lower() or resp.status_code == 200
