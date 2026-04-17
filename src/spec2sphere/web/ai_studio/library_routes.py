"""AI Studio library export/import routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from spec2sphere.dsp_ai.library import export_library, import_library


def _caller_email(request: Request) -> str:
    session = getattr(request.state, "session", None) or {}
    return session.get("email") or request.headers.get("X-User-Email") or "anonymous"


def create_library_router() -> APIRouter:
    router = APIRouter(prefix="/library", tags=["ai-studio"])

    @router.get("/export")
    async def export(request: Request) -> Response:
        blob = await export_library()
        payload = json.dumps(blob, indent=2)
        customer = blob.get("customer", "default")
        fname = f"spec2sphere-library-{customer}.json"
        return Response(
            payload,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{fname}"'},
        )

    @router.post("/import")
    async def imp(
        request: Request,
        file: UploadFile = File(...),
        mode: str = Form("merge"),
    ) -> JSONResponse:
        if mode not in ("merge", "replace", "draftify"):
            raise HTTPException(status_code=400, detail=f"invalid mode: {mode!r}")
        raw = await file.read()
        try:
            blob = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"invalid JSON: {exc}") from exc
        try:
            result = await import_library(blob, mode=mode, author=_caller_email(request))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

    return router
