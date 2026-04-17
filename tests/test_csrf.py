"""Tests for CSRF double-submit protection."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from spec2sphere.web.csrf import CSRFMiddleware, CSRF_COOKIE, CSRF_HEADER


@pytest.fixture
def csrf_app():
    app = FastAPI()

    @app.get("/api/items")
    async def list_items():
        return {"items": []}

    @app.post("/api/items")
    async def create_item():
        return {"ok": True}

    @app.post("/ui/login")
    async def login():
        return {"ok": True}

    @app.post("/mcp/messages")
    async def mcp_msg():
        return {"ok": True}

    @app.post("/api/ingest/upload")
    async def ingest():
        return {"ok": True}

    app.add_middleware(CSRFMiddleware)
    return app


def test_get_request_sets_csrf_cookie(csrf_app):
    client = TestClient(csrf_app)
    resp = client.get("/api/items")
    assert resp.status_code == 200
    assert CSRF_COOKIE in resp.cookies


def test_post_without_token_rejected(csrf_app):
    """With a session cookie, a mutating POST without CSRF header is rejected."""
    client = TestClient(csrf_app)
    client.cookies.set("session", "fake-session-value")
    resp = client.post("/api/items")
    assert resp.status_code == 403
    assert "CSRF" in resp.json()["detail"]


def test_post_with_matching_token_accepted(csrf_app):
    client = TestClient(csrf_app)
    # Bootstrap cookie via GET
    client.get("/api/items")
    token = client.cookies.get(CSRF_COOKIE)
    assert token
    client.cookies.set("session", "fake-session-value")
    resp = client.post("/api/items", headers={CSRF_HEADER: token})
    assert resp.status_code == 200


def test_post_with_mismatched_token_rejected(csrf_app):
    client = TestClient(csrf_app)
    client.get("/api/items")
    client.cookies.set("session", "fake-session-value")
    resp = client.post("/api/items", headers={CSRF_HEADER: "wrong-token"})
    assert resp.status_code == 403


def test_post_without_session_cookie_skipped(csrf_app):
    """Without a session cookie, CSRF doesn't apply — there's no session to steal."""
    client = TestClient(csrf_app)
    resp = client.post("/api/items")
    assert resp.status_code == 200


def test_bearer_auth_skipped(csrf_app):
    client = TestClient(csrf_app)
    # Bearer-authenticated requests bypass CSRF (they're agent calls, not sessions)
    resp = client.post("/api/items", headers={"Authorization": "Bearer abc123"})
    assert resp.status_code == 200


def test_login_post_skipped(csrf_app):
    client = TestClient(csrf_app)
    resp = client.post("/ui/login")
    assert resp.status_code == 200


def test_mcp_path_skipped(csrf_app):
    client = TestClient(csrf_app)
    resp = client.post("/mcp/messages")
    assert resp.status_code == 200


def test_safe_methods_not_checked(csrf_app):
    client = TestClient(csrf_app)
    # GET needs no token even with no cookie
    resp = client.get("/api/items")
    assert resp.status_code == 200
    # OPTIONS also bypasses (but may 405 depending on ASGI); ensure it's never 403
    resp2 = client.options("/api/items")
    assert resp2.status_code != 403
