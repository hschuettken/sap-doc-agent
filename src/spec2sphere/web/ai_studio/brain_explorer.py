"""AI Studio Brain Explorer — visual Neo4j navigator with a read-only Cypher console."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Only allow read-oriented Cypher. Reject anything that could mutate state.
_READ_ONLY_VERBS = {"MATCH", "RETURN", "CALL", "WITH", "UNWIND", "OPTIONAL"}
_FORBIDDEN = re.compile(
    r"\b(CREATE|DELETE|DETACH|SET|MERGE|REMOVE|DROP|LOAD|CALL\s+apoc\.periodic)\b",
    re.IGNORECASE,
)


def _is_read_only(cypher: str) -> bool:
    if not cypher.strip():
        return False
    if _FORBIDDEN.search(cypher):
        return False
    first_word = cypher.strip().split()[0].upper()
    return first_word in _READ_ONLY_VERBS


def create_brain_router() -> APIRouter:
    router = APIRouter(prefix="/brain", tags=["ai-studio"])

    @router.get("/", response_class=HTMLResponse)
    @router.get("", response_class=HTMLResponse)
    async def explorer(request: Request):
        return _templates.TemplateResponse(
            request,
            "partials/ai_studio_brain.html",
            {
                "request": request,
                "active_page": "ai-studio",
                "sub_nav": "brain",
            },
        )

    @router.post("/query")
    async def query(body: dict = Body(...)):
        cypher = str(body.get("cypher", ""))
        params = body.get("parameters", {}) or {}
        if not _is_read_only(cypher):
            raise HTTPException(400, "read-only Cypher required (MATCH/RETURN/CALL/WITH/UNWIND/OPTIONAL)")
        try:
            from spec2sphere.dsp_ai.brain.client import run as brain_run

            rows = await brain_run(cypher, **params)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=502)

        def _coerce(v):
            if hasattr(v, "_properties"):
                return dict(v._properties)
            if isinstance(v, dict):
                return {k: _coerce(val) for k, val in v.items()}
            if isinstance(v, list):
                return [_coerce(x) for x in v]
            return v

        return {"rows": [_coerce(dict(r)) for r in rows]}

    @router.get("/overview")
    async def overview():
        """Quick 50-node snapshot for the initial vis-network render."""
        try:
            from spec2sphere.dsp_ai.brain.client import run as brain_run

            rows = await brain_run(
                "MATCH (n) OPTIONAL MATCH (n)-[r]-(m) "
                "RETURN labels(n) AS labels, n.id AS id, n.name AS name, "
                "type(r) AS rel, m.id AS other_id LIMIT 50"
            )
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=502)
        return {"rows": rows}

    return router
