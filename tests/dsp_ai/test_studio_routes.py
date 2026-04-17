"""Integration tests for the AI Studio CRUD + preview + publish routes.

Requires DATABASE_URL (the compose postgres with dsp_ai.* migrations
applied) — skipped otherwise. Preview is mocked via respx so tests
don't need a live dsp-ai service.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import asyncpg
import httpx
import pytest
import respx
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from spec2sphere.dsp_ai.settings import postgres_dsn
from spec2sphere.web.ai_studio.routes import create_ai_studio_router

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — integration test",
)


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    app.include_router(create_ai_studio_router())
    return app


@pytest.fixture(autouse=True)
async def _clean_enhancements():
    conn = await asyncpg.connect(postgres_dsn())
    try:
        await conn.execute("DELETE FROM dsp_ai.studio_audit")
        await conn.execute("DELETE FROM dsp_ai.briefings")
        await conn.execute("DELETE FROM dsp_ai.generations")
        await conn.execute("DELETE FROM dsp_ai.enhancements")
    finally:
        await conn.close()
    yield


@pytest.mark.asyncio
async def test_list_empty(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/ai-studio/")
    assert r.status_code == 200
    assert "AI Studio" in r.text
    assert "No enhancements yet" in r.text


@pytest.mark.asyncio
async def test_create_redirects_to_edit_and_persists(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/ai-studio/",
            data={"name": "Revenue Brief", "kind": "briefing"},
            follow_redirects=False,
        )
    assert r.status_code == 303
    loc = r.headers["location"]
    assert loc.startswith("/ai-studio/") and loc.endswith("/edit")

    conn = await asyncpg.connect(postgres_dsn())
    try:
        row = await conn.fetchrow("SELECT name, kind, status FROM dsp_ai.enhancements")
    finally:
        await conn.close()
    assert row["name"] == "Revenue Brief"
    assert row["kind"] == "briefing"
    assert row["status"] == "draft"


@pytest.mark.asyncio
async def test_edit_page_shows_config_json(app: FastAPI) -> None:
    conn = await asyncpg.connect(postgres_dsn())
    eid = str(uuid.uuid4())
    try:
        await conn.execute(
            "INSERT INTO dsp_ai.enhancements (id, name, kind, config, author) "
            "VALUES ($1::uuid, 'Test', 'narrative', $2::jsonb, 'h@example')",
            eid,
            '{"prompt_template": "x"}',
        )
    finally:
        await conn.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get(f"/ai-studio/{eid}/edit")
    assert r.status_code == 200
    assert "prompt_template" in r.text
    assert "Run preview" in r.text


@pytest.mark.asyncio
async def test_edit_unknown_id_404(app: FastAPI) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/ai-studio/00000000-0000-0000-0000-000000000000/edit")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_publish_flips_status_and_emits_notify(app: FastAPI, monkeypatch) -> None:
    from spec2sphere.dsp_ai.events import subscribe

    conn = await asyncpg.connect(postgres_dsn())
    eid = str(uuid.uuid4())
    try:
        await conn.execute(
            "INSERT INTO dsp_ai.enhancements (id, name, kind, config, author) "
            "VALUES ($1::uuid, 'T', 'narrative', '{}'::jsonb, 'h@example')",
            eid,
        )
    finally:
        await conn.close()

    received: list[dict] = []

    async def consume() -> None:
        async for ev in subscribe("enhancement_published"):
            received.append(ev)
            return

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.3)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(f"/ai-studio/{eid}/publish", follow_redirects=False)
    assert r.status_code == 303

    await asyncio.wait_for(task, timeout=3.0)
    assert received and received[0]["id"] == eid

    conn = await asyncpg.connect(postgres_dsn())
    try:
        row = await conn.fetchrow("SELECT status FROM dsp_ai.enhancements WHERE id = $1::uuid", eid)
        audit = await conn.fetchval("SELECT count(*) FROM dsp_ai.studio_audit WHERE action='publish'")
    finally:
        await conn.close()
    assert row["status"] == "published"
    assert audit == 1


@pytest.mark.asyncio
@respx.mock
async def test_preview_proxies_to_dsp_ai_with_preview_true(app: FastAPI, monkeypatch) -> None:
    monkeypatch.setenv("DSPAI_URL", "http://fake-dsp-ai:8000")
    fake_body = {"generation_id": "g-1", "content": {"narrative_text": "hello"}}
    route = respx.post("http://fake-dsp-ai:8000/v1/enhance/enh-123").mock(
        return_value=httpx.Response(200, json=fake_body)
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/ai-studio/enh-123/preview", json={"user": "h@example"})

    assert r.status_code == 200
    assert r.json() == fake_body
    import json as _json

    sent = route.calls[0].request
    forwarded = _json.loads(sent.content.decode())
    assert forwarded["preview"] is True
    assert forwarded["user"] == "h@example"


@pytest.mark.asyncio
async def test_non_author_denied_when_allowlist_set(app: FastAPI, monkeypatch) -> None:
    monkeypatch.setenv("STUDIO_AUTHOR_EMAILS", "owner@example.com")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post(
            "/ai-studio/",
            data={"name": "T", "kind": "narrative"},
            headers={"X-User-Email": "intruder@evil.com"},
        )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_update_config_validates_payload(app: FastAPI) -> None:
    conn = await asyncpg.connect(postgres_dsn())
    eid = str(uuid.uuid4())
    try:
        await conn.execute(
            "INSERT INTO dsp_ai.enhancements (id, name, kind, config, author) "
            "VALUES ($1::uuid, 'T', 'narrative', '{}'::jsonb, 'h@example')",
            eid,
        )
    finally:
        await conn.close()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        bad = await c.put(f"/ai-studio/{eid}/config", json={"name": "T"})  # missing required fields
        assert bad.status_code == 422

        good_cfg = {
            "name": "T",
            "kind": "narrative",
            "bindings": {"data": {"dsp_query": "SELECT 1"}},
            "prompt_template": "hi",
            "render_hint": "narrative_text",
        }
        ok = await c.put(f"/ai-studio/{eid}/config", json=good_cfg)
        assert ok.status_code == 200
