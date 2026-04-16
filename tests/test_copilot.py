"""Tests for the Copilot Integration module.

Covers:
- copilot_routes.py HTTP endpoints (/copilot/*, /api/copilot/*, /mcp/*)
- content_hub.py ContentHub unit behaviour
- mcp_server.py MCPHandler message handling
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from spec2sphere.web.server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def output_dir(tmp_path):
    """Minimal output directory so create_app succeeds."""
    graph = {
        "nodes": [
            {"id": "SPACE.OBJ1", "name": "OBJ1", "type": "view", "layer": "harmonized", "source_system": "DSP"},
        ],
        "edges": [],
    }
    (tmp_path / "graph.json").write_text(json.dumps(graph))
    obj_dir = tmp_path / "objects" / "view"
    obj_dir.mkdir(parents=True)
    (obj_dir / "SPACE.OBJ1.md").write_text("---\nobject_id: SPACE.OBJ1\nname: OBJ1\n---\n# OBJ1\nA test view.")
    (tmp_path / "reports").mkdir()
    return tmp_path


@pytest.fixture
def client(output_dir):
    """Unauthenticated client — /copilot/* and /api/copilot/* bypass auth."""
    app = create_app(output_dir=str(output_dir))
    return TestClient(app)


# ---------------------------------------------------------------------------
# Web page tests  (/copilot/*)
# ---------------------------------------------------------------------------


def test_copilot_hub_renders(client):
    """GET /copilot returns 200 with 'Knowledge Hub' in body."""
    resp = client.get("/copilot")
    assert resp.status_code == 200
    assert "Knowledge Hub" in resp.text


def test_copilot_section_knowledge(client):
    """GET /copilot/knowledge returns 200 — knowledge section exists."""
    resp = client.get("/copilot/knowledge")
    assert resp.status_code == 200


def test_copilot_section_not_found(client):
    """GET /copilot/nonexistent returns 404."""
    resp = client.get("/copilot/nonexistentsection99")
    assert resp.status_code == 404


def test_copilot_search_page(client):
    """GET /copilot/search?q=SAP returns 200 HTML."""
    resp = client.get("/copilot/search?q=SAP")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")


def test_copilot_search_page_empty_query(client):
    """GET /copilot/search with no query param still returns 200."""
    resp = client.get("/copilot/search")
    assert resp.status_code == 200


def test_copilot_sitemap(client):
    """GET /copilot/sitemap.xml returns XML with copilot URLs."""
    resp = client.get("/copilot/sitemap.xml")
    assert resp.status_code == 200
    assert "urlset" in resp.text
    assert "/copilot" in resp.text
    # Should include section URLs
    assert "/copilot/architecture" in resp.text or "/copilot/knowledge" in resp.text


# ---------------------------------------------------------------------------
# REST API tests  (/api/copilot/*)
# ---------------------------------------------------------------------------


def test_copilot_sections_api(client):
    """GET /api/copilot/sections returns 200 with sections list."""
    resp = client.get("/api/copilot/sections")
    assert resp.status_code == 200
    data = resp.json()
    assert "sections" in data
    assert isinstance(data["sections"], list)
    assert len(data["sections"]) > 0
    # All expected sections present
    section_ids = {s["id"] for s in data["sections"]}
    assert "architecture" in section_ids
    assert "knowledge" in section_ids
    assert "standards" in section_ids


def test_copilot_page_api(client):
    """GET /api/copilot/sections/architecture/overview returns 200 with content."""
    resp = client.get("/api/copilot/sections/architecture/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "content_html" in data
    assert len(data["content_html"]) > 0
    assert data["id"] == "overview"
    assert data["section_id"] == "architecture"


def test_copilot_page_not_found(client):
    """GET /api/copilot/sections/knowledge/nonexistent returns 404."""
    # knowledge section exists but this page doesn't
    resp = client.get("/api/copilot/sections/knowledge/nonexistent-page-xyz")
    assert resp.status_code == 404


def test_copilot_section_api_not_found(client):
    """GET /api/copilot/sections/doesnotexist returns 404."""
    resp = client.get("/api/copilot/sections/doesnotexist99")
    assert resp.status_code == 404


def test_copilot_search_api(client):
    """GET /api/copilot/search?q=SAP returns results."""
    resp = client.get("/api/copilot/search?q=SAP")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "SAP"
    assert "results" in data
    assert "count" in data
    # "SAP" appears in architecture content — expect at least one hit
    assert data["count"] >= 1


def test_copilot_search_empty(client):
    """GET /api/copilot/search?q=xyznonexistent returns empty results."""
    resp = client.get("/api/copilot/search?q=xyznonexistentterm999")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0
    assert data["results"] == []


def test_copilot_search_section_filter(client):
    """GET /api/copilot/search?q=layer&section=architecture scopes results."""
    resp = client.get("/api/copilot/search?q=layer&section=architecture")
    assert resp.status_code == 200
    data = resp.json()
    assert data["section"] == "architecture"
    # Every result should belong to the architecture section
    for result in data["results"]:
        assert result["section_id"] == "architecture"


# ---------------------------------------------------------------------------
# ContentHub unit tests
# ---------------------------------------------------------------------------


def test_content_hub_index():
    """ContentHub.get_index() returns dict with sections list."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    index = hub.get_index()
    assert isinstance(index, dict)
    assert "sections" in index
    assert "title" in index
    section_ids = {s["id"] for s in index["sections"]}
    assert "architecture" in section_ids
    assert "glossary" in section_ids


def test_content_hub_section():
    """ContentHub.get_section('architecture') returns dict with pages."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    section = hub.get_section("architecture")
    assert section is not None
    assert section["id"] == "architecture"
    assert "pages" in section
    assert len(section["pages"]) > 0
    # Check page structure
    page = section["pages"][0]
    assert "id" in page
    assert "title" in page
    assert "url" in page


def test_content_hub_section_not_found():
    """ContentHub.get_section() returns None for unknown section."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    assert hub.get_section("doesnotexist") is None


def test_content_hub_page():
    """ContentHub.get_page('architecture', 'overview') returns dict with content_html."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    page = hub.get_page("architecture", "overview")
    assert page is not None
    assert page["id"] == "overview"
    assert page["section_id"] == "architecture"
    assert "content_html" in page
    assert "content_md" in page
    assert len(page["content_html"]) > 0
    # Architecture overview mentions 4-layer content
    assert "layer" in page["content_md"].lower() or "Layer" in page["content_md"]


def test_content_hub_page_not_found():
    """ContentHub.get_page() returns None for unknown page."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    assert hub.get_page("architecture", "nonexistent-page") is None
    assert hub.get_page("nonexistent-section", "overview") is None


def test_content_hub_search():
    """ContentHub.search('layer') returns results from architecture content."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    results = hub.search("layer")
    assert isinstance(results, list)
    assert len(results) > 0
    # Check result structure
    r = results[0]
    assert "section_id" in r
    assert "page_id" in r
    assert "title" in r
    assert "snippet" in r
    assert "url" in r


def test_content_hub_search_empty_query():
    """ContentHub.search('') returns empty list."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    assert hub.search("") == []
    assert hub.search("   ") == []


def test_content_hub_search_no_results():
    """ContentHub.search() returns empty list when nothing matches."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    results = hub.search("xyznonexistentterm999abc")
    assert results == []


def test_content_hub_glossary_section():
    """ContentHub.get_section('glossary') returns alphabetical term pages."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    section = hub.get_section("glossary")
    assert section is not None
    assert len(section["pages"]) > 0
    # All page IDs should start with 'terms-'
    for page in section["pages"]:
        assert page["id"].startswith("terms-")


def test_content_hub_migration_pages():
    """ContentHub.get_section('migration') contains expected pages."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    section = hub.get_section("migration")
    assert section is not None
    page_ids = {p["id"] for p in section["pages"]}
    assert "bw-to-datasphere" in page_ids
    assert "validation-checklist" in page_ids


# ---------------------------------------------------------------------------
# MCPHandler unit tests
# ---------------------------------------------------------------------------


@pytest.fixture
def hub():
    from spec2sphere.copilot.content_hub import ContentHub

    return ContentHub()


@pytest.fixture
def mcp_handler(hub):
    from spec2sphere.copilot.mcp_server import MCPHandler

    return MCPHandler(hub)


@pytest.mark.asyncio
async def test_mcp_handler_initialize(mcp_handler):
    """MCPHandler handles 'initialize' message correctly."""
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = await mcp_handler.handle_message(msg)
    assert resp["jsonrpc"] == "2.0"
    assert resp["id"] == 1
    assert "result" in resp
    result = resp["result"]
    assert "protocolVersion" in result
    assert "serverInfo" in result
    assert result["serverInfo"]["name"] == "spec2sphere-mcp"
    assert "capabilities" in result


@pytest.mark.asyncio
async def test_mcp_handler_tools_list(mcp_handler):
    """MCPHandler returns tool definitions on tools/list."""
    msg = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = await mcp_handler.handle_message(msg)
    assert resp["id"] == 2
    tools = resp["result"]["tools"]
    assert isinstance(tools, list)
    assert len(tools) > 0
    # search_knowledge should be present
    tool_names = {t["name"] for t in tools}
    assert "search_knowledge" in tool_names
    assert "get_architecture_overview" in tool_names
    # Each tool has required fields
    for tool in tools:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool


@pytest.mark.asyncio
async def test_mcp_handler_resources_list(mcp_handler):
    """MCPHandler returns resource URIs on resources/list."""
    msg = {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}}
    resp = await mcp_handler.handle_message(msg)
    assert resp["id"] == 3
    resources = resp["result"]["resources"]
    assert isinstance(resources, list)
    assert len(resources) > 0
    # Check URI format
    for resource in resources:
        assert resource["uri"].startswith("spec2sphere://")
        assert "name" in resource
        assert resource["mimeType"] == "text/markdown"


@pytest.mark.asyncio
async def test_mcp_handler_tool_call(mcp_handler):
    """MCPHandler executes search_knowledge tool and returns content."""
    msg = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "search_knowledge",
            "arguments": {"query": "architecture"},
        },
    }
    resp = await mcp_handler.handle_message(msg)
    assert resp["id"] == 4
    assert "result" in resp
    content = resp["result"]["content"]
    assert isinstance(content, list)
    assert len(content) > 0
    assert content[0]["type"] == "text"
    assert isinstance(content[0]["text"], str)
    assert len(content[0]["text"]) > 0


@pytest.mark.asyncio
async def test_mcp_handler_tool_call_architecture(mcp_handler):
    """MCPHandler executes get_architecture_overview tool."""
    msg = {
        "jsonrpc": "2.0",
        "id": 5,
        "method": "tools/call",
        "params": {
            "name": "get_architecture_overview",
            "arguments": {"topic": "overview"},
        },
    }
    resp = await mcp_handler.handle_message(msg)
    assert "result" in resp
    text = resp["result"]["content"][0]["text"]
    assert "layer" in text.lower() or "Layer" in text


@pytest.mark.asyncio
async def test_mcp_handler_unknown_method(mcp_handler):
    """MCPHandler returns JSON-RPC error for unknown method."""
    msg = {"jsonrpc": "2.0", "id": 99, "method": "doesnotexist/foo", "params": {}}
    resp = await mcp_handler.handle_message(msg)
    assert resp["id"] == 99
    assert "error" in resp
    assert resp["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_mcp_handler_ping(mcp_handler):
    """MCPHandler responds to ping with empty result."""
    msg = {"jsonrpc": "2.0", "id": 10, "method": "ping", "params": {}}
    resp = await mcp_handler.handle_message(msg)
    assert resp["id"] == 10
    assert "result" in resp
    assert resp["result"] == {}


@pytest.mark.asyncio
async def test_mcp_handler_initialized_notification(mcp_handler):
    """MCPHandler handles 'initialized' notification (no response body)."""
    msg = {"jsonrpc": "2.0", "method": "initialized"}
    resp = await mcp_handler.handle_message(msg)
    # Notifications return an empty dict
    assert resp == {}


# ---------------------------------------------------------------------------
# MCP HTTP endpoint tests
# ---------------------------------------------------------------------------


def test_mcp_sse_post_initialize(client):
    """POST /mcp/sse with initialize returns JSON-RPC response."""
    resp = client.post(
        "/mcp/sse",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 1
    assert "result" in data
    assert data["result"]["serverInfo"]["name"] == "spec2sphere-mcp"


def test_mcp_sse_post_tools_list(client):
    """POST /mcp/sse with tools/list returns tool definitions."""
    resp = client.post(
        "/mcp/sse",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    )
    assert resp.status_code == 200
    data = resp.json()
    tool_names = {t["name"] for t in data["result"]["tools"]}
    assert "search_knowledge" in tool_names


def test_mcp_sse_post_invalid_json(client):
    """POST /mcp/sse with non-JSON body returns 400 parse error."""
    resp = client.post(
        "/mcp/sse",
        content=b"not valid json{{",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == -32700


def test_mcp_sse_post_search_tool(client):
    """POST /mcp/sse can invoke search_knowledge tool inline."""
    resp = client.post(
        "/mcp/sse",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "search_knowledge", "arguments": {"query": "SAP"}},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "result" in data
    text = data["result"]["content"][0]["text"]
    assert isinstance(text, str)
    assert len(text) > 0


def test_mcp_sse_post_notification_returns_204(client):
    """POST /mcp/sse with a notification (no id) returns 204."""
    resp = client.post(
        "/mcp/sse",
        json={"jsonrpc": "2.0", "method": "initialized"},
    )
    assert resp.status_code == 204
