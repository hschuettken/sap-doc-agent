"""RBAC enforcement at the live adapter edge."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from spec2sphere.dsp_ai.auth import issue_token
from spec2sphere.dsp_ai.service import create_app


@pytest.fixture
def client():
    # Fresh app with default (non-enforced) auth
    os.environ.setdefault("DSPAI_JWT_SECRET", "test-secret")
    os.environ["DSPAI_JWT_SECRET"] = "test-secret"
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def author_token():
    os.environ["DSPAI_JWT_SECRET"] = "test-secret"
    return issue_token("author@example.com", "default", "author")


@pytest.fixture
def viewer_token():
    os.environ["DSPAI_JWT_SECRET"] = "test-secret"
    return issue_token("viewer@example.com", "default", "viewer")


@pytest.fixture
def widget_token():
    os.environ["DSPAI_JWT_SECRET"] = "test-secret"
    return issue_token("widget", "default", "widget")


def test_viewer_cannot_force_regen(client, viewer_token):
    fake_id = "00000000-0000-0000-0000-000000000000"
    r = client.post(
        f"/v1/actions/{fake_id}/regen",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"user": "viewer@example.com", "context_hints": {}},
    )
    assert r.status_code == 403, r.text
    assert "author" in r.json().get("detail", "").lower()


def test_widget_cannot_force_regen(client, widget_token):
    fake_id = "00000000-0000-0000-0000-000000000000"
    r = client.post(
        f"/v1/actions/{fake_id}/regen",
        headers={"Authorization": f"Bearer {widget_token}"},
        json={},
    )
    assert r.status_code == 403


def test_author_regen_reaches_engine(client, author_token):
    """Author gets past RBAC and hits the engine; with a bogus id we expect 404, not 403."""
    fake_id = "00000000-0000-0000-0000-000000000000"
    r = client.post(
        f"/v1/actions/{fake_id}/regen",
        headers={"Authorization": f"Bearer {author_token}"},
        json={"user": "author@example.com", "context_hints": {}},
    )
    # Success path requires a real engine + seeded data; in isolated unit test expect 404
    # or 500 if engine can't connect to DB. Either way, NOT 403.
    assert r.status_code != 403, r.text


def test_missing_token_when_not_enforced_allows_enhance(client, monkeypatch):
    """With DSPAI_AUTH_ENFORCED unset (default false), /v1/enhance works without a token."""
    monkeypatch.setenv("DSPAI_AUTH_ENFORCED", "false")
    fake_id = "00000000-0000-0000-0000-000000000000"
    r = client.post(f"/v1/enhance/{fake_id}", json={"user": "anon"})
    assert r.status_code != 401, r.text  # 200 or 404 or 500 (no DB), not auth error


def test_missing_token_when_enforced_rejects_enhance(monkeypatch):
    """With DSPAI_AUTH_ENFORCED=true, missing token → 401."""
    monkeypatch.setenv("DSPAI_AUTH_ENFORCED", "true")
    os.environ["DSPAI_JWT_SECRET"] = "test-secret"
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        fake_id = "00000000-0000-0000-0000-000000000000"
        r = c.post(f"/v1/enhance/{fake_id}", json={"user": "anon"})
        assert r.status_code == 401, r.text


def test_invalid_token_rejected(client):
    fake_id = "00000000-0000-0000-0000-000000000000"
    r = client.post(
        f"/v1/actions/{fake_id}/regen",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={},
    )
    assert r.status_code == 401, r.text
