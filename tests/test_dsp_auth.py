"""Tests for DSP OAuth 2.0 authentication."""

from __future__ import annotations

import time

import pytest
import respx
import httpx

from sap_doc_agent.scanner.dsp_auth import DSPAuth

TOKEN_URL = "https://auth.example.com/oauth/token"


def _make_auth() -> DSPAuth:
    return DSPAuth(
        client_id="test_client",
        client_secret="test_secret",
        token_url=TOKEN_URL,
    )


@respx.mock
async def test_get_token_returns_access_token():
    """get_token returns the access_token from the OAuth response."""
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "my-token", "expires_in": 3600}))
    auth = _make_auth()
    token = await auth.get_token()
    assert token == "my-token"


@respx.mock
async def test_get_token_cached_no_second_request():
    """Second call to get_token uses cached token — no extra HTTP request."""
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "cached-token", "expires_in": 3600})
    )
    auth = _make_auth()
    await auth.get_token()
    await auth.get_token()
    assert route.call_count == 1


@respx.mock
async def test_get_token_refreshes_when_expired():
    """Token is refreshed when _expires_at is in the past."""
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "fresh-token", "expires_in": 3600})
    )
    auth = _make_auth()
    # Force expired state
    auth._access_token = "old-token"
    auth._expires_at = time.time() - 1  # already expired

    token = await auth.get_token()
    assert token == "fresh-token"
    assert route.call_count == 1


@respx.mock
async def test_auth_failure_raises_runtime_error():
    """Non-200 OAuth response raises RuntimeError with 'OAuth' in message."""
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(401, text="Unauthorized"))
    auth = _make_auth()
    with pytest.raises(RuntimeError, match="OAuth"):
        await auth.get_token()


@respx.mock
async def test_get_headers_returns_authorization_header():
    """get_headers returns correct Authorization Bearer header."""
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "header-token", "expires_in": 3600})
    )
    auth = _make_auth()
    headers = await auth.get_headers()
    assert headers == {"Authorization": "Bearer header-token"}
