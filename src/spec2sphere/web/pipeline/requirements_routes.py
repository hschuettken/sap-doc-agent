"""Pipeline UI routes: pipeline overview and requirements intake."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse

from .shared import (
    PIPELINE_STAGES,
    _get_ctx,
    _get_llm,
    _render,
    _str_ids,
    _safe_json,
)

logger = logging.getLogger(__name__)


def create_requirements_routes() -> APIRouter:
    """Return an APIRouter with pipeline overview and requirements routes."""
    router = APIRouter()

    # ── Pipeline overview ─────────────────────────────────────────────────────

    @router.get("/ui/pipeline", response_class=HTMLResponse)
    async def pipeline_overview(request: Request):
        """Pipeline stage-by-stage progress view."""
        requirements: list[dict] = []
        hlas: list[dict] = []
        approvals: list[dict] = []
        error: Optional[str] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.intake import list_requirements
            from spec2sphere.pipeline.hla_generator import list_hla_documents
            from spec2sphere.governance.approvals import list_approvals

            requirements = await list_requirements(ctx=ctx, limit=20)
            hlas = await list_hla_documents(ctx=ctx)
            approvals = await list_approvals(ctx=ctx, limit=50)

            for r in requirements:
                _str_ids(r)
            for h in hlas:
                _str_ids(h)
            for a in approvals:
                _str_ids(a)
        except Exception as exc:
            logger.warning("Pipeline overview load error: %s", exc)
            error = str(exc)

        # Compute per-stage counts
        approved_reqs = sum(1 for r in requirements if r.get("status") == "approved")
        approved_hlas = sum(1 for h in hlas if h.get("status") == "approved")
        stage_counts = {
            "intake": len(requirements),
            "interpretation": sum(1 for r in requirements if r.get("confidence") is not None),
            "hla": len(hlas),
        }

        return _render(
            request,
            "partials/pipeline.html",
            {
                "active_page": "pipeline",
                "stages": PIPELINE_STAGES,
                "requirements": requirements[:5],
                "hlas": hlas[:5],
                "approvals": approvals[:5],
                "stage_counts": stage_counts,
                "approved_reqs": approved_reqs,
                "approved_hlas": approved_hlas,
                "error": error,
            },
        )

    # ── Requirements ──────────────────────────────────────────────────────────

    @router.get("/ui/pipeline/requirements", response_class=HTMLResponse)
    async def requirements_list(request: Request):
        """List requirements with upload form."""
        requirements: list[dict] = []
        error: Optional[str] = None
        status_filter = request.query_params.get("status", "")

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.intake import list_requirements

            requirements = await list_requirements(
                ctx=ctx,
                status=status_filter or None,
                limit=50,
            )
            for r in requirements:
                _str_ids(r)
        except Exception as exc:
            logger.warning("Requirements list error: %s", exc)
            error = str(exc)

        return _render(
            request,
            "partials/requirements.html",
            {
                "active_page": "pipeline",
                "requirements": requirements,
                "status_filter": status_filter,
                "error": error,
            },
        )

    @router.post("/ui/pipeline/requirements/upload", response_class=HTMLResponse)
    async def upload_requirement(request: Request, file: UploadFile = File(...)):
        """Ingest a BRS document via HTMX."""
        try:
            data = await file.read()
            content_type = file.content_type or "application/octet-stream"
            ctx = await _get_ctx()
            llm = _get_llm()

            from spec2sphere.pipeline.intake import ingest_requirement

            result = await ingest_requirement(
                file_data=data,
                filename=file.filename or "upload",
                content_type=content_type,
                ctx=ctx,
                llm=llm,
            )
            req_id = result.get("requirement_id", "")
            title = result.get("title", file.filename)
            return HTMLResponse(
                f'<div class="p-3 bg-green-50 border border-green-200 rounded-lg">'
                f'<p class="text-sm font-medium text-green-700">Ingested: <strong>{title}</strong></p>'
                f'<a href="/ui/pipeline/requirements/{req_id}" '
                f'   hx-get="/ui/pipeline/requirements/{req_id}" '
                f'   hx-target="#content" hx-push-url="true" hx-select="#content-inner" '
                f'   class="text-xs text-petrol underline mt-1 inline-block">View Requirement →</a>'
                f"</div>"
            )
        except Exception as exc:
            logger.error("BRS upload failed: %s", exc)
            return HTMLResponse(
                f'<div class="p-3 bg-red-50 border border-red-200 rounded-lg">'
                f'<p class="text-sm text-red-700">Upload failed: {exc}</p>'
                f"</div>"
            )

    @router.get("/ui/pipeline/requirements/{req_id}", response_class=HTMLResponse)
    async def requirement_detail(req_id: str, request: Request):
        """Single requirement detail with parsed data and action buttons."""
        req: Optional[dict] = None
        approval: Optional[dict] = None
        error: Optional[str] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.intake import get_requirement
            from spec2sphere.governance.approvals import get_approval_for_artifact, CHECKLISTS

            req = await get_requirement(req_id)
            if req:
                _str_ids(req)
                # Deserialise JSON columns
                for col in ("parsed_entities", "parsed_kpis", "parsed_grain", "open_questions"):
                    req[col] = _safe_json(req.get(col))

                try:
                    approval = await get_approval_for_artifact("requirement", req_id)
                    if approval:
                        _str_ids(approval)
                        approval["checklist"] = _safe_json(approval.get("checklist"))
                except Exception:
                    pass

        except Exception as exc:
            logger.warning("Requirement detail error: %s", exc)
            error = str(exc)

        if req is None and not error:
            error = "Requirement not found"

        from spec2sphere.governance.approvals import CHECKLISTS

        checklist_template = CHECKLISTS.get("requirement", [])

        return _render(
            request,
            "partials/requirement_detail.html",
            {
                "active_page": "pipeline",
                "req": req,
                "approval": approval,
                "checklist_template": checklist_template,
                "error": error,
            },
        )

    @router.post("/ui/pipeline/requirements/{req_id}/parse", response_class=HTMLResponse)
    async def parse_requirement_route(req_id: str, request: Request):
        """Trigger semantic parsing via HTMX. Returns inline result fragment."""
        try:
            ctx = await _get_ctx()
            llm = _get_llm()
            from spec2sphere.pipeline.semantic_parser import parse_requirement

            req = await parse_requirement(requirement_id=req_id, ctx=ctx, llm=llm)
            _str_ids(req)
            confidence_raw = req.get("confidence") or {}
            if isinstance(confidence_raw, dict):
                # Average confidence from per-category scores (each has a "level" key)
                levels = {"high": 0.9, "medium": 0.6, "low": 0.3}
                scores = [
                    levels.get(v.get("level", "low") if isinstance(v, dict) else "low", 0.3)
                    for v in confidence_raw.values()
                ]
                confidence = sum(scores) / len(scores) if scores else 0
            else:
                confidence = float(confidence_raw) if confidence_raw else 0
            conf_pct = int(confidence * 100) if confidence <= 1 else int(confidence)
            conf_cls = "text-green-600" if conf_pct >= 80 else "text-amber-500" if conf_pct >= 50 else "text-red-500"

            return HTMLResponse(
                f'<div class="p-3 bg-green-50 border border-green-200 rounded-lg" '
                f'     hx-get="/ui/pipeline/requirements/{req_id}" '
                f'     hx-target="#content" hx-push-url="true" hx-select="#content-inner" '
                f'     hx-trigger="load">'
                f'<p class="text-sm font-medium text-green-700">Parsing complete — '
                f'confidence <span class="{conf_cls} font-bold">{conf_pct}%</span></p>'
                f'<p class="text-xs text-gray-500 mt-1">Reloading detail view…</p>'
                f"</div>"
            )
        except Exception as exc:
            logger.error("Parse requirement %s failed: %s", req_id, exc)
            return HTMLResponse(
                f'<div class="p-3 bg-red-50 border border-red-200 rounded-lg">'
                f'<p class="text-sm text-red-700">Parsing failed: {exc}</p>'
                f"</div>"
            )

    @router.put("/ui/pipeline/requirements/{req_id}", response_class=HTMLResponse)
    async def update_requirement_route(req_id: str, request: Request):
        """Update requirement fields from inline edit form."""
        try:
            form = await request.form()
            updates = {k: str(v) for k, v in form.items() if v}
            ctx = await _get_ctx()

            from spec2sphere.pipeline.intake import update_requirement

            await update_requirement(req_id, **updates)

            return HTMLResponse(
                '<div class="p-3 bg-green-50 border border-green-200 rounded-lg">'
                '<p class="text-sm text-green-700 font-medium">Updated successfully.</p>'
                "</div>"
            )
        except Exception as exc:
            return HTMLResponse(
                f'<div class="p-3 bg-red-50 border border-red-200 rounded-lg">'
                f'<p class="text-sm text-red-700">Update failed: {exc}</p>'
                f"</div>"
            )

    @router.post("/ui/pipeline/requirements/{req_id}/submit-review", response_class=HTMLResponse)
    async def submit_requirement_review(req_id: str, request: Request):
        """Submit requirement for review."""
        try:
            ctx = await _get_ctx()
            from spec2sphere.governance.approvals import submit_for_review

            approval = await submit_for_review(
                artifact_type="requirement",
                artifact_id=req_id,
                ctx=ctx,
                reviewer_id=None,
            )
            _str_ids(approval)
            approval_id = approval.get("id", "")
            return HTMLResponse(
                f'<div class="p-3 bg-amber-50 border border-amber-200 rounded-lg">'
                f'<p class="text-sm font-medium text-amber-700">Submitted for review.</p>'
                f'<a href="/ui/pipeline/approvals/{approval_id}" '
                f'   hx-get="/ui/pipeline/approvals/{approval_id}" '
                f'   hx-target="#content" hx-push-url="true" hx-select="#content-inner" '
                f'   class="text-xs text-petrol underline mt-1 inline-block">View Approval →</a>'
                f"</div>"
            )
        except Exception as exc:
            return HTMLResponse(
                f'<div class="p-3 bg-red-50 border border-red-200 rounded-lg">'
                f'<p class="text-sm text-red-700">Submit failed: {exc}</p>'
                f"</div>"
            )

    @router.post("/ui/pipeline/requirements/{req_id}/generate-hla", response_class=HTMLResponse)
    async def generate_hla_route(req_id: str, request: Request):
        """Trigger HLA generation for an approved requirement."""
        try:
            ctx = await _get_ctx()
            llm = _get_llm()
            from spec2sphere.pipeline.hla_generator import generate_hla

            result = await generate_hla(requirement_id=req_id, ctx=ctx, llm=llm)
            hla_id = result.get("hla_id", "")
            decisions = result.get("decisions_count", 0)
            return HTMLResponse(
                f'<div class="p-3 bg-green-50 border border-green-200 rounded-lg">'
                f'<p class="text-sm font-medium text-green-700">HLA generated — {decisions} architecture decision(s).</p>'
                f'<a href="/ui/pipeline/architecture/{hla_id}" '
                f'   hx-get="/ui/pipeline/architecture/{hla_id}" '
                f'   hx-target="#content" hx-push-url="true" hx-select="#content-inner" '
                f'   class="text-xs text-petrol underline mt-1 inline-block">View HLA →</a>'
                f"</div>"
            )
        except Exception as exc:
            logger.error("HLA generation for %s failed: %s", req_id, exc)
            return HTMLResponse(
                f'<div class="p-3 bg-red-50 border border-red-200 rounded-lg">'
                f'<p class="text-sm text-red-700">HLA generation failed: {exc}</p>'
                f"</div>"
            )

    return router
