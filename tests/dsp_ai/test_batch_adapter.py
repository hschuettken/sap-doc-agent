"""Unit tests for the dsp-ai batch adapter.

Mocks asyncpg + run_engine so the tests don't require a live compose.
Integration coverage (real DB + engine end-to-end) lives in test_smoke.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class _FakeConn:
    """Asyncpg-ish stub — the batch adapter only calls fetch() + close()."""

    def __init__(self, *, enh_rows=None, user_rows=None):
        self._enh_rows = enh_rows or []
        self._user_rows = user_rows or []
        self.closed = False

    async def fetch(self, query, *args):
        q = query.lower()
        if "dsp_ai.enhancements" in q:
            return list(self._enh_rows)
        if "dsp_ai.user_state" in q:
            return list(self._user_rows)
        return []

    async def close(self):
        self.closed = True


def _make_conn(**kwargs):
    conn = _FakeConn(**kwargs)

    async def _connect(*_args, **_kw):
        return conn

    return conn, _connect


@pytest.mark.asyncio
async def test_batch_skips_when_no_published_enhancements() -> None:
    from spec2sphere.dsp_ai.adapters import batch as batch_mod

    conn, connect = _make_conn(enh_rows=[], user_rows=[])
    with patch.object(batch_mod.asyncpg, "connect", connect):
        result = await batch_mod._run_batch_enhancements_async()

    assert result["enhancements"] == 0
    assert result["ran"] == 0
    assert result["errors"] == 0
    assert conn.closed is True


@pytest.mark.asyncio
async def test_batch_runs_one_published_enhancement_for_default_user() -> None:
    from spec2sphere.dsp_ai.adapters import batch as batch_mod

    conn, connect = _make_conn(
        enh_rows=[{"id": "11111111-1111-1111-1111-111111111111"}],
        user_rows=[],  # no active users → falls back to _default
    )
    engine = AsyncMock(return_value={"generation_id": "gen-1", "content": "ok"})

    with patch.object(batch_mod.asyncpg, "connect", connect), patch.object(batch_mod, "run_engine", engine):
        result = await batch_mod._run_batch_enhancements_async()

    assert result == {"enhancements": 1, "users": 1, "ran": 1, "errors": 0}
    engine.assert_awaited_once()
    args, kwargs = engine.call_args
    assert args[0] == "11111111-1111-1111-1111-111111111111"
    assert kwargs["user_id"] == "_default"
    assert kwargs["context_key"] == "default"


@pytest.mark.asyncio
async def test_batch_continues_on_per_user_failure() -> None:
    """One user failing must not abort the rest — errors counter records it."""
    from spec2sphere.dsp_ai.adapters import batch as batch_mod

    conn, connect = _make_conn(
        enh_rows=[{"id": "enh-1"}],
        user_rows=[{"user_id": "alice"}, {"user_id": "bob"}],
    )

    async def flaky_engine(enhancement_id, **kwargs):
        if kwargs["user_id"] == "alice":
            raise RuntimeError("boom")
        return {"ok": True}

    with patch.object(batch_mod.asyncpg, "connect", connect), patch.object(batch_mod, "run_engine", flaky_engine):
        result = await batch_mod._run_batch_enhancements_async()

    assert result["ran"] == 1
    assert result["errors"] == 1


def test_crontab_helper_parses_batch_cron(monkeypatch) -> None:
    """schedules._crontab_from_env must round-trip the BATCH_CRON string."""
    from spec2sphere.tasks import schedules

    monkeypatch.setenv("BATCH_CRON", "30 7 * * 1")  # Mondays 07:30
    ct = schedules._crontab_from_env("BATCH_CRON", "0 6 * * 1-5")
    assert "30" in str(ct.minute)
    assert "7" in str(ct.hour)


def test_crontab_helper_falls_back_on_malformed_value(monkeypatch) -> None:
    from spec2sphere.tasks import schedules

    monkeypatch.setenv("BATCH_CRON", "not a cron")
    ct = schedules._crontab_from_env("BATCH_CRON", "0 6 * * 1-5")
    assert "6" in str(ct.hour)
