"""Server-Sent Events endpoints for frontend state updates.

Replaces the legacy setInterval/setTimeout polling loops in browser_viewer
and agent_terminal. Backed by Postgres LISTEN/NOTIFY — publishers emit on
the relevant channel via ``spec2sphere.dsp_ai.events.emit``; this router
fans events out over SSE.

Channels:
- ``factory_status_changed`` — emitted whenever the active factory task
  changes; browser_viewer re-fetches ``/api/factory/active`` on receipt.
- ``agent_session_changed`` — emitted by the agent terminal whenever a
  session is created, status changes, or is deleted.

Fallback: if subscribe() throws (Postgres unreachable), the client gets
an `error` event; the template's JS retries automatically.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


async def _stream(channel: str):
    """Yield SSE events for a Postgres NOTIFY channel, with heartbeat."""
    try:
        from spec2sphere.dsp_ai.events import subscribe
    except Exception:
        yield {"event": "error", "data": json.dumps({"reason": "events module unavailable"})}
        return
    queue: asyncio.Queue = asyncio.Queue()

    async def _pump():
        try:
            async for ev in subscribe(channel):
                await queue.put(ev)
        except Exception:
            logger.exception("events subscribe failed for %s", channel)

    task = asyncio.create_task(_pump())
    try:
        while True:
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=25.0)
                yield {"event": "update", "data": json.dumps(ev)}
            except asyncio.TimeoutError:
                # Send a keepalive comment so proxies don't close the stream
                yield {"event": "ping", "data": "{}"}
    finally:
        task.cancel()


@router.get("/browser")
async def browser_events() -> EventSourceResponse:
    """SSE stream for browser_viewer — fires when factory task changes."""
    return EventSourceResponse(_stream("factory_status_changed"))


@router.get("/agent-sessions")
async def agent_session_events() -> EventSourceResponse:
    """SSE stream for agent_terminal — fires when session list changes."""
    return EventSourceResponse(_stream("agent_session_changed"))
