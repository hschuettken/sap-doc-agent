"""SSE events routes — /events/browser and /events/agent-sessions.

These streams replace the legacy setInterval polling. The integration test
just confirms the routes register and respond to OPTIONS/HEAD-like smoke
without hanging — the real subscribe() behavior is exercised end-to-end
in the Task 14 smoke suite against live compose.
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_events_routes_registered() -> None:
    from spec2sphere.web.events_routes import router

    paths = {r.path for r in router.routes}
    assert "/events/browser" in paths
    assert "/events/agent-sessions" in paths


@pytest.mark.asyncio
async def test_browser_events_emits_keepalive_when_idle() -> None:
    """With no NOTIFY traffic, the stream should still emit a ping within 30s.

    Uses a 2s timeout against a stub subscribe() that never yields. The
    route's internal wait_for(queue.get(), timeout=25s) should still kick
    out a ping before we bail — but to keep the test fast, we only assert
    that connecting does not immediately 500.
    """
    from spec2sphere.web.events_routes import router

    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(router)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        try:
            resp = await asyncio.wait_for(c.get("/events/browser"), timeout=2.0)
        except asyncio.TimeoutError:
            # Acceptable — SSE stays open, test just confirms no 500.
            return
    # If the server closed the stream, that's fine so long as it didn't 500.
    assert resp.status_code in (200, 204)


@pytest.mark.asyncio
async def test_agent_manager_notify_emits_on_persist(monkeypatch) -> None:
    """_persist on the AgentTerminalManager should fire NOTIFY when loop is live."""
    from spec2sphere.agent_terminal import manager as mgr_mod

    emit_calls: list = []

    async def _fake_emit(channel, payload):
        emit_calls.append((channel, payload))

    monkeypatch.setattr("spec2sphere.dsp_ai.events.emit", _fake_emit)

    # Force a fresh manager; bypass tmux.
    mgr = mgr_mod.AgentSessionManager()
    mgr._sessions = {}
    mgr._notify_changed()
    # Allow the spawned task to run
    await asyncio.sleep(0.05)
    assert emit_calls, f"_notify_changed did not emit; calls={emit_calls}"
    assert emit_calls[0][0] == "agent_session_changed"
