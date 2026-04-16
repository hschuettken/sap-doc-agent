"""Copilot Integration routes: knowledge hub web pages, REST API, and MCP server.

Web pages (/copilot/*) are unauthenticated — they are crawlable by MS Copilot.
REST API (/api/copilot/*) is also unauthenticated.
MCP endpoints (/mcp/*) are unauthenticated — MCP clients handle their own auth.

Auth middleware only protects /ui/* so these routes bypass it automatically.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from spec2sphere.copilot.content_hub import ContentHub

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

# Singleton hub (cheap — reads lazily)
_hub = ContentHub()


def _render_standalone(request: Request, template_name: str, ctx: dict) -> HTMLResponse:
    """Render a template from the templates root (not partials/)."""
    ctx["request"] = request
    return _templates.TemplateResponse(request, template_name, ctx)


def create_copilot_routes() -> APIRouter:
    """Create and return the copilot routes router."""
    router = APIRouter(tags=["copilot"])

    # ---------------------------------------------------------------- web pages --

    @router.get("/copilot", response_class=HTMLResponse, include_in_schema=False)
    async def copilot_hub(request: Request):
        """Copilot knowledge hub — landing page for MS Copilot crawling."""
        index = _hub.get_index()
        return _render_standalone(request, "copilot_standalone.html", {"page": "hub", "index": index})

    @router.get("/copilot/sitemap.xml", response_class=Response, include_in_schema=False)
    async def copilot_sitemap():
        """Sitemap for all copilot knowledge pages."""
        urls = ["<url><loc>/copilot</loc><priority>1.0</priority></url>"]
        index = _hub.get_index()
        for section in index.get("sections", []):
            sid = section["id"]
            urls.append(f"<url><loc>/copilot/{sid}</loc><priority>0.9</priority></url>")
            sec = _hub.get_section(sid)
            if sec:
                for page in sec.get("pages", []):
                    urls.append(f"<url><loc>/copilot/{sid}/{page['id']}</loc><priority>0.7</priority></url>")
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(urls) + "</urlset>"
        )
        return Response(content=xml, media_type="application/xml")

    @router.get("/copilot/search", response_class=HTMLResponse, include_in_schema=False)
    async def copilot_search_page(request: Request, q: str = Query(""), section: Optional[str] = Query(None)):
        """Search results page (HTML)."""
        results = _hub.search(q, section=section) if q else []
        return _render_standalone(
            request,
            "copilot_standalone.html",
            {"page": "search", "query": q, "section_filter": section, "results": results},
        )

    @router.get("/copilot/{section_id}", response_class=HTMLResponse, include_in_schema=False)
    async def copilot_section(request: Request, section_id: str):
        """Section listing page."""
        section = _hub.get_section(section_id)
        if section is None:
            raise _not_found(f"Section not found: {section_id}")
        return _render_standalone(
            request,
            "copilot_standalone.html",
            {"page": "section", "section": section},
        )

    @router.get("/copilot/{section_id}/{page_id}", response_class=HTMLResponse, include_in_schema=False)
    async def copilot_page(request: Request, section_id: str, page_id: str):
        """Individual content page."""
        page = _hub.get_page(section_id, page_id)
        if page is None:
            raise _not_found(f"Page not found: {section_id}/{page_id}")
        return _render_standalone(
            request,
            "copilot_standalone.html",
            {"page": "content", "content_page": page},
        )

    # ---------------------------------------------------------------- REST API --

    @router.get(
        "/api/copilot/sections",
        summary="List all knowledge sections",
        operation_id="listCopilotSections",
    )
    async def api_list_sections():
        """Return all sections with metadata and page counts."""
        index = _hub.get_index()
        return JSONResponse(index)

    @router.get(
        "/api/copilot/sections/{section_id}",
        summary="Get a section with its page list",
        operation_id="getCopilotSection",
    )
    async def api_get_section(section_id: str):
        """Return a section and its pages."""
        section = _hub.get_section(section_id)
        if section is None:
            return JSONResponse({"error": f"Section not found: {section_id}"}, status_code=404)
        return JSONResponse(section)

    @router.get(
        "/api/copilot/sections/{section_id}/{page_id}",
        summary="Get a page with full content",
        operation_id="getCopilotPage",
    )
    async def api_get_page(section_id: str, page_id: str):
        """Return page content as markdown + rendered HTML."""
        page = _hub.get_page(section_id, page_id)
        if page is None:
            return JSONResponse({"error": f"Page not found: {section_id}/{page_id}"}, status_code=404)
        return JSONResponse(page)

    @router.get(
        "/api/copilot/search",
        summary="Search across all knowledge content",
        operation_id="searchCopilot",
    )
    async def api_search(
        q: str = Query(..., description="Search query"),
        section: Optional[str] = Query(None, description="Limit to section"),
    ):
        """Full-text search across all or one section."""
        results = _hub.search(q, section=section)
        return JSONResponse({"query": q, "section": section, "results": results, "count": len(results)})

    # ---------------------------------------------------------------- MCP -------

    @router.get("/mcp/sse", include_in_schema=False)
    async def mcp_sse_connect(request: Request):
        """SSE channel for MCP clients.

        Client connects via GET. Server sends an 'endpoint' event with the
        message POST URL. Client then POSTs JSON-RPC messages to /mcp/messages.
        """
        from fastapi.responses import StreamingResponse
        from spec2sphere.copilot.mcp_server import create_session, sse_event_stream

        session_id = create_session()

        async def _stream():
            async for chunk in sse_event_stream(session_id, _hub):
                yield chunk

        return StreamingResponse(
            _stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @router.post("/mcp/sse", include_in_schema=False)
    async def mcp_sse_post(request: Request):
        """Stateless JSON-RPC endpoint (POST /mcp/sse).

        Accepts a JSON-RPC message and returns the response directly.
        Simpler than the SSE session model — good for testing and simple clients.
        """
        from spec2sphere.copilot.mcp_server import MCPHandler

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                status_code=400,
            )
        handler = MCPHandler(_hub)
        result = await handler.handle_message(body)
        if not result:
            # Notification — no response
            return Response(status_code=204)
        return JSONResponse(result)

    @router.post("/mcp/messages", include_in_schema=False)
    async def mcp_messages(request: Request):
        """JSON-RPC message endpoint for SSE-connected clients.

        Client posts a message here; response is delivered via the SSE channel.
        """
        from spec2sphere.copilot.mcp_server import MCPHandler, deliver_to_session

        session_id = request.query_params.get("session_id")
        if not session_id:
            return JSONResponse({"error": "session_id required"}, status_code=400)

        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}},
                status_code=400,
            )

        handler = MCPHandler(_hub)
        result = await handler.handle_message(body)

        if result:
            sent = await deliver_to_session(session_id, result)
            if not sent:
                # Session expired — return inline
                return JSONResponse(result)

        return Response(status_code=202)

    return router


def _not_found(detail: str):
    from fastapi import HTTPException

    return HTTPException(status_code=404, detail=detail)
