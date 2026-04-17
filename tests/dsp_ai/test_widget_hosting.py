"""Contract tests for /widget/* routes — served by dsp-ai service.

Uses a tmp dir as WIDGET_DIST_DIR so we don't depend on an actual
widget build being present in the CI environment.
"""

from __future__ import annotations


import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_manifest_returns_503_when_widget_not_built(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WIDGET_DIST_DIR", str(tmp_path))
    from spec2sphere.dsp_ai.service import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/widget/manifest.json")
    assert r.status_code == 503


@pytest.mark.asyncio
async def test_manifest_served_with_cors(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WIDGET_DIST_DIR", str(tmp_path))
    monkeypatch.setenv("WIDGET_ALLOWED_ORIGINS", "https://sac.example.com")
    monkeypatch.setenv("PUBLIC_API_BASE", "https://api.example.com")
    (tmp_path / "manifest.json").write_text('{"url":"{{API_BASE}}/widget/main.js"}')

    from spec2sphere.dsp_ai.service import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/widget/manifest.json")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://sac.example.com"
    assert "https://api.example.com/widget/main.js" in r.text  # template replaced


@pytest.mark.asyncio
async def test_main_js_served(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("WIDGET_DIST_DIR", str(tmp_path))
    (tmp_path / "main.js").write_text("(() => {})();")

    from spec2sphere.dsp_ai.service import create_app

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/widget/main.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/javascript")
    assert b"(() => {})" in r.content
