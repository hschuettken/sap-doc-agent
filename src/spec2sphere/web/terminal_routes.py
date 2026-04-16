"""Terminal routes: agent session manager UI + API + WebSocket stream.

Provides:
  GET  /ui/agent-terminal                   — main viewer page
  GET  /api/agent-terminal/sessions         — JSON list of all sessions
  POST /api/agent-terminal/sessions         — create a new agent session
  GET  /api/agent-terminal/sessions/{id}    — get session details
  DELETE /api/agent-terminal/sessions/{id}  — kill session
  GET  /api/agent-terminal/sessions/{id}/output — last N lines of output
  WS   /ws/agent-terminal/{id}             — live terminal stream
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


def _render(request: Request, template_name: str, ctx: dict) -> HTMLResponse:
    """Render a partial template from the partials/ subdirectory."""
    ctx["request"] = request
    ctx.setdefault("active_page", "agent-terminal")
    return _templates.TemplateResponse(request, f"partials/{template_name}", ctx)


def create_terminal_routes() -> APIRouter:
    """Return an APIRouter with agent terminal viewer routes."""
    router = APIRouter()

    # ── UI: Main terminal viewer page ─────────────────────────────────────

    @router.get("/ui/agent-terminal", response_class=HTMLResponse)
    async def agent_terminal_page(request: Request, session_id: Optional[str] = None):
        """Agent terminal viewer — list sessions and optionally open one."""
        from spec2sphere.agent_terminal.manager import get_manager  # noqa: PLC0415

        manager = get_manager()
        sessions = [s.to_dict() for s in manager.list_sessions()]

        selected = None
        if session_id:
            s = manager.get_session(session_id)
            selected = s.to_dict() if s else None
        elif sessions:
            selected = sessions[0]

        return _render(
            request,
            "agent_terminal.html",
            {
                "sessions": sessions,
                "selected": selected,
                "active_page": "agent-terminal",
            },
        )

    # ── API: List sessions ────────────────────────────────────────────────

    @router.get("/api/agent-terminal/sessions")
    async def list_sessions():
        """Return all agent sessions as JSON."""
        from spec2sphere.agent_terminal.manager import get_manager  # noqa: PLC0415

        manager = get_manager()
        return JSONResponse([s.to_dict() for s in manager.list_sessions()])

    # ── API: Create session ───────────────────────────────────────────────

    @router.post("/api/agent-terminal/sessions")
    async def create_session(request: Request):
        """Create a new agent session. Body: {name, description, command}."""
        from spec2sphere.agent_terminal.manager import get_manager  # noqa: PLC0415

        body = await request.json()
        name = body.get("name", "").strip()
        description = body.get("description", "").strip()
        command = body.get("command", "").strip()

        if not name:
            return JSONResponse({"error": "name is required"}, status_code=400)
        if not command:
            return JSONResponse({"error": "command is required"}, status_code=400)

        manager = get_manager()
        session = manager.create_session(name=name, description=description, command=command)
        return JSONResponse(session.to_dict(), status_code=201)

    # ── API: Get session ──────────────────────────────────────────────────

    @router.get("/api/agent-terminal/sessions/{session_id}")
    async def get_session(session_id: str):
        """Get a session by ID."""
        from spec2sphere.agent_terminal.manager import get_manager  # noqa: PLC0415

        manager = get_manager()
        session = manager.get_session(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return JSONResponse(session.to_dict())

    # ── API: Kill session ─────────────────────────────────────────────────

    @router.delete("/api/agent-terminal/sessions/{session_id}")
    async def kill_session(session_id: str):
        """Kill a running agent session."""
        from spec2sphere.agent_terminal.manager import get_manager  # noqa: PLC0415

        manager = get_manager()
        ok = manager.kill_session(session_id)
        if not ok:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return JSONResponse({"status": "killed", "session_id": session_id})

    # ── API: Get output ───────────────────────────────────────────────────

    @router.get("/api/agent-terminal/sessions/{session_id}/output")
    async def get_output(session_id: str, lines: int = 100):
        """Get the last N lines of output from a session's tmux pane."""
        from spec2sphere.agent_terminal.manager import get_manager  # noqa: PLC0415

        manager = get_manager()
        session = manager.get_session(session_id)
        if not session:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        output = manager.read_output(session_id, lines=min(lines, 1000))
        return JSONResponse({"session_id": session_id, "output": output, "lines": lines})

    # ── WebSocket: live terminal stream ───────────────────────────────────

    @router.websocket("/ws/agent-terminal/{session_id}")
    async def terminal_ws(websocket: WebSocket, session_id: str):
        """Stream tmux output to the browser via WebSocket."""
        from spec2sphere.agent_terminal.ws_proxy import stream_terminal  # noqa: PLC0415

        await stream_terminal(websocket, session_id)

    return router
