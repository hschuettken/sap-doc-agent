"""Library export/import routes for the AI Studio.

GET  /ai-studio/library/export  — download a JSON bundle of all enhancements
POST /ai-studio/library/import  — upload a JSON bundle, with merge/replace/draftify mode
GET  /ai-studio/library/        — library management UI page
"""

from __future__ import annotations

import datetime as dt
import json
import os

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pathlib import Path

from spec2sphere.dsp_ai.library import export_library, import_library

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _current_email(request: Request) -> str:
    session = getattr(request.state, "session", None) or {}
    return session.get("email") or request.headers.get("X-User-Email") or "anonymous"


def _is_author(email: str) -> bool:
    allow = [e.strip().lower() for e in os.environ.get("STUDIO_AUTHOR_EMAILS", "").split(",") if e.strip()]
    return not allow or email.lower() in allow


def create_library_router() -> APIRouter:
    router = APIRouter(prefix="/library", tags=["ai-studio-library"])

    @router.get("/", response_class=HTMLResponse)
    async def library_page(request: Request):
        email = _current_email(request)
        return _templates.TemplateResponse(
            request,
            "partials/ai_studio_library.html",
            {
                "active_page": "ai-studio",
                "sub_nav": "library",
                "is_author": _is_author(email),
                "user": {"email": email},
            },
        )

    @router.get("/export")
    async def export(request: Request) -> Response:
        customer = os.environ.get("CUSTOMER", "default")
        blob = await export_library(customer)
        payload = json.dumps(blob, indent=2)
        filename = f"spec2sphere-library-{customer}-{dt.date.today().isoformat()}.json"
        return Response(
            payload,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.post("/import")
    async def imp(
        request: Request,
        file: UploadFile = File(...),
        mode: str = Form("merge"),
    ) -> JSONResponse:
        email = _current_email(request)
        if not _is_author(email):
            raise HTTPException(403, "author role required to import library")
        if mode not in ("merge", "replace", "draftify"):
            raise HTTPException(400, f"invalid mode: {mode!r}")
        try:
            raw = await file.read()
            blob = json.loads(raw)
        except Exception as exc:
            raise HTTPException(400, f"invalid JSON: {exc}") from exc
        customer = os.environ.get("CUSTOMER", "default")
        try:
            result = await import_library(blob, customer=customer, mode=mode, author=email)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return JSONResponse(result)

    return router
