"""Contract tests for the Session B live adapter additions.

Covers: /v1/actions/{id}/run, /v1/why/{gen_id}, /v1/telemetry.

SSE streaming (/v1/stream/{id}/{user}) is not tested here — ASGI test
clients don't stream SSE naturally.
# TODO session B Task 14: SSE integration smoke against live compose
"""

from __future__ import annotations

import datetime
import decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from spec2sphere.dsp_ai.auth import issue_token
from spec2sphere.dsp_ai.service import app


def _auth_headers(role: str = "viewer") -> dict:
    tok = issue_token("test@spec2sphere", "default", role)
    return {"Authorization": f"Bearer {tok}"}


# ---------------------------------------------------------------------------
# /v1/actions/{enhancement_id}/run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_action_404_on_unknown_id() -> None:
    async def boom(*_, **__):
        raise LookupError("missing")

    with patch("spec2sphere.dsp_ai.adapters.live.run_engine", boom):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/v1/actions/no-such-id/run",
                json={},
                headers=_auth_headers(),
            )

    assert r.status_code == 404
    assert r.json()["detail"] == "enhancement not found"


@pytest.mark.asyncio
async def test_run_action_200_on_existing() -> None:
    engine = AsyncMock(return_value={"content": "ok", "generation_id": "g1"})

    with patch("spec2sphere.dsp_ai.adapters.live.run_engine", engine):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/v1/actions/enh-1/run",
                json={"user": "h"},
                headers=_auth_headers(),
            )

    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "ok"
    assert body["generation_id"] == "g1"


@pytest.mark.asyncio
async def test_run_action_does_not_consult_cache() -> None:
    engine = AsyncMock(return_value={"content": "fresh"})
    cache_get = AsyncMock()

    with (
        patch("spec2sphere.dsp_ai.adapters.live.run_engine", engine),
        patch("spec2sphere.dsp_ai.adapters.live.cache.get", cache_get),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.post("/v1/actions/enh-1/run", json={}, headers=_auth_headers())

    cache_get.assert_not_called()


# ---------------------------------------------------------------------------
# /v1/why/{generation_id}
# ---------------------------------------------------------------------------


class _FakeConn:
    """asyncpg-ish stub for why() tests."""

    def __init__(self, row):
        self._row = row

    async def fetchrow(self, query, *args):
        return self._row

    async def close(self):
        pass


def _make_why_conn(row):
    conn = _FakeConn(row)

    async def _connect(*_args, **_kw):
        return conn

    return conn, _connect


def _gen_row(**overrides):
    base = {
        "gen_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "eid": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        "user_id": "h",
        "context_key": "daily",
        "prompt_hash": "abc123",
        "input_ids": ["node-1", "node-2"],
        "model": "gpt-4o",
        "quality_level": "standard",
        "latency_ms": 312,
        "tokens_in": 100,
        "tokens_out": 50,
        "cost_usd": decimal.Decimal("0.001"),
        "cached": False,
        "quality_warnings": None,
        "error_kind": None,
        "preview": False,
        "created_at": datetime.datetime(2026, 4, 17, 10, 0, 0),
        "enh_name": "My Enhancement",
        "enh_version": "1.0",
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_why_404_on_unknown() -> None:
    _, connect = _make_why_conn(None)

    # asyncpg is imported lazily inside why() — patch the module directly
    with patch("asyncpg.connect", connect):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/v1/why/00000000-0000-0000-0000-000000000000")

    assert r.status_code == 404
    assert r.json()["detail"] == "generation not found"


@pytest.mark.asyncio
async def test_why_200_with_narrative() -> None:
    row = _gen_row()
    _, connect = _make_why_conn(row)

    with (
        patch("asyncpg.connect", connect),
        patch("spec2sphere.dsp_ai.brain.client.run", AsyncMock(return_value=[])),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/v1/why/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    assert r.status_code == 200
    body = r.json()
    assert body["generation_id"] == row["gen_id"]
    assert "narrative" in body and len(body["narrative"]) > 0
    assert "provenance" in body
    assert body["provenance"]["model"] == "gpt-4o"
    assert body["provenance"]["input_ids"] == ["node-1", "node-2"]
    assert "brain_one_hop" in body


# ---------------------------------------------------------------------------
# /v1/telemetry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telemetry_returns_ok_even_when_record_event_fails() -> None:
    """Telemetry endpoint must never propagate record_event errors to caller."""
    # Ensure behavior module exists (stub or real)
    beh = pytest.importorskip("spec2sphere.dsp_ai.brain.feeders.behavior")

    async def boom(ev):
        raise RuntimeError("storage unavailable")

    with patch.object(beh, "record_event", boom):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/v1/telemetry",
                json={"kind": "widget.clicked", "user_id": "h", "enhancement_id": "enh-1"},
            )

    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_telemetry_ok_on_success() -> None:
    """Happy path — record_event succeeds, still returns {ok: True}."""
    beh = pytest.importorskip("spec2sphere.dsp_ai.brain.feeders.behavior")

    called = {"n": 0}

    async def stub(ev):
        called["n"] += 1

    with patch.object(beh, "record_event", stub):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post(
                "/v1/telemetry",
                json={
                    "kind": "widget.dwelled",
                    "user_id": "h",
                    "duration_s": 3.5,
                    "details": {"widget": "briefing"},
                },
            )

    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert called["n"] == 1
