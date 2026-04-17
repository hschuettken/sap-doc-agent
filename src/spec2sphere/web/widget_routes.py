"""Serve the SAC Custom Widget bundle + manifest with CORS + integrity."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

router = APIRouter(prefix="/widget", tags=["widget"])


def _widget_dir() -> Path:
    """Directory holding main.js, main.js.map, manifest.json.

    Override with WIDGET_DIST_DIR env var (useful for tests).
    Default: src/spec2sphere/widget/dist relative to this file.
    """
    override = os.environ.get("WIDGET_DIST_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1] / "widget" / "dist"


def _cors_headers() -> dict[str, str]:
    origins = os.environ.get("WIDGET_ALLOWED_ORIGINS", "*").strip() or "*"
    # SAC will only send one origin at a time; echoing the configured
    # value is the simplest form and matches the compose env.
    return {
        "Access-Control-Allow-Origin": origins.split(",")[0].strip() if origins != "*" else "*",
        "Cross-Origin-Resource-Policy": "cross-origin",
    }


@router.get("/manifest.json")
async def manifest() -> Response:
    path = _widget_dir() / "manifest.json"
    if not path.exists():
        raise HTTPException(status_code=503, detail="widget not built")
    text = path.read_text().replace("{{API_BASE}}", os.environ.get("PUBLIC_API_BASE", ""))
    return Response(content=text, media_type="application/json", headers=_cors_headers())


@router.get("/main.js")
async def main_js() -> FileResponse:
    path = _widget_dir() / "main.js"
    if not path.exists():
        raise HTTPException(status_code=503, detail="widget not built")
    return FileResponse(path, media_type="application/javascript", headers=_cors_headers())


@router.get("/main.js.map")
async def main_js_map() -> FileResponse:
    path = _widget_dir() / "main.js.map"
    if not path.exists():
        raise HTTPException(status_code=503, detail="widget not built")
    return FileResponse(path, media_type="application/json", headers=_cors_headers())
