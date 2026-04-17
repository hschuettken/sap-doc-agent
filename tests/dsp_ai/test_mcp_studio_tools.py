"""Tests for MCP Studio tools (studio_tools.py).

Happy paths + one error path per tool.  asyncpg.connect is patched with a
_FakeConn so no real DB connection is required.
"""

from __future__ import annotations

import datetime
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from spec2sphere.copilot import studio_tools


# ------------------------------------------------------------------ helpers --


class _FakeConn:
    def __init__(self, fetchall=None, fetchone=None):
        self._fetchall = fetchall or []
        self._fetchone = fetchone
        self.executed: list[tuple] = []

    async def fetch(self, q, *args):
        return list(self._fetchall)

    async def fetchrow(self, q, *args):
        return self._fetchone

    async def execute(self, q, *args):
        self.executed.append((q, args))

    async def close(self):
        pass


def _connect_returning(conn):
    async def _c(*_a, **_k):
        return conn

    return _c


# --------------------------------------------------------- list_enhancements --


@pytest.mark.asyncio
async def test_list_enhancements_renders_rows() -> None:
    conn = _FakeConn(
        fetchall=[
            {
                "id": "a1b2c3d4-0000-0000-0000-000000000001",
                "name": "Morning Brief",
                "kind": "briefing",
                "version": 1,
                "status": "published",
            },
        ]
    )
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.list_enhancements({})
    text = out["content"][0]["text"]
    assert "Morning Brief" in text
    assert "published" in text


@pytest.mark.asyncio
async def test_list_enhancements_empty() -> None:
    conn = _FakeConn(fetchall=[])
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.list_enhancements({})
    assert "No enhancements found" in out["content"][0]["text"]


@pytest.mark.asyncio
async def test_list_enhancements_with_status_filter() -> None:
    conn = _FakeConn(
        fetchall=[
            {
                "id": "a1b2c3d4-0000-0000-0000-000000000002",
                "name": "Draft One",
                "kind": "narrative",
                "version": 1,
                "status": "draft",
            },
        ]
    )
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.list_enhancements({"status": "draft"})
    assert "Draft One" in out["content"][0]["text"]


# ---------------------------------------------------------- get_enhancement --


@pytest.mark.asyncio
async def test_get_enhancement_renders_config() -> None:
    conn = _FakeConn(
        fetchone={
            "id": "abc",
            "name": "Test Enh",
            "kind": "narrative",
            "version": 2,
            "status": "staging",
            "config": '{"render_hint": "narrative_text"}',
        }
    )
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.get_enhancement({"enhancement_id": "abc"})
    text = out["content"][0]["text"]
    assert "Test Enh" in text
    assert "narrative_text" in text


@pytest.mark.asyncio
async def test_get_enhancement_404_when_missing() -> None:
    conn = _FakeConn(fetchone=None)
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.get_enhancement({"enhancement_id": "00000000-0000-0000-0000-000000000000"})
    assert out.get("isError") is True


@pytest.mark.asyncio
async def test_get_enhancement_missing_id() -> None:
    out = await studio_tools.get_enhancement({})
    assert out.get("isError") is True
    assert "required" in out["content"][0]["text"]


# ------------------------------------------------------- create_enhancement --


@pytest.mark.asyncio
async def test_create_enhancement_inserts_row() -> None:
    conn = _FakeConn()
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.create_enhancement(
            {
                "name": "Test",
                "kind": "narrative",
                "config": {"render_hint": "narrative_text"},
            }
        )
    assert "Created enhancement" in out["content"][0]["text"]
    assert conn.executed  # INSERT ran


@pytest.mark.asyncio
async def test_create_enhancement_missing_name_or_kind() -> None:
    out = await studio_tools.create_enhancement({"name": "OnlyName"})
    assert out.get("isError") is True


@pytest.mark.asyncio
async def test_create_enhancement_bad_config_json() -> None:
    conn = _FakeConn()
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.create_enhancement({"name": "T", "kind": "narrative", "config": "NOT_JSON{{"})
    assert out.get("isError") is True


# ------------------------------------------------------- update_enhancement --


@pytest.mark.asyncio
async def test_update_enhancement_merges_patch() -> None:
    conn = _FakeConn(fetchone={"config": '{"existing_key": "val"}'})
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.update_enhancement(
            {
                "enhancement_id": "abc",
                "patch": {"new_key": "new_val"},
            }
        )
    text = out["content"][0]["text"]
    assert "Updated enhancement" in text
    assert "1 key(s)" in text


@pytest.mark.asyncio
async def test_update_enhancement_404() -> None:
    conn = _FakeConn(fetchone=None)
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.update_enhancement({"enhancement_id": "missing", "patch": {"x": 1}})
    assert out.get("isError") is True


@pytest.mark.asyncio
async def test_update_enhancement_missing_id() -> None:
    out = await studio_tools.update_enhancement({"patch": {"x": 1}})
    assert out.get("isError") is True


# --------------------------------------------------------------- preview -----


@pytest.mark.asyncio
async def test_preview_uses_dspai_url() -> None:
    mock_resp = MagicMock(status_code=200)
    mock_resp.json = MagicMock(return_value={"generation_id": "g", "content": "ok"})

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, json=None):
            return mock_resp

    with patch.object(studio_tools.httpx, "AsyncClient", _Client):
        out = await studio_tools.preview({"enhancement_id": "abc"})
    assert "Preview result" in out["content"][0]["text"]


@pytest.mark.asyncio
async def test_preview_missing_id() -> None:
    out = await studio_tools.preview({})
    assert out.get("isError") is True


@pytest.mark.asyncio
async def test_preview_http_error() -> None:
    mock_resp = MagicMock(status_code=500)
    mock_resp.text = "internal error"

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, json=None):
            return mock_resp

    with patch.object(studio_tools.httpx, "AsyncClient", _Client):
        out = await studio_tools.preview({"enhancement_id": "abc"})
    assert out.get("isError") is True


# --------------------------------------------------------------- publish -----


@pytest.mark.asyncio
async def test_publish_updates_status() -> None:
    conn = _FakeConn(fetchone={"id": "abc"})
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        with patch("spec2sphere.dsp_ai.events.emit", AsyncMock()):
            out = await studio_tools.publish({"enhancement_id": "abc"})
    assert "Published" in out["content"][0]["text"]


@pytest.mark.asyncio
async def test_publish_404() -> None:
    conn = _FakeConn(fetchone=None)
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.publish({"enhancement_id": "missing"})
    assert out.get("isError") is True


@pytest.mark.asyncio
async def test_publish_missing_id() -> None:
    out = await studio_tools.publish({})
    assert out.get("isError") is True


# ---------------------------------------------------------- query_brain ------


@pytest.mark.asyncio
async def test_query_brain_rejects_writes() -> None:
    out = await studio_tools.query_brain({"cypher": "CREATE (n) RETURN n"})
    assert out.get("isError") is True


@pytest.mark.asyncio
async def test_query_brain_rejects_merge() -> None:
    out = await studio_tools.query_brain({"cypher": "MATCH (n) MERGE (n)-[:X]->() RETURN n"})
    assert out.get("isError") is True


@pytest.mark.asyncio
async def test_query_brain_passes_match() -> None:
    with patch("spec2sphere.dsp_ai.brain.client.run", AsyncMock(return_value=[{"x": 1}])):
        out = await studio_tools.query_brain({"cypher": "MATCH (n) RETURN n LIMIT 1"})
    text = out["content"][0]["text"]
    assert "1 row" in text


@pytest.mark.asyncio
async def test_query_brain_empty_cypher() -> None:
    out = await studio_tools.query_brain({"cypher": "   "})
    assert out.get("isError") is True


# -------------------------------------------------------- generation_log -----


@pytest.mark.asyncio
async def test_generation_log_empty() -> None:
    conn = _FakeConn(fetchall=[])
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.generation_log({})
    assert "No generations" in out["content"][0]["text"]


@pytest.mark.asyncio
async def test_generation_log_renders_rows() -> None:
    conn = _FakeConn(
        fetchall=[
            {
                "created_at": datetime.datetime(2026, 4, 17, 10, 0, 0),
                "model": "gpt-4o",
                "latency_ms": 420,
                "user_id": "user1",
                "preview": True,
                "error_kind": None,
            }
        ]
    )
    with patch.object(studio_tools.asyncpg, "connect", _connect_returning(conn)):
        out = await studio_tools.generation_log({})
    text = out["content"][0]["text"]
    assert "gpt-4o" in text
    assert "420ms" in text


# -------------------------------------------- registration smoke test -------


def test_all_8_tools_registered_in_mcp_server() -> None:
    """Smoke — confirm we haven't forgotten a descriptor."""
    from spec2sphere.copilot.mcp_server import _TOOLS

    names = {t["name"] for t in _TOOLS}
    expected = {
        "studio_list_enhancements",
        "studio_get_enhancement",
        "studio_create_enhancement",
        "studio_update_enhancement",
        "studio_preview",
        "studio_publish",
        "studio_query_brain",
        "studio_generation_log",
    }
    assert expected.issubset(names)


def test_existing_7_tools_still_registered() -> None:
    """Guard — existing tools must not be disturbed."""
    from spec2sphere.copilot.mcp_server import _TOOLS

    names = {t["name"] for t in _TOOLS}
    original = {
        "search_knowledge",
        "get_object_details",
        "get_quality_summary",
        "list_standards",
        "get_standard",
        "get_migration_guide",
        "get_architecture_overview",
    }
    assert original.issubset(names)
