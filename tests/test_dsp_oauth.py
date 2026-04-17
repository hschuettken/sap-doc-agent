"""
Tests for DSP OAuth 2.0 client credentials flow:
  - DSPOAuthClient (token caching, expiry, invalidate, async lock)
  - DSPBasicAuth (header generation, invalidate no-op)
  - DSPAuthFactory (dispatch from config dict)
  - DSPScanner 401 → token refresh flow
"""

from __future__ import annotations

import time

import httpx
import pytest
import respx

from spec2sphere.scanner.dsp_auth import (
    DSPAuth,  # backward-compat alias
    DSPAuthFactory,
    DSPBasicAuth,
    DSPOAuthClient,
)
from spec2sphere.scanner.dsp_scanner import DSPScanner

TOKEN_URL = "https://auth.example.com/oauth/token"
BASE_URL = "https://dsp.example.com"


# ---------------------------------------------------------------------------
# DSPOAuthClient — token caching
# ---------------------------------------------------------------------------


@respx.mock
async def test_oauth_client_token_fetched_once_and_cached():
    """Token is fetched once and reused on the second call."""
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "tok-1", "expires_in": 3600})
    )
    client = DSPOAuthClient("cid", "csec", TOKEN_URL)
    t1 = await client.get_token()
    t2 = await client.get_token()
    assert t1 == t2 == "tok-1"
    assert route.call_count == 1


@respx.mock
async def test_oauth_client_refreshes_when_expired():
    """Token is refreshed when _expires_at is in the past."""
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
    )
    client = DSPOAuthClient("cid", "csec", TOKEN_URL)
    # Simulate an already-expired token
    client._access_token = "stale"
    client._expires_at = time.time() - 1  # expired

    token = await client.get_token()
    assert token == "fresh"
    assert route.call_count == 1


@respx.mock
async def test_oauth_client_refreshes_within_60s_buffer():
    """Token is refreshed when within the 60-second expiry buffer."""
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "buffered", "expires_in": 3600})
    )
    client = DSPOAuthClient("cid", "csec", TOKEN_URL)
    # Token expires in 30 s — inside the 60 s buffer
    client._access_token = "almost-expired"
    client._expires_at = time.time() + 30

    token = await client.get_token()
    assert token == "buffered"
    assert route.call_count == 1


@respx.mock
async def test_oauth_client_authorization_header():
    """get_headers returns correct Bearer Authorization header."""
    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "header-tok", "expires_in": 3600})
    )
    client = DSPOAuthClient("cid", "csec", TOKEN_URL)
    headers = await client.get_headers()
    assert headers == {"Authorization": "Bearer header-tok"}


@respx.mock
async def test_oauth_client_invalidate_forces_refresh():
    """After invalidate(), the next get_token() call fetches a fresh token."""
    route = respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "new-tok", "expires_in": 3600})
    )
    client = DSPOAuthClient("cid", "csec", TOKEN_URL)
    # Prime the cache manually
    client._access_token = "old-tok"
    client._expires_at = time.time() + 3600

    await client.invalidate()
    token = await client.get_token()
    assert token == "new-tok"
    assert route.call_count == 1


@respx.mock
async def test_oauth_client_failure_raises_runtime_error():
    """Non-200 token response raises RuntimeError with 'OAuth' in message."""
    respx.post(TOKEN_URL).mock(return_value=httpx.Response(401, text="Unauthorized"))
    client = DSPOAuthClient("cid", "csec", TOKEN_URL)
    with pytest.raises(RuntimeError, match="OAuth"):
        await client.get_token()


async def test_dsp_auth_alias_is_oauth_client():
    """DSPAuth is the backward-compatible alias for DSPOAuthClient."""
    auth = DSPAuth("a", "b", "https://example.com/token")
    assert isinstance(auth, DSPOAuthClient)


# ---------------------------------------------------------------------------
# DSPBasicAuth
# ---------------------------------------------------------------------------


async def test_basic_auth_header_format():
    """DSPBasicAuth.get_headers returns a valid Basic Authorization header."""
    import base64

    auth = DSPBasicAuth("alice", "wonderland")
    headers = await auth.get_headers()
    expected = base64.b64encode(b"alice:wonderland").decode()
    assert headers == {"Authorization": f"Basic {expected}"}


async def test_basic_auth_invalidate_is_noop():
    """DSPBasicAuth.invalidate does not raise and has no side effects."""
    auth = DSPBasicAuth("u", "p")
    await auth.invalidate()  # must not raise
    headers = await auth.get_headers()
    assert "Authorization" in headers


async def test_basic_auth_exposes_httpx_auth():
    """DSPBasicAuth.httpx_auth returns an httpx.BasicAuth instance."""
    auth = DSPBasicAuth("u", "p")
    assert isinstance(auth.httpx_auth, httpx.BasicAuth)


# ---------------------------------------------------------------------------
# DSPAuthFactory — config dispatch
# ---------------------------------------------------------------------------


async def test_factory_oauth_from_explicit_type():
    """from_config with auth.type='oauth' returns DSPOAuthClient."""
    config = {
        "auth": {
            "type": "oauth",
            "oauth": {
                "token_url": "https://auth.example.com/token",
                "client_id": "my_client",
                "client_secret": "my_secret",
            },
        }
    }
    auth = DSPAuthFactory.from_config(config)
    assert isinstance(auth, DSPOAuthClient)


async def test_factory_oauth_from_top_level_oauth_block():
    """from_config with top-level 'oauth' block (legacy style) returns DSPOAuthClient."""
    config = {
        "oauth": {
            "token_url": "https://auth.example.com/token",
            "client_id": "cid",
            "client_secret": "csec",
        }
    }
    auth = DSPAuthFactory.from_config(config)
    assert isinstance(auth, DSPOAuthClient)


async def test_factory_oauth_resolves_env_vars(monkeypatch):
    """from_config resolves *_env references from environment variables."""
    monkeypatch.setenv("MY_CLIENT_ID", "env-client")
    monkeypatch.setenv("MY_CLIENT_SECRET", "env-secret")
    monkeypatch.setenv("MY_TOKEN_URL", "https://env.example.com/token")

    config = {
        "oauth": {
            "client_id_env": "MY_CLIENT_ID",
            "client_secret_env": "MY_CLIENT_SECRET",
            "token_url_env": "MY_TOKEN_URL",
        }
    }
    auth = DSPAuthFactory.from_config(config)
    assert isinstance(auth, DSPOAuthClient)
    assert auth._client_id == "env-client"
    assert auth._client_secret == "env-secret"
    assert auth._token_url == "https://env.example.com/token"


async def test_factory_basic_from_explicit_type():
    """from_config with auth.type='basic' returns DSPBasicAuth."""
    config = {
        "auth": {
            "type": "basic",
            "username": "bob",
            "password": "s3cr3t",
        }
    }
    auth = DSPAuthFactory.from_config(config)
    assert isinstance(auth, DSPBasicAuth)


async def test_factory_basic_resolves_env_vars(monkeypatch):
    """from_config resolves username_env / password_env from environment."""
    monkeypatch.setenv("DSP_USER", "carol")
    monkeypatch.setenv("DSP_PASS", "p@ss")

    config = {
        "auth": {
            "type": "basic",
            "username_env": "DSP_USER",
            "password_env": "DSP_PASS",
        }
    }
    auth = DSPAuthFactory.from_config(config)
    assert isinstance(auth, DSPBasicAuth)


async def test_factory_raises_on_missing_oauth_fields():
    """ValueError raised when oauth block is present but fields are missing."""
    config = {
        "auth": {
            "type": "oauth",
            "oauth": {
                # token_url missing, env vars not set
                "client_id": "x",
                "client_secret": "y",
            },
        }
    }
    with pytest.raises(ValueError, match="token_url"):
        DSPAuthFactory.from_config(config)


async def test_factory_raises_when_no_auth_info():
    """ValueError raised when config has no recognisable auth information."""
    with pytest.raises(ValueError, match="Cannot determine"):
        DSPAuthFactory.from_config({})


# ---------------------------------------------------------------------------
# DSPScanner — 401 triggers token refresh
# ---------------------------------------------------------------------------


@respx.mock
async def test_scanner_refreshes_token_on_401():
    """
    A 401 from the catalog endpoint triggers invalidate() + one retry.
    The retry uses the fresh token and succeeds.
    """
    # Token endpoint: first call returns tok-old, second returns tok-new
    token_route = respx.post(TOKEN_URL).mock(
        side_effect=[
            httpx.Response(200, json={"access_token": "tok-old", "expires_in": 3600}),
            httpx.Response(200, json={"access_token": "tok-new", "expires_in": 3600}),
        ]
    )
    assets_url = f"{BASE_URL}/api/v1/dwc/catalog/assets"
    # First assets request → 401 (stale token); second → 200 (fresh token)
    assets_route = respx.get(assets_url).mock(
        side_effect=[
            httpx.Response(401, text="Unauthorized"),
            httpx.Response(200, json={"value": [{"technicalName": "OBJ1", "type": "VIEW", "description": ""}]}),
        ]
    )

    auth = DSPOAuthClient("cid", "csec", TOKEN_URL)
    scanner = DSPScanner(base_url=BASE_URL, auth=auth, spaces=["SPACE_A"])
    result = await scanner.scan()

    assert len(result.objects) == 1
    assert result.objects[0].name == "OBJ1"
    # Token was fetched twice: initial + after invalidate
    assert token_route.call_count == 2
    # Assets endpoint was called twice: 401 + retry
    assert assets_route.call_count == 2


@respx.mock
async def test_scanner_basic_auth_gets_correct_header():
    """DSPScanner works correctly with DSPBasicAuth (no token refresh)."""
    auth = DSPBasicAuth("alice", "secret")
    assets_url = f"{BASE_URL}/api/v1/dwc/catalog/assets"
    spaces_url = f"{BASE_URL}/api/v1/dwc/catalog/spaces"

    captured_headers: list[str] = []

    def capture(request, route):
        captured_headers.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"value": []})

    respx.get(assets_url).mock(side_effect=capture)
    respx.get(spaces_url).mock(side_effect=capture)

    scanner = DSPScanner(base_url=BASE_URL, auth=auth, spaces=["S"])
    await scanner.scan()

    assert any(h.startswith("Basic ") for h in captured_headers)
