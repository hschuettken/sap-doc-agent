"""Declarative Agent endpoints for Copilot for M365.

Exposes:
  GET /api/copilot/agent/manifest.yaml   — Copilot agent manifest (YAML)
  GET /api/copilot/agent/openapi.yaml    — OpenAPI spec for agent actions (YAML)
  POST /api/copilot/agent/actions/search_specs        — search knowledge
  GET  /api/copilot/agent/actions/list_governance_rules — list governance/standards pages
  GET  /api/copilot/agent/actions/get_route/{route_id} — get a specific page

All endpoints are unauthenticated — MS Copilot handles auth on the M365 side.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from spec2sphere.copilot.content_hub import ContentHub

logger = logging.getLogger(__name__)

_hub = ContentHub()

# Base URL — overridable via env for production/tunnel setups
_BASE_URL = os.environ.get("SPEC2SPHERE_BASE_URL", "http://localhost:8260")

# ---------------------------------------------------------------------------
# Manifest & OpenAPI templates
# ---------------------------------------------------------------------------


def _agent_manifest() -> dict:
    """Build the Copilot agent manifest as a Python dict (serialised to YAML on request)."""
    return {
        "schema_version": "v2.1",
        "name_for_human": "Spec2Sphere",
        "name_for_model": "spec2sphere",
        "description_for_human": (
            "SAP Datasphere and SAC delivery knowledge: specs, best practices, "
            "architecture patterns, migration guides, and governance rules from Spec2Sphere."
        ),
        "description_for_model": (
            "Use this agent to look up SAP Datasphere / SAC delivery standards, "
            "query architecture best practices, search migration guides, and retrieve "
            "governance rules maintained by the Spec2Sphere platform."
        ),
        "contact_email": "spec2sphere@horvath.com",
        "legal_info_url": f"{_BASE_URL}/copilot",
        "logo_url": f"{_BASE_URL}/static/logo.png",
        "api": {
            "type": "openapi",
            "url": f"{_BASE_URL}/api/copilot/agent/openapi.yaml",
        },
        "auth": {"type": "none"},
        "capabilities": [
            {
                "name": "search_specs",
                "description": "Search across all Spec2Sphere knowledge sections.",
            },
            {
                "name": "list_governance_rules",
                "description": "List available governance rules and standards.",
            },
            {
                "name": "get_route",
                "description": "Retrieve a specific knowledge page by its route identifier.",
            },
        ],
    }


def _openapi_spec() -> dict:
    """Build the OpenAPI 3.0 spec for agent actions."""
    return {
        "openapi": "3.0.0",
        "info": {
            "title": "Spec2Sphere Copilot Agent Actions",
            "description": ("Actions available to the Spec2Sphere Declarative Agent for Copilot for M365."),
            "version": "1.0.0",
        },
        "servers": [{"url": _BASE_URL}],
        "paths": {
            "/api/copilot/agent/actions/search_specs": {
                "post": {
                    "operationId": "search_specs",
                    "summary": "Search Spec2Sphere knowledge",
                    "description": (
                        "Full-text search across all Spec2Sphere knowledge sections "
                        "(architecture, standards, knowledge, migration, quality, glossary). "
                        "Optionally scope to a single section."
                    ),
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["query"],
                                    "properties": {
                                        "query": {
                                            "type": "string",
                                            "description": "Search terms",
                                        },
                                        "section": {
                                            "type": "string",
                                            "description": "Limit search to this section",
                                            "enum": [
                                                "knowledge",
                                                "standards",
                                                "architecture",
                                                "migration",
                                                "quality",
                                                "glossary",
                                            ],
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Search results",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "query": {"type": "string"},
                                            "count": {"type": "integer"},
                                            "results": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "section_id": {"type": "string"},
                                                        "page_id": {"type": "string"},
                                                        "title": {"type": "string"},
                                                        "snippet": {"type": "string"},
                                                        "url": {"type": "string"},
                                                    },
                                                },
                                            },
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/api/copilot/agent/actions/list_governance_rules": {
                "get": {
                    "operationId": "list_governance_rules",
                    "summary": "List governance rules and standards",
                    "description": (
                        "Returns all pages in the 'standards' and 'quality' sections — "
                        "the Horvath Analytics delivery governance rules."
                    ),
                    "responses": {
                        "200": {
                            "description": "List of governance pages",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "sections": {
                                                "type": "array",
                                                "items": {
                                                    "type": "object",
                                                    "properties": {
                                                        "section_id": {"type": "string"},
                                                        "section_title": {"type": "string"},
                                                        "pages": {
                                                            "type": "array",
                                                            "items": {
                                                                "type": "object",
                                                                "properties": {
                                                                    "id": {"type": "string"},
                                                                    "title": {"type": "string"},
                                                                    "excerpt": {"type": "string"},
                                                                    "url": {"type": "string"},
                                                                },
                                                            },
                                                        },
                                                    },
                                                },
                                            }
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            },
            "/api/copilot/agent/actions/get_route/{route_id}": {
                "get": {
                    "operationId": "get_route",
                    "summary": "Get a specific knowledge page",
                    "description": (
                        "Retrieve the full content of a page by its route identifier "
                        "(format: section_id__page_id, e.g. 'architecture__overview')."
                    ),
                    "parameters": [
                        {
                            "name": "route_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                            "description": "Route identifier in format section_id__page_id",
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "Page content",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "id": {"type": "string"},
                                            "section_id": {"type": "string"},
                                            "title": {"type": "string"},
                                            "content_md": {"type": "string"},
                                            "updated_at": {"type": "string"},
                                            "url": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        },
                        "404": {"description": "Page not found"},
                    },
                }
            },
        },
    }


# ---------------------------------------------------------------------------
# Router factory
# ---------------------------------------------------------------------------


def create_declarative_agent_router() -> APIRouter:
    """Return the FastAPI router for the declarative agent endpoints."""
    router = APIRouter(prefix="/api/copilot/agent", tags=["copilot-agent"])

    # ---------------------------------------------------------------- manifest --

    @router.get("/manifest.yaml", response_class=Response, include_in_schema=False)
    async def agent_manifest():
        """Return the Copilot for M365 declarative agent manifest as YAML."""
        content = yaml.dump(_agent_manifest(), allow_unicode=True, sort_keys=False)
        return Response(content=content, media_type="application/yaml")

    # ----------------------------------------------------------------- openapi --

    @router.get("/openapi.yaml", response_class=Response, include_in_schema=False)
    async def agent_openapi():
        """Return the OpenAPI spec for agent actions as YAML."""
        content = yaml.dump(_openapi_spec(), allow_unicode=True, sort_keys=False)
        return Response(content=content, media_type="application/yaml")

    # ----------------------------------------------------------- search action --

    @router.post("/actions/search_specs")
    async def action_search_specs(body: dict):
        """Delegate to ContentHub.search(); returns structured JSON for the agent."""
        query = body.get("query", "").strip()
        section: Optional[str] = body.get("section")
        if not query:
            return {"query": query, "count": 0, "results": []}
        results = _hub.search(query, section=section)
        return {
            "query": query,
            "section": section,
            "count": len(results),
            "results": [
                {
                    "section_id": r["section_id"],
                    "section_title": r["section_title"],
                    "page_id": r["page_id"],
                    "title": r["title"],
                    "snippet": r["snippet"],
                    "url": r["url"],
                    "updated_at": r.get("updated_at", ""),
                }
                for r in results
            ],
        }

    # ------------------------------------------ list_governance_rules action --

    @router.get("/actions/list_governance_rules")
    async def action_list_governance_rules():
        """Return all pages from standards + quality sections."""
        sections_out = []
        for sid in ("standards", "quality"):
            sec = _hub.get_section(sid)
            if not sec:
                continue
            sections_out.append(
                {
                    "section_id": sid,
                    "section_title": sec["title"],
                    "pages": [
                        {
                            "id": p["id"],
                            "title": p["title"],
                            "excerpt": p.get("excerpt", ""),
                            "url": p["url"],
                        }
                        for p in sec.get("pages", [])
                    ],
                }
            )
        return {"sections": sections_out}

    # ---------------------------------------------- get_route/{route_id} action --

    @router.get("/actions/get_route/{route_id:path}")
    async def action_get_route(route_id: str):
        """Return full page content for a route_id of the form 'section_id__page_id'."""
        if "__" not in route_id:
            raise HTTPException(
                status_code=400,
                detail="route_id must be in format section_id__page_id (double underscore separator)",
            )
        section_id, page_id = route_id.split("__", 1)
        page = _hub.get_page(section_id, page_id)
        if page is None:
            raise HTTPException(status_code=404, detail=f"Page not found: {route_id}")
        return {
            "id": page["id"],
            "section_id": page["section_id"],
            "title": page["title"],
            "content_md": page["content_md"],
            "updated_at": page.get("updated_at", ""),
            "url": page["breadcrumbs"][-1]["url"] if page.get("breadcrumbs") else f"/copilot/{section_id}/{page_id}",
        }

    return router
