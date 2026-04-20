"""Contract tests for the dsp-ai live adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from spec2sphere.dsp_ai.service import app


@pytest.mark.asyncio
async def test_healthz_ok() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz_reports_dependency_warnings_gracefully() -> None:
    """readyz never 500s — reports dependency issues as warnings."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "warnings" in body  # postgres/redis may or may not be reachable in CI


@pytest.mark.asyncio
async def test_enhance_404_on_unknown_id() -> None:
    async def boom(*_, **__):
        raise LookupError("missing")

    with (
        patch("spec2sphere.dsp_ai.adapters.live.run_engine", boom),
        patch("spec2sphere.dsp_ai.adapters.live.cache.get", AsyncMock(return_value=None)),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/v1/enhance/00000000-0000-0000-0000-000000000000", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_enhance_cache_hit_short_circuits_engine() -> None:
    cached_payload = {"generation_id": "abc", "content": "cached", "render_hint": "narrative_text"}
    called = {"engine": 0}

    async def fake_engine(*_, **__):
        called["engine"] += 1
        return {}

    with (
        patch("spec2sphere.dsp_ai.adapters.live.cache.get", AsyncMock(return_value=cached_payload)),
        patch("spec2sphere.dsp_ai.adapters.live.cache.set_", AsyncMock()),
        patch("spec2sphere.dsp_ai.adapters.live.run_engine", fake_engine),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/v1/enhance/abc", json={"user": "h"})

    assert r.status_code == 200
    body = r.json()
    assert body["_cached"] is True
    assert body["content"] == "cached"
    assert called["engine"] == 0


@pytest.mark.asyncio
async def test_enhance_preview_bypasses_cache() -> None:
    """preview=True must skip the cache read AND skip the cache write."""
    engine_calls = {"n": 0}

    async def fake_engine(enhancement_id, **kwargs):
        engine_calls["n"] += 1
        assert kwargs.get("preview") is True
        return {"generation_id": "xyz", "content": "fresh"}

    cache_set = AsyncMock()
    cache_get = AsyncMock()
    with (
        patch("spec2sphere.dsp_ai.adapters.live.cache.get", cache_get),
        patch("spec2sphere.dsp_ai.adapters.live.cache.set_", cache_set),
        patch("spec2sphere.dsp_ai.adapters.live.run_engine", fake_engine),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/v1/enhance/abc", json={"user": "h", "preview": True})

    assert r.status_code == 200
    assert engine_calls["n"] == 1
    cache_get.assert_not_called()
    cache_set.assert_not_called()


@pytest.mark.asyncio
async def test_enhance_error_result_not_cached() -> None:
    """Results with error_kind must NOT be written to cache to prevent permanent failure lock-in."""
    cache_set = AsyncMock()

    async def fake_engine_timeout(enhancement_id, **kwargs):
        return {"generation_id": "err1", "content": None, "error_kind": "llm_timeout"}

    with (
        patch("spec2sphere.dsp_ai.adapters.live.cache.get", AsyncMock(return_value=None)),
        patch("spec2sphere.dsp_ai.adapters.live.cache.set_", cache_set),
        patch("spec2sphere.dsp_ai.adapters.live.run_engine", fake_engine_timeout),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/v1/enhance/abc", json={"user": "h"})

    assert r.status_code == 200
    body = r.json()
    assert body.get("error_kind") == "llm_timeout"
    cache_set.assert_not_called(), "error result must never be written to cache"


@pytest.mark.asyncio
async def test_enhance_success_result_is_cached() -> None:
    """Successful results (no error_kind) must be written to cache."""
    cache_set = AsyncMock()

    async def fake_engine_ok(enhancement_id, **kwargs):
        return {"generation_id": "ok1", "content": "hello", "error_kind": None}

    with (
        patch("spec2sphere.dsp_ai.adapters.live.cache.get", AsyncMock(return_value=None)),
        patch("spec2sphere.dsp_ai.adapters.live.cache.set_", cache_set),
        patch("spec2sphere.dsp_ai.adapters.live.run_engine", fake_engine_ok),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/v1/enhance/abc", json={"user": "h"})

    assert r.status_code == 200
    cache_set.assert_called_once()


def test_cache_key_is_stable_for_same_inputs() -> None:
    from spec2sphere.dsp_ai.cache import key_for

    a = key_for("enh-1", "user-1", {"region": "FR", "q": 3})
    b = key_for("enh-1", "user-1", {"q": 3, "region": "FR"})  # key order irrelevant
    c = key_for("enh-1", "user-1", {"region": "DE", "q": 3})
    assert a == b
    assert a != c


def test_cache_key_includes_user_discriminator() -> None:
    from spec2sphere.dsp_ai.cache import key_for

    a = key_for("enh-1", "user-1", {})
    b = key_for("enh-1", "user-2", {})
    anon = key_for("enh-1", None, {})
    assert a != b
    assert anon.endswith(":_:" + a.split(":")[-1])  # None resolves to "_"
