"""AI Studio Generation Log — queryable ledger of dsp_ai.generations."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def create_log_router() -> APIRouter:
    router = APIRouter(prefix="/log", tags=["ai-studio"])

    @router.get("/", response_class=HTMLResponse)
    @router.get("", response_class=HTMLResponse)
    async def list_generations(
        request: Request,
        enhancement_id: str | None = None,
        user_id: str | None = None,
        since_hours: int = 24,
        model: str | None = None,
        error_kind: str | None = None,
    ):
        since = datetime.now(timezone.utc) - timedelta(hours=max(1, min(since_hours, 720)))
        filters = ["g.created_at >= $1"]
        params: list = [since]

        def _add(cond: str, v):
            params.append(v)
            filters.append(cond.replace("$$", f"${len(params)}"))

        if enhancement_id:
            _add("g.enhancement_id = $$::uuid", enhancement_id)
        if user_id:
            _add("g.user_id = $$", user_id)
        if model:
            _add("g.model = $$", model)
        if error_kind:
            _add("g.error_kind = $$", error_kind)

        sql = (
            "SELECT g.id::text AS id, g.enhancement_id::text AS enhancement_id, "
            "g.user_id, g.context_key, g.model, g.quality_level, g.latency_ms, "
            "g.cost_usd, g.cached, g.quality_warnings, g.error_kind, g.preview, "
            "g.created_at, e.name AS enh_name "
            "FROM dsp_ai.generations g "
            "LEFT JOIN dsp_ai.enhancements e ON e.id = g.enhancement_id "
            "WHERE " + " AND ".join(filters) + " "
            "ORDER BY g.created_at DESC LIMIT 200"
        )
        from spec2sphere.dsp_ai.db import get_conn  # noqa: PLC0415

        async with get_conn() as conn:
            rows = await conn.fetch(sql, *params)
        return _templates.TemplateResponse(
            request,
            "partials/ai_studio_log.html",
            {
                "request": request,
                "active_page": "ai-studio",
                "sub_nav": "log",
                "rows": [dict(r) for r in rows],
                "filters": {
                    "enhancement_id": enhancement_id,
                    "user_id": user_id,
                    "since_hours": since_hours,
                    "model": model,
                    "error_kind": error_kind,
                },
            },
        )

    @router.get("/{gen_id}", response_class=HTMLResponse)
    async def generation_detail(request: Request, gen_id: str):
        base = os.environ.get("DSPAI_URL", "http://dsp-ai:8000")
        why: dict = {}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{base}/v1/why/{gen_id}")
            if resp.status_code == 200:
                why = resp.json()
            elif resp.status_code == 404:
                raise HTTPException(404, "generation not found")
        except HTTPException:
            raise
        except Exception:
            why = {"error": "dsp-ai unreachable"}
        return _templates.TemplateResponse(
            request,
            "partials/ai_studio_log_detail.html",
            {
                "request": request,
                "active_page": "ai-studio",
                "sub_nav": "log",
                "gen_id": gen_id,
                "why": why,
            },
        )

    return router
