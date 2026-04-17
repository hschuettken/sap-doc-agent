"""Tests for the Microsoft Graph Connector module.

Uses unittest.mock (not httpx-level mocking) to intercept httpx.AsyncClient
calls, so tests are fast and never touch the network.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spec2sphere.copilot.graph_connector import (
    GraphConnectorClient,
    GraphItem,
    _TokenCache,
    _build_all_items,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

_ENV = {
    "M365_TENANT_ID": "test-tenant",
    "M365_CLIENT_ID": "test-client",
    "M365_CLIENT_SECRET": "test-secret",
    "M365_CONNECTION_ID": "s2sconn",
}


def _make_client(**kwargs) -> GraphConnectorClient:
    return GraphConnectorClient(
        tenant_id=_ENV["M365_TENANT_ID"],
        client_id=_ENV["M365_CLIENT_ID"],
        client_secret=_ENV["M365_CLIENT_SECRET"],
        connection_id=_ENV["M365_CONNECTION_ID"],
        **kwargs,
    )


def _mock_response(status_code: int = 200, json_body: dict | None = None, content: bytes = b"") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content or (b"{}" if json_body is not None else b"")
    resp.json = MagicMock(return_value=json_body or {})
    resp.raise_for_status = MagicMock()
    return resp


# ---------------------------------------------------------------------------
# GraphItem validation
# ---------------------------------------------------------------------------


def test_graph_item_valid():
    item = GraphItem(
        id="s2s-architecture-overview",
        title="Architecture Overview",
        url="/copilot/architecture/overview",
        body="4-layer architecture content",
        type="spec",
        last_modified=_NOW,
    )
    assert item.type == "spec"
    assert item.author == "Spec2Sphere"


def test_graph_item_invalid_type():
    with pytest.raises(ValueError, match="must be one of"):
        GraphItem(
            id="x",
            title="X",
            url="/x",
            body="body",
            type="invalid_type",
            last_modified=_NOW,
        )


def test_graph_item_missing_required():
    with pytest.raises(ValueError, match="required"):
        GraphItem(id="", title="X", url="/x", body="body", type="spec", last_modified=_NOW)


# ---------------------------------------------------------------------------
# _TokenCache
# ---------------------------------------------------------------------------


def test_token_cache_empty_is_invalid():
    cache = _TokenCache()
    assert not cache.is_valid()


def test_token_cache_valid():
    cache = _TokenCache(token="tok", expires_at=time.time() + 3600)
    assert cache.is_valid()


def test_token_cache_expired():
    cache = _TokenCache(token="tok", expires_at=time.time() - 1)
    assert not cache.is_valid()


def test_token_cache_within_60s_buffer():
    """Token within 60 s of expiry is treated as invalid."""
    cache = _TokenCache(token="tok", expires_at=time.time() + 30)
    assert not cache.is_valid()


# ---------------------------------------------------------------------------
# Constructor — missing env vars
# ---------------------------------------------------------------------------


def test_client_raises_when_unconfigured():
    with pytest.raises(RuntimeError, match="M365 env vars"):
        GraphConnectorClient(tenant_id="", client_id="", client_secret="", connection_id="")


def test_client_allow_unconfigured():
    client = GraphConnectorClient(
        tenant_id="", client_id="", client_secret="", connection_id="", _allow_unconfigured=True
    )
    assert not client.is_configured


def test_client_is_configured():
    client = _make_client()
    assert client.is_configured


# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_token_fetches_and_caches():
    client = _make_client()
    token_resp = _mock_response(
        200, json_body={"access_token": "mytoken", "expires_in": 3600}, content=b'{"access_token":"mytoken"}'
    )
    token_resp.json.return_value = {"access_token": "mytoken", "expires_in": 3600}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=token_resp)

    with patch("httpx.AsyncClient", return_value=mock_http):
        token = await client._get_token()

    assert token == "mytoken"
    assert client._token_cache.is_valid()


@pytest.mark.asyncio
async def test_get_token_uses_cache_on_second_call():
    client = _make_client()
    # Pre-populate the cache
    client._token_cache.token = "cached_token"
    client._token_cache.expires_at = time.time() + 3600

    with patch("httpx.AsyncClient") as mock_cls:
        token = await client._get_token()
        # httpx should NOT have been called
        mock_cls.assert_not_called()

    assert token == "cached_token"


# ---------------------------------------------------------------------------
# create_connection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_connection_success():
    client = _make_client()
    client._token_cache.token = "tok"
    client._token_cache.expires_at = time.time() + 3600

    patch_resp = _mock_response(200, json_body={"id": "s2sconn"}, content=b'{"id":"s2sconn"}')
    patch_resp.json.return_value = {"id": "s2sconn"}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.patch = AsyncMock(return_value=patch_resp)

    with patch("httpx.AsyncClient", return_value=mock_http):
        result = await client.create_connection()

    assert result["id"] == "s2sconn"
    # Verify PATCH was called with correct URL
    call_args = mock_http.patch.call_args
    assert "s2sconn" in call_args.args[0]


@pytest.mark.asyncio
async def test_create_connection_409_fetches_existing():
    client = _make_client()
    client._token_cache.token = "tok"
    client._token_cache.expires_at = time.time() + 3600

    conflict_resp = _mock_response(409, content=b"")
    conflict_resp.raise_for_status = MagicMock()
    get_resp = _mock_response(200, json_body={"id": "s2sconn", "name": "Spec2Sphere Knowledge"})
    get_resp.json.return_value = {"id": "s2sconn", "name": "Spec2Sphere Knowledge"}

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.patch = AsyncMock(return_value=conflict_resp)
    mock_http.get = AsyncMock(return_value=get_resp)

    with patch("httpx.AsyncClient", return_value=mock_http):
        result = await client.create_connection()

    assert result["name"] == "Spec2Sphere Knowledge"


# ---------------------------------------------------------------------------
# create_schema
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_schema_accepted():
    client = _make_client()
    client._token_cache.token = "tok"
    client._token_cache.expires_at = time.time() + 3600

    resp_202 = _mock_response(202, content=b"")
    resp_202.raise_for_status = MagicMock()

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.patch = AsyncMock(return_value=resp_202)

    with patch("httpx.AsyncClient", return_value=mock_http):
        await client.create_schema()  # should not raise

    # Verify the schema payload contains our property names
    call_args = mock_http.patch.call_args
    payload = call_args.kwargs.get("json") or {}
    prop_names = [p["name"] for p in payload.get("properties", [])]
    assert "title" in prop_names
    assert "body" in prop_names
    assert "lastModified" in prop_names
    assert "type" in prop_names
    assert "author" in prop_names


# ---------------------------------------------------------------------------
# push_item / push_items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_item_payload_shape():
    """Verify the PUT payload has the expected shape."""
    client = _make_client()
    client._token_cache.token = "tok"
    client._token_cache.expires_at = time.time() + 3600

    item = GraphItem(
        id="s2s-architecture-overview",
        title="Architecture Overview",
        url="/copilot/architecture/overview",
        body="Content here.",
        type="spec",
        last_modified=_NOW,
        author="Spec2Sphere",
    )

    put_resp = _mock_response(200, content=b"")
    put_resp.raise_for_status = MagicMock()

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.put = AsyncMock(return_value=put_resp)

    with patch("httpx.AsyncClient", return_value=mock_http):
        await client.push_item(item)

    call_args = mock_http.put.call_args
    url = call_args.args[0]
    payload = call_args.kwargs.get("json") or {}

    assert "s2s-architecture-overview" in url
    assert payload["id"] == "s2s-architecture-overview"
    assert payload["properties"]["title"] == "Architecture Overview"
    assert payload["properties"]["type"] == "spec"
    assert payload["properties"]["body"] == "Content here."
    assert "2026-01-15" in payload["properties"]["lastModified"]
    assert payload["acl"][0]["accessType"] == "grant"
    assert payload["content"]["type"] == "text"


@pytest.mark.asyncio
async def test_push_items_summary():
    client = _make_client()
    client._token_cache.token = "tok"
    client._token_cache.expires_at = time.time() + 3600

    items = [
        GraphItem(id=f"item-{i}", title=f"Item {i}", url=f"/item/{i}", body="body", type="spec", last_modified=_NOW)
        for i in range(3)
    ]

    put_resp = _mock_response(200, content=b"")
    put_resp.raise_for_status = MagicMock()

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.put = AsyncMock(return_value=put_resp)

    with patch("httpx.AsyncClient", return_value=mock_http):
        result = await client.push_items(items)

    assert result["pushed"] == 3
    assert result["failed"] == 0
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_push_items_partial_failure():
    client = _make_client()
    client._token_cache.token = "tok"
    client._token_cache.expires_at = time.time() + 3600

    items = [
        GraphItem(id=f"item-{i}", title=f"Item {i}", url=f"/item/{i}", body="body", type="spec", last_modified=_NOW)
        for i in range(2)
    ]

    ok_resp = _mock_response(200, content=b"")
    ok_resp.raise_for_status = MagicMock()

    fail_resp = _mock_response(500, content=b"error")
    fail_resp.raise_for_status = MagicMock(side_effect=Exception("500 error"))

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.put = AsyncMock(side_effect=[ok_resp, fail_resp])

    with patch("httpx.AsyncClient", return_value=mock_http):
        result = await client.push_items(items)

    assert result["pushed"] == 1
    assert result["failed"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["id"] == "item-1"


# ---------------------------------------------------------------------------
# delete_item
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_item_success():
    client = _make_client()
    client._token_cache.token = "tok"
    client._token_cache.expires_at = time.time() + 3600

    del_resp = _mock_response(204, content=b"")
    del_resp.raise_for_status = MagicMock()

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.delete = AsyncMock(return_value=del_resp)

    with patch("httpx.AsyncClient", return_value=mock_http):
        await client.delete_item("item-123")  # should not raise

    call_url = mock_http.delete.call_args.args[0]
    assert "item-123" in call_url


@pytest.mark.asyncio
async def test_delete_item_404_is_silent():
    client = _make_client()
    client._token_cache.token = "tok"
    client._token_cache.expires_at = time.time() + 3600

    not_found = _mock_response(404, content=b"")
    not_found.raise_for_status = MagicMock()

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.delete = AsyncMock(return_value=not_found)

    with patch("httpx.AsyncClient", return_value=mock_http):
        await client.delete_item("ghost-item")  # should not raise


# ---------------------------------------------------------------------------
# _build_all_items (content builder)
# ---------------------------------------------------------------------------


def test_build_all_items_returns_list():
    items = _build_all_items()
    assert isinstance(items, list)
    assert len(items) > 0


def test_build_all_items_valid_types():
    items = _build_all_items()
    for item in items:
        assert item.type in {"spec", "route", "knowledge", "governance"}
        assert item.id
        assert item.title
        assert item.url.startswith("/copilot/")
        assert isinstance(item.last_modified, datetime)


def test_build_all_items_architecture_present():
    items = _build_all_items()
    ids = {i.id for i in items}
    # Architecture pages should be indexed as spec type
    arch_items = [i for i in items if "architecture" in i.id]
    assert len(arch_items) > 0


def test_build_all_items_no_body_overflow():
    """No item body should exceed 8000 characters (Graph API limit)."""
    items = _build_all_items()
    for item in items:
        assert len(item.body) <= 8000


# ---------------------------------------------------------------------------
# incremental_sync — only items after cutoff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incremental_sync_skips_old_items():
    """Items with last_modified before the cutoff are excluded."""
    client = _make_client()
    client._token_cache.token = "tok"
    client._token_cache.expires_at = time.time() + 3600

    # Patch _build_all_items to return one old and one new item
    old_item = GraphItem(
        id="old",
        title="Old",
        url="/old",
        body="old body",
        type="spec",
        last_modified=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    new_item = GraphItem(
        id="new",
        title="New",
        url="/new",
        body="new body",
        type="spec",
        last_modified=datetime(2026, 4, 17, 12, 0, 0, tzinfo=timezone.utc),
    )

    with patch("spec2sphere.copilot.graph_connector._build_all_items", return_value=[old_item, new_item]):
        # Also mock push_items to avoid network
        async def _fake_push(items):
            return {"pushed": len(items), "failed": 0, "errors": []}

        client.push_items = _fake_push  # type: ignore[method-assign]
        since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = await client.incremental_sync(since)

    assert result["pushed"] == 1  # only the new item
