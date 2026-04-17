"""Tests for AI Studio polish: template library, generation log, brain explorer."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


def _make_app() -> FastAPI:
    """Build a minimal FastAPI app with the full AI Studio router mounted.

    Called inside each test (not at module level) so env monkey-patches and
    SEEDS_DIR patches applied before this call take effect.
    """
    from spec2sphere.web.ai_studio.routes import create_ai_studio_router

    app = FastAPI()
    app.include_router(create_ai_studio_router())
    return app


# ---------------------------------------------------------------------------
# Template Library
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_template_library_lists_seeds(tmp_path: Path, monkeypatch) -> None:
    """GET /ai-studio/templates/ renders seed template names."""
    seed_a = {"name": "Alpha Brief", "kind": "briefing", "render_hint": "brief", "mode": "batch"}
    seed_b = {"name": "Beta Ranking", "kind": "ranking", "render_hint": "table", "mode": "streaming"}
    (tmp_path / "alpha.json").write_text(json.dumps(seed_a))
    (tmp_path / "beta.json").write_text(json.dumps(seed_b))

    monkeypatch.setenv("SEEDS_DIR", str(tmp_path))
    # Re-import module so _SEEDS_DIR picks up the env change
    import importlib
    import spec2sphere.web.ai_studio.templates_library as tl_mod

    importlib.reload(tl_mod)

    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/ai-studio/templates/")

    assert r.status_code == 200
    assert "Alpha Brief" in r.text
    assert "Beta Ranking" in r.text


@pytest.mark.asyncio
async def test_template_fork_creates_draft_and_redirects(tmp_path: Path, monkeypatch) -> None:
    """POST /ai-studio/templates/{slug}/fork inserts a draft row and returns 303."""
    seed = {
        "name": "Morning Brief — Revenue",
        "kind": "briefing",
        "render_hint": "brief",
        "mode": "batch",
        "prompt_template": "hi",
    }
    slug = "morning_brief_revenue"
    (tmp_path / f"{slug}.json").write_text(json.dumps(seed))

    monkeypatch.setenv("SEEDS_DIR", str(tmp_path))

    import importlib
    import spec2sphere.web.ai_studio.templates_library as tl_mod

    importlib.reload(tl_mod)

    executed_args: list = []

    class FakeConn:
        async def execute(self, *args):
            executed_args.extend(args)

        async def close(self):
            pass

    async def fake_connect(dsn):
        return FakeConn()

    with patch("spec2sphere.dsp_ai.db.asyncpg.connect", side_effect=fake_connect):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(f"/ai-studio/templates/{slug}/fork", follow_redirects=False)

    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/ai-studio/")
    assert location.endswith("/edit")

    # Extract the new UUID from the redirect location: /ai-studio/{uuid}/edit
    parts = location.rstrip("/").split("/")
    # parts: ['', 'ai-studio', '{uuid}', 'edit']
    new_id = parts[-2]
    assert len(new_id) == 36  # valid UUID

    # INSERT was called with the right args
    assert any("INSERT INTO dsp_ai.enhancements" in str(a) for a in executed_args)
    # Forked name includes "(copy)"
    assert any("(copy)" in str(a) for a in executed_args)


# ---------------------------------------------------------------------------
# Generation Log
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generation_log_filters_by_since_hours(monkeypatch) -> None:
    """GET /ai-studio/log/?since_hours=1 returns 200 with rows rendered."""
    gen_id_1 = str(uuid.uuid4())
    gen_id_2 = str(uuid.uuid4())
    enh_id = str(uuid.uuid4())

    from datetime import datetime, timezone

    fake_rows = [
        {
            "id": gen_id_1,
            "enhancement_id": enh_id,
            "user_id": "u1",
            "context_key": "ctx-a",
            "model": "gpt-4o",
            "quality_level": "high",
            "latency_ms": 320,
            "cost_usd": 0.0012,
            "cached": False,
            "quality_warnings": [],
            "error_kind": None,
            "preview": True,
            "created_at": datetime.now(timezone.utc),
            "enh_name": "Revenue Brief",
        },
        {
            "id": gen_id_2,
            "enhancement_id": enh_id,
            "user_id": "u2",
            "context_key": "ctx-b",
            "model": "claude-3-sonnet",
            "quality_level": "medium",
            "latency_ms": 510,
            "cost_usd": 0.0035,
            "cached": False,
            "quality_warnings": ["low_confidence"],
            "error_kind": None,
            "preview": False,
            "created_at": datetime.now(timezone.utc),
            "enh_name": "Revenue Brief",
        },
    ]

    class FakeConn:
        async def execute(self, *args):
            pass  # GUC set_config no-op

        async def fetch(self, *args):
            # Return plain dicts; generation_log.py does dict(r) for r in rows
            return fake_rows

        async def close(self):
            pass

    async def fake_connect(dsn):
        return FakeConn()

    with patch("spec2sphere.dsp_ai.db.asyncpg.connect", side_effect=fake_connect):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get("/ai-studio/log/?since_hours=1")

    assert r.status_code == 200
    assert "gpt-4o" in r.text
    assert "claude-3-sonnet" in r.text


@pytest.mark.asyncio
async def test_generation_detail_fetches_why_from_dspai(monkeypatch) -> None:
    """GET /ai-studio/log/{gen_id} calls dsp-ai /v1/why and renders narrative."""
    gen_id = "gen-abc-123"
    monkeypatch.setenv("DSPAI_URL", "http://fake-dsp:8000")

    why_payload = {
        "narrative": "Revenue grew 12% last week driven by EMEA region.",
        "provenance": {"model": "gpt-4o", "latency_ms": 400, "cost_usd": 0.0015},
        "quality_warnings": [],
        "brain_hops": [],
    }

    class FakeResponse:
        status_code = 200

        def json(self):
            return why_payload

    class FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url):
            return FakeResponse()

    with patch("spec2sphere.web.ai_studio.generation_log.httpx.AsyncClient", return_value=FakeAsyncClient()):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/ai-studio/log/{gen_id}")

    assert r.status_code == 200
    assert "Revenue grew 12%" in r.text


# ---------------------------------------------------------------------------
# Brain Explorer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_brain_query_rejects_write_cypher() -> None:
    """POST /ai-studio/brain/query with CREATE cypher returns 400."""
    app = _make_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/ai-studio/brain/query",
            json={"cypher": "CREATE (n) RETURN n"},
        )
    assert r.status_code == 400
    assert "read-only" in r.text.lower()


@pytest.mark.asyncio
async def test_brain_query_allows_match() -> None:
    """POST /ai-studio/brain/query with MATCH returns 200 with rows."""
    fake_rows = [{"n": {"id": "x", "name": "X"}}]

    async def fake_brain_run(cypher, **kwargs):
        return fake_rows

    with patch("spec2sphere.dsp_ai.brain.client.run", side_effect=fake_brain_run):
        app = _make_app()
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.post(
                "/ai-studio/brain/query",
                json={"cypher": "MATCH (n) RETURN n LIMIT 1"},
            )

    assert r.status_code == 200
    data = r.json()
    assert "rows" in data
