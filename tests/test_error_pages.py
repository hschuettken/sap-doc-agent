"""Tests for branded 404/500 error pages."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_errors(tmp_path, monkeypatch):
    monkeypatch.setenv("SAP_DOC_AGENT_UI_PASSWORD_HASH", "dummy")
    monkeypatch.setenv("SAP_DOC_AGENT_SECRET_KEY", "test-secret")
    from spec2sphere.web.server import create_app

    return create_app(output_dir=str(tmp_path))


def test_404_html_accept_renders_branded_page(app_with_errors):
    client = TestClient(app_with_errors)
    resp = client.get("/ui/does-not-exist", headers={"Accept": "text/html"}, follow_redirects=False)
    # Unauthenticated /ui/* redirects to login; but an authenticated-style path that doesn't
    # exist should 404. Easier: use a non-/ui path that doesn't exist.
    resp = client.get("/api/nope-does-not-exist", headers={"Accept": "text/html"})
    assert resp.status_code == 404
    assert "Page not found" in resp.text
    assert "/api/nope-does-not-exist" in resp.text


def test_404_json_accept_returns_json(app_with_errors):
    client = TestClient(app_with_errors)
    resp = client.get("/api/nope-does-not-exist", headers={"Accept": "application/json"})
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Not Found"}


def test_500_html_for_unhandled_exception(app_with_errors):
    # Register a route that blows up
    @app_with_errors.get("/api/_boom_test")
    async def _boom():
        raise RuntimeError("kaboom")

    client = TestClient(app_with_errors, raise_server_exceptions=False)
    resp = client.get("/api/_boom_test", headers={"Accept": "text/html"})
    assert resp.status_code == 500
    assert "Something went wrong" in resp.text


def test_500_json_for_unhandled_exception(app_with_errors):
    @app_with_errors.get("/api/_boom_test2")
    async def _boom():
        raise RuntimeError("kaboom-json")

    client = TestClient(app_with_errors, raise_server_exceptions=False)
    resp = client.get("/api/_boom_test2", headers={"Accept": "application/json"})
    assert resp.status_code == 500
    body = resp.json()
    assert body["detail"] == "Internal server error"
