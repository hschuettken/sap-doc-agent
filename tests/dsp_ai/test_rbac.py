"""RBAC unit tests — auth.py token issuance and scope enforcement."""

from __future__ import annotations

import time

import pytest

from spec2sphere.dsp_ai.auth import (
    Principal,
    _JWT_SECRET,
    _JWT_ALGO,
    issue_token,
    require,
    require_author,
)
import jwt
from fastapi import HTTPException


def _fake_require(role: str) -> Principal:
    """Simulate the FastAPI dependency by calling _decode directly."""
    token = issue_token("u@example.com", "horvath", role)
    # Mimic what require() does minus the FastAPI Header injection
    data = jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    return Principal(**data)


class TestIssueToken:
    def test_valid_author_token_roundtrips(self):
        tok = issue_token("alice@example.com", "horvath", "author")
        data = jwt.decode(tok, _JWT_SECRET, algorithms=[_JWT_ALGO])
        assert data["user_id"] == "alice@example.com"
        assert data["customer"] == "horvath"
        assert data["role"] == "author"
        assert data["exp"] > int(time.time())

    def test_valid_viewer_token(self):
        tok = issue_token("bob@example.com", "horvath", "viewer")
        data = jwt.decode(tok, _JWT_SECRET, algorithms=[_JWT_ALGO])
        assert data["role"] == "viewer"

    def test_valid_widget_token(self):
        tok = issue_token("widget", "horvath", "widget")
        data = jwt.decode(tok, _JWT_SECRET, algorithms=[_JWT_ALGO])
        assert data["role"] == "widget"

    def test_unknown_role_rejected(self):
        with pytest.raises(ValueError, match="unknown role"):
            issue_token("u@x", "c", "admin")

    def test_ttl_respected(self):
        tok = issue_token("u@x", "c", "viewer", ttl_s=1)
        time.sleep(1.1)
        with pytest.raises(Exception):
            jwt.decode(tok, _JWT_SECRET, algorithms=[_JWT_ALGO])

    def test_custom_ttl(self):
        tok = issue_token("u@x", "c", "viewer", ttl_s=7200)
        data = jwt.decode(tok, _JWT_SECRET, algorithms=[_JWT_ALGO])
        assert data["exp"] > int(time.time()) + 7000


class TestRequireDependency:
    def test_author_principal_parsed(self):
        p = _fake_require("author")
        assert p.role == "author"
        assert p.customer == "horvath"

    def test_viewer_principal_parsed(self):
        p = _fake_require("viewer")
        assert p.role == "viewer"

    def test_require_raises_without_bearer(self):
        with pytest.raises(HTTPException) as exc_info:
            require(authorization="not-a-bearer-token")
        assert exc_info.value.status_code == 401

    def test_require_raises_on_tampered_token(self):
        with pytest.raises(HTTPException) as exc_info:
            require(authorization="Bearer eyJhbGciOiJIUzI1NiJ9.e30.tampered")
        assert exc_info.value.status_code == 401


class TestRequireAuthor:
    def test_author_passes(self):
        p = _fake_require("author")
        result = require_author(p)
        assert result.role == "author"

    def test_viewer_blocked(self):
        p = _fake_require("viewer")
        with pytest.raises(HTTPException) as exc_info:
            require_author(p)
        assert exc_info.value.status_code == 403

    def test_widget_blocked(self):
        p = _fake_require("widget")
        with pytest.raises(HTTPException) as exc_info:
            require_author(p)
        assert exc_info.value.status_code == 403
