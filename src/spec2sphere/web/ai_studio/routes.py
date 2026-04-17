"""AI Studio web routes — list, create, edit, preview, publish.

Persistence lives in ``dsp_ai.enhancements``. Preview proxies to the
dsp-ai live adapter at ``DSPAI_URL`` so the Studio editor and the SAC
widget drive the same engine. RBAC: every email in
``STUDIO_AUTHOR_EMAILS`` can author; empty means allow-all (dev).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Body, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from spec2sphere.dsp_ai.config import EnhancementConfig
from spec2sphere.dsp_ai.events import emit

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _current_email(request: Request) -> str:
    """Best-effort caller email — session middleware sets request.state,
    but tests and unauthenticated contexts can still POST preview."""
    session = getattr(request.state, "session", None) or {}
    return session.get("email") or request.headers.get("X-User-Email") or "anonymous"


def _is_author(email: str) -> bool:
    allow = [e.strip().lower() for e in os.environ.get("STUDIO_AUTHOR_EMAILS", "").split(",") if e.strip()]
    return not allow or email.lower() in allow


def _render(request: Request, template: str, ctx: dict[str, Any]) -> HTMLResponse:
    ctx["request"] = request
    ctx["user"] = {"email": _current_email(request)}
    return _templates.TemplateResponse(request, template, ctx)


def create_ai_studio_router() -> APIRouter:
    from .brain_explorer import create_brain_router  # noqa: PLC0415
    from .generation_log import create_log_router  # noqa: PLC0415
    from .library_routes import create_library_router  # noqa: PLC0415
    from .templates_library import create_templates_router  # noqa: PLC0415

    router = APIRouter(prefix="/ai-studio", tags=["ai-studio"])
    # Sub-routers registered first so fixed prefixes (/templates, /log, /brain, /library)
    # are matched before the generic /{enh_id} path-param routes below.
    router.include_router(create_templates_router())
    router.include_router(create_log_router())
    router.include_router(create_brain_router())
    router.include_router(create_library_router())

    @router.get("/", response_class=HTMLResponse)
    @router.get("", response_class=HTMLResponse)
    async def list_enhancements(request: Request):
        from spec2sphere.dsp_ai.db import get_conn  # noqa: PLC0415

        async with get_conn() as conn:
            rows = await conn.fetch(
                "SELECT id::text AS id, name, kind, version, status, updated_at "
                "FROM dsp_ai.enhancements ORDER BY updated_at DESC"
            )
        return _render(
            request,
            "partials/ai_studio.html",
            {
                "active_page": "ai-studio",
                "sub_nav": "enhancements",
                "enhancements": [dict(r) for r in rows],
                "is_author": _is_author(_current_email(request)),
            },
        )

    @router.post("/")
    @router.post("")
    async def create(request: Request, name: str = Form(...), kind: str = Form(...)):
        from spec2sphere.dsp_ai.db import current_customer, get_conn  # noqa: PLC0415

        email = _current_email(request)
        if not _is_author(email):
            raise HTTPException(403, detail="not an AI Studio author")
        new_id = str(uuid.uuid4())
        default_config = {
            "name": name,
            "kind": kind,
            "mode": "batch",
            "bindings": {"data": {"dsp_query": "SELECT 1", "parameters": {}}},
            "adaptive_rules": {"per_user": False, "per_time": False, "per_delta": False},
            "prompt_template": "You are a helpful assistant. Context: {{ dsp_data }}",
            "render_hint": "narrative_text",
            "ttl_seconds": 600,
        }
        async with get_conn() as conn:
            await conn.execute(
                "INSERT INTO dsp_ai.enhancements (id, name, kind, config, author, customer) "
                "VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6)",
                new_id,
                name,
                kind,
                json.dumps(default_config),
                email,
                current_customer(),
            )
        return RedirectResponse(f"/ai-studio/{new_id}/edit", status_code=303)

    @router.get("/{enh_id}/edit", response_class=HTMLResponse)
    async def edit(request: Request, enh_id: str):
        from spec2sphere.dsp_ai.db import get_conn  # noqa: PLC0415

        email = _current_email(request)
        if not _is_author(email):
            raise HTTPException(403, detail="not an AI Studio author")
        async with get_conn() as conn:
            row = await conn.fetchrow(
                "SELECT id::text AS id, name, kind, version, status, config "
                "FROM dsp_ai.enhancements WHERE id = $1::uuid",
                enh_id,
            )
        if row is None:
            raise HTTPException(404, detail="enhancement not found")
        data = dict(row)
        cfg = data["config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        return _render(
            request,
            "partials/ai_studio_editor.html",
            {
                "active_page": "ai-studio",
                "enh": {k: data[k] for k in ("id", "name", "kind", "version", "status")},
                "config_json": json.dumps(cfg, indent=2),
            },
        )

    @router.put("/{enh_id}/config")
    async def update_config(request: Request, enh_id: str, body: dict = Body(...)):
        from spec2sphere.dsp_ai.db import get_conn  # noqa: PLC0415

        email = _current_email(request)
        if not _is_author(email):
            raise HTTPException(403, detail="not an AI Studio author")
        try:
            EnhancementConfig.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(422, detail=exc.errors())
        async with get_conn() as conn:
            await conn.execute(
                "UPDATE dsp_ai.enhancements SET config = $1::jsonb, updated_at = NOW() WHERE id = $2::uuid",
                json.dumps(body),
                enh_id,
            )
        return {"ok": True}

    @router.post("/{enh_id}/preview")
    async def preview(request: Request, enh_id: str, body: dict = Body(default=None)):
        email = _current_email(request)
        if not _is_author(email):
            raise HTTPException(403, detail="not an AI Studio author")
        body = body or {}
        body["preview"] = True
        base = os.environ.get("DSPAI_URL", "http://dsp-ai:8000")
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base}/v1/enhance/{enh_id}", json=body)
        try:
            payload = resp.json()
        except Exception:
            payload = {"error": "invalid response from dsp-ai", "status": resp.status_code}
        return JSONResponse(payload, status_code=resp.status_code)

    @router.post("/{enh_id}/publish")
    async def publish(request: Request, enh_id: str):
        from spec2sphere.dsp_ai.db import current_customer, get_conn  # noqa: PLC0415

        email = _current_email(request)
        if not _is_author(email):
            raise HTTPException(403, detail="not an AI Studio author")
        async with get_conn() as conn:
            row = await conn.fetchrow("SELECT status FROM dsp_ai.enhancements WHERE id = $1::uuid", enh_id)
            if row is None:
                raise HTTPException(404, detail="enhancement not found")
            await conn.execute(
                "UPDATE dsp_ai.enhancements SET status = 'published', updated_at = NOW() WHERE id = $1::uuid",
                enh_id,
            )
            await conn.execute(
                "INSERT INTO dsp_ai.studio_audit (action, enhancement_id, author, before, after, customer) "
                "VALUES ($1, $2::uuid, $3, $4::jsonb, $5::jsonb, $6)",
                "publish",
                enh_id,
                email,
                json.dumps({"status": row["status"]}),
                json.dumps({"status": "published"}),
                current_customer(),
            )
        await emit("enhancement_published", {"id": enh_id})
        return RedirectResponse(f"/ai-studio/{enh_id}/edit", status_code=303)

    return router
