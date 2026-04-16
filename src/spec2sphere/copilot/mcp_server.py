"""Lightweight MCP (Model Context Protocol) server over SSE.

Implements JSON-RPC 2.0 with SSE transport as required by MCP 2024-11-05.
No external MCP SDK dependency — the protocol is implemented directly.

Endpoint layout:
  GET  /mcp/sse      — SSE channel (client connects here to receive events)
  POST /mcp/messages — Client POSTs JSON-RPC messages; responses go back over SSE

Alternatively a single POST /mcp/sse endpoint can be used for stateless requests:
  POST /mcp/sse with JSON body → JSON response (simpler for testing)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator

logger = logging.getLogger(__name__)

# ------------------------------------------------------------ protocol defs --

MCP_PROTOCOL_VERSION = "2024-11-05"

_CAPABILITIES = {
    "experimental": {},
    "logging": {},
    "prompts": {"listChanged": False},
    "resources": {"subscribe": False, "listChanged": False},
    "tools": {"listChanged": False},
}

_SERVER_INFO = {
    "name": "spec2sphere-mcp",
    "version": "2.0.0",
}

# ------------------------------------------------------------ tool registry --

_TOOLS = [
    {
        "name": "search_knowledge",
        "description": (
            "Search across all Spec2Sphere knowledge: best practices, DSP quirks, "
            "HANA SQL patterns, UI mappings, architecture, standards, migration guides, "
            "and glossary. Returns matching pages with excerpts."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "section": {
                    "type": "string",
                    "description": "Optional: limit to a section (knowledge, standards, architecture, migration, quality, glossary)",
                    "enum": ["knowledge", "standards", "architecture", "migration", "quality", "glossary"],
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_object_details",
        "description": "Get full documentation for a scanned SAP object by its ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "object_id": {"type": "string", "description": "SAP object identifier"},
            },
            "required": ["object_id"],
        },
    },
    {
        "name": "get_quality_summary",
        "description": "Get current documentation quality metrics and top issues.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_standards",
        "description": "List all Horvath delivery standards available in Spec2Sphere.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_standard",
        "description": "Get the full content of a specific Horvath standard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "standard_name": {
                    "type": "string",
                    "description": "Standard name (e.g. 'documentation_standard', 'quality_gates_standard')",
                },
            },
            "required": ["standard_name"],
        },
    },
    {
        "name": "get_migration_guide",
        "description": "Get migration guidance for SAP BW to Datasphere migration.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Specific topic: 'bw-to-datasphere', 'object-classification', 'validation-checklist'",
                },
            },
        },
    },
    {
        "name": "get_architecture_overview",
        "description": "Get the 4-layer architecture overview, naming conventions, and design patterns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Specific topic: 'overview', 'naming-conventions', 'persistence-strategy', 'design-patterns'",
                },
            },
        },
    },
]

# --------------------------------------------------------- resource registry -


def _build_resource_list(hub) -> list[dict]:
    """Build the resource list from the content hub."""
    resources = []
    try:
        index = hub.get_index()
        for section in index.get("sections", []):
            sid = section["id"]
            sec = hub.get_section(sid)
            if not sec:
                continue
            for page in sec.get("pages", []):
                pid = page["id"]
                resources.append(
                    {
                        "uri": f"spec2sphere://{sid}/{pid}",
                        "name": page["title"],
                        "description": page.get("excerpt", ""),
                        "mimeType": "text/markdown",
                    }
                )
    except Exception as exc:
        logger.warning("Could not build resource list: %s", exc)
    return resources


# ------------------------------------------------------------ MCPHandler -----


class MCPHandler:
    """Lightweight MCP JSON-RPC 2.0 handler.

    Instances are created per-request (stateless). The ContentHub is
    passed in at construction so handlers can use it.
    """

    def __init__(self, hub) -> None:
        from spec2sphere.copilot.content_hub import ContentHub  # local import, avoid circulars

        self._hub: ContentHub = hub

    async def handle_message(self, message: dict) -> dict:
        """Route a JSON-RPC message to the appropriate handler."""
        msg_id = message.get("id")
        method = message.get("method", "")
        params = message.get("params") or {}

        try:
            if method == "initialize":
                result = self._initialize(params)
            elif method == "initialized":
                # Notification, no response needed
                return {}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = self._list_tools(params)
            elif method == "tools/call":
                result = await self._call_tool(params)
            elif method == "resources/list":
                result = self._list_resources(params)
            elif method == "resources/read":
                result = await self._read_resource(params)
            elif method == "prompts/list":
                result = {"prompts": []}
            else:
                return self._error(msg_id, -32601, f"Method not found: {method}")

            return {"jsonrpc": "2.0", "id": msg_id, "result": result}

        except Exception as exc:
            logger.exception("MCP handler error for method %s", method)
            return self._error(msg_id, -32603, str(exc))

    # --------------------------------------------------------- handlers ------

    def _initialize(self, params: dict) -> dict:
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": _CAPABILITIES,
            "serverInfo": _SERVER_INFO,
            "instructions": (
                "Spec2Sphere Knowledge Hub — authoritative reference for SAP Datasphere "
                "and SAC delivery by Horvath Analytics. Use search_knowledge for general "
                "queries, get_architecture_overview for design patterns, get_standard for "
                "compliance checks, and get_migration_guide for BW→DSP migration guidance."
            ),
        }

    def _list_tools(self, params: dict) -> dict:
        return {"tools": _TOOLS}

    async def _call_tool(self, params: dict) -> dict:
        name = params.get("name", "")
        args = params.get("arguments") or {}

        if name == "search_knowledge":
            return await self._tool_search_knowledge(args)
        elif name == "get_object_details":
            return await self._tool_get_object(args)
        elif name == "get_quality_summary":
            return await self._tool_quality_summary(args)
        elif name == "list_standards":
            return await self._tool_list_standards(args)
        elif name == "get_standard":
            return await self._tool_get_standard(args)
        elif name == "get_migration_guide":
            return await self._tool_migration_guide(args)
        elif name == "get_architecture_overview":
            return await self._tool_architecture(args)
        else:
            return self._tool_error(f"Unknown tool: {name}")

    def _list_resources(self, params: dict) -> dict:
        resources = _build_resource_list(self._hub)
        return {"resources": resources}

    async def _read_resource(self, params: dict) -> dict:
        uri = params.get("uri", "")
        # Expected format: spec2sphere://{section}/{page}
        if not uri.startswith("spec2sphere://"):
            return self._resource_error(uri, "Invalid URI scheme")
        path = uri.replace("spec2sphere://", "")
        parts = path.split("/", 1)
        if len(parts) != 2:
            return self._resource_error(uri, "URI must be spec2sphere://{section}/{page}")
        section_id, page_id = parts
        page = self._hub.get_page(section_id, page_id)
        if page is None:
            return self._resource_error(uri, f"Resource not found: {uri}")
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "text/markdown",
                    "text": page["content_md"],
                }
            ]
        }

    # ------------------------------------------------------ tool impls -------

    async def _tool_search_knowledge(self, args: dict) -> dict:
        query = args.get("query", "")
        section = args.get("section")
        if not query:
            return self._tool_error("query is required")
        results = self._hub.search(query, section=section)
        if not results:
            text = f"No results found for '{query}'."
        else:
            lines = [f"Found {len(results)} result(s) for '{query}':\n"]
            for r in results[:10]:
                lines.append(f"**{r['title']}** ({r['section_title']})")
                lines.append(f"URL: {r['url']}")
                lines.append(f"{r['snippet']}\n")
            text = "\n".join(lines)
        return {"content": [{"type": "text", "text": text}]}

    async def _tool_get_object(self, args: dict) -> dict:
        object_id = args.get("object_id", "")
        if not object_id:
            return self._tool_error("object_id is required")
        # Try to load from output/objects filesystem

        from spec2sphere.copilot.content_hub import _PROJECT_ROOT

        output_dir = _PROJECT_ROOT / "output" / "objects"
        if output_dir.exists():
            for type_dir in output_dir.iterdir():
                md_path = type_dir / f"{object_id}.md"
                if md_path.exists():
                    content = md_path.read_text(encoding="utf-8")
                    return {"content": [{"type": "text", "text": content}]}
        # Try DB
        try:
            from spec2sphere.db import _get_conn

            conn = await _get_conn()
            try:
                row = await conn.fetchrow("SELECT * FROM technical_objects WHERE name = $1 LIMIT 1", object_id)
                if row:
                    data = dict(row)
                    text = f"# {data.get('name', object_id)}\n\n"
                    text += f"**Type:** {data.get('object_type', 'Unknown')}\n"
                    text += f"**Layer:** {data.get('layer', 'Unknown')}\n"
                    if data.get("description"):
                        text += f"\n{data['description']}\n"
                    return {"content": [{"type": "text", "text": text}]}
            finally:
                await conn.close()
        except Exception:
            pass
        return self._tool_error(f"Object not found: {object_id}")

    async def _tool_quality_summary(self, args: dict) -> dict:
        from spec2sphere.copilot.content_hub import _PROJECT_ROOT

        summary_path = _PROJECT_ROOT / "output" / "reports" / "summary.md"
        if summary_path.exists():
            text = summary_path.read_text(encoding="utf-8")
        else:
            text = (
                "No quality report available yet. "
                "Run the documentation audit pipeline first to generate a quality summary."
            )
        return {"content": [{"type": "text", "text": text}]}

    async def _tool_list_standards(self, args: dict) -> dict:
        section = self._hub.get_section("standards")
        if not section or not section.get("pages"):
            return {"content": [{"type": "text", "text": "No standards found."}]}
        lines = ["# Available Horvath Standards\n"]
        for page in section["pages"]:
            lines.append(f"- **{page['title']}** — `{page['id']}`")
            if page.get("excerpt"):
                lines.append(f"  {page['excerpt']}")
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}

    async def _tool_get_standard(self, args: dict) -> dict:
        name = args.get("standard_name", "")
        if not name:
            return self._tool_error("standard_name is required")
        page = self._hub.get_page("standards", name)
        if page is None:
            return self._tool_error(f"Standard not found: {name}")
        return {"content": [{"type": "text", "text": page["content_md"]}]}

    async def _tool_migration_guide(self, args: dict) -> dict:
        topic = args.get("topic", "bw-to-datasphere")
        if not topic:
            topic = "bw-to-datasphere"
        page = self._hub.get_page("migration", topic)
        if page is None:
            # Return overview of available topics
            section = self._hub.get_section("migration")
            topics = [p["id"] for p in (section or {}).get("pages", [])]
            return self._tool_error(f"Topic '{topic}' not found. Available: {topics}")
        return {"content": [{"type": "text", "text": page["content_md"]}]}

    async def _tool_architecture(self, args: dict) -> dict:
        topic = args.get("topic", "overview")
        if not topic:
            topic = "overview"
        page = self._hub.get_page("architecture", topic)
        if page is None:
            section = self._hub.get_section("architecture")
            topics = [p["id"] for p in (section or {}).get("pages", [])]
            return self._tool_error(f"Topic '{topic}' not found. Available: {topics}")
        return {"content": [{"type": "text", "text": page["content_md"]}]}

    # ------------------------------------------------------------ helpers -----

    @staticmethod
    def _error(msg_id: Any, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        }

    @staticmethod
    def _tool_error(message: str) -> dict:
        return {
            "content": [{"type": "text", "text": f"Error: {message}"}],
            "isError": True,
        }

    @staticmethod
    def _resource_error(uri: str, message: str) -> dict:
        return {"contents": [{"uri": uri, "mimeType": "text/plain", "text": f"Error: {message}"}]}


# -------------------------------------------------------- SSE session store --

# Map session_id → asyncio.Queue for response delivery
_sessions: dict[str, asyncio.Queue] = {}


def create_session() -> str:
    """Create a new SSE session and return its ID."""
    session_id = str(uuid.uuid4())
    _sessions[session_id] = asyncio.Queue()
    return session_id


def drop_session(session_id: str) -> None:
    """Remove a session."""
    _sessions.pop(session_id, None)


async def deliver_to_session(session_id: str, data: dict) -> bool:
    """Put a message onto a session's queue. Returns False if session not found."""
    q = _sessions.get(session_id)
    if q is None:
        return False
    await q.put(data)
    return True


async def sse_event_stream(session_id: str, hub) -> AsyncGenerator[str, None]:
    """Generate SSE events for a session.

    Yields the endpoint event first (MCP spec requirement), then waits
    for messages placed on the session queue.
    """
    # MCP requires the server to send an 'endpoint' event with the messages URL
    endpoint_url = f"/mcp/messages?session_id={session_id}"
    yield f"event: endpoint\ndata: {json.dumps({'uri': endpoint_url})}\n\n"

    q = _sessions.get(session_id)
    if q is None:
        return

    try:
        while True:
            try:
                # Wait for a message with a timeout so the connection stays alive
                msg = await asyncio.wait_for(q.get(), timeout=30.0)
                if msg is None:
                    # Sentinel: close the stream
                    break
                yield f"event: message\ndata: {json.dumps(msg)}\n\n"
            except asyncio.TimeoutError:
                # Send a keepalive comment
                yield ": keepalive\n\n"
    except asyncio.CancelledError:
        pass
    finally:
        drop_session(session_id)
