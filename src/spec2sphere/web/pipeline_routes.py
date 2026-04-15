"""Pipeline UI routes for Spec2Sphere.

Provides HTMX-driven routes for the full delivery pipeline:
  Requirements intake, semantic parsing, HLA generation, placement,
  approval gates, and notification centre.

All routes live under /ui/pipeline and /ui/notifications.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Status badge colours ──────────────────────────────────────────────────────
STATUS_CLASSES = {
    "draft": "bg-gray-100 text-gray-600",
    "pending_review": "bg-amber-100 text-amber-700",
    "approved": "bg-green-100 text-green-700",
    "rejected": "bg-red-100 text-red-700",
    "rework": "bg-blue-100 text-blue-700",
    "generating": "bg-purple-100 text-purple-700",
    "parsed": "bg-teal-100 text-teal-700",
    "ingested": "bg-indigo-100 text-indigo-700",
}

# ── Pipeline stage definitions ────────────────────────────────────────────────
PIPELINE_STAGES = [
    {
        "key": "intake",
        "label": "Intake",
        "url": "/ui/pipeline/requirements",
        "icon": "M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12",
    },
    {
        "key": "interpretation",
        "label": "Interpretation",
        "url": "/ui/pipeline/requirements",
        "icon": "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2",
    },
    {
        "key": "hla",
        "label": "HLA",
        "url": "/ui/pipeline/architecture",
        "icon": "M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z",
    },
    {"key": "tech_spec", "label": "Tech Spec", "url": "#", "icon": "M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"},
    {
        "key": "test_spec",
        "label": "Test Spec",
        "url": "#",
        "icon": "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4",
    },
    {
        "key": "build",
        "label": "Build",
        "url": "#",
        "icon": "M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z",
    },
    {
        "key": "deploy",
        "label": "Deploy",
        "url": "#",
        "icon": "M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2",
    },
    {
        "key": "qa",
        "label": "QA",
        "url": "#",
        "icon": "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
    },
    {"key": "release", "label": "Release", "url": "#", "icon": "M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4"},
    {
        "key": "docs",
        "label": "Docs",
        "url": "#",
        "icon": "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
    },
]


def _render(request: Request, template: str, ctx: dict) -> HTMLResponse:
    ctx["request"] = request
    ctx.setdefault("status_classes", STATUS_CLASSES)
    return templates.TemplateResponse(request, template, ctx)


def _get_llm():
    try:
        import os
        from spec2sphere.config import LLMConfig
        from spec2sphere.llm import create_llm_provider

        provider = os.environ.get("LLM_PROVIDER", "none")
        if provider and provider != "none":
            return create_llm_provider(LLMConfig(provider=provider))
    except Exception:
        pass
    return None


async def _get_ctx():
    from spec2sphere.tenant.context import get_default_context

    return await get_default_context()


def _status_badge(status: str) -> str:
    cls = STATUS_CLASSES.get(status or "draft", "bg-gray-100 text-gray-600")
    return f'<span class="inline-block px-2 py-0.5 rounded-full text-xs font-medium {cls}">{status or "draft"}</span>'


def _safe_json(val) -> dict | list:
    """Return parsed JSON if val is a string, or the value itself."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return val or {}


def _str_ids(d: dict) -> dict:
    """Stringify UUID fields in a dict so Jinja2 can render them."""
    import uuid as _uuid

    for k, v in list(d.items()):
        if isinstance(v, _uuid.UUID):
            d[k] = str(v)
    return d


def create_pipeline_routes() -> APIRouter:
    """Return an APIRouter with all pipeline + notification UI routes."""
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
            hlas = await list_hla_documents(ctx=ctx, limit=20)
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
                for col in ("parsed_entities", "parsed_kpis", "parsed_grain", "open_questions", "migration_objects"):
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

    # ── Architecture (HLA) ────────────────────────────────────────────────────

    @router.get("/ui/pipeline/architecture", response_class=HTMLResponse)
    async def architecture_list(request: Request):
        """List HLA documents."""
        hlas: list[dict] = []
        error: Optional[str] = None
        req_filter = request.query_params.get("requirement_id", "")

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.hla_generator import list_hla_documents

            hlas = await list_hla_documents(
                ctx=ctx,
                requirement_id=req_filter or None,
            )
            for h in hlas:
                _str_ids(h)
        except Exception as exc:
            logger.warning("Architecture list error: %s", exc)
            error = str(exc)

        return _render(
            request,
            "partials/architecture.html",
            {
                "active_page": "pipeline",
                "hlas": hlas,
                "req_filter": req_filter,
                "error": error,
            },
        )

    @router.get("/ui/pipeline/architecture/{hla_id}", response_class=HTMLResponse)
    async def architecture_detail(hla_id: str, request: Request):
        """HLA document detail with decisions, placement, and approval panel."""
        hla: Optional[dict] = None
        approval: Optional[dict] = None
        placements: list[dict] = []
        versions: list[dict] = []
        error: Optional[str] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.hla_generator import get_hla, list_hla_documents
            from spec2sphere.governance.approvals import get_approval_for_artifact, CHECKLISTS

            hla = await get_hla(hla_id)
            if hla:
                _str_ids(hla)
                hla["content"] = _safe_json(hla.get("content"))

                # Placement decisions
                try:
                    from spec2sphere.pipeline.placement import place_architecture

                    llm = _get_llm()
                    if hla.get("content"):
                        placement_results = await place_architecture(hla["content"], llm)
                        placements = [p.to_dict() if hasattr(p, "to_dict") else dict(p) for p in placement_results]
                except Exception:
                    pass

                # Approval
                try:
                    approval = await get_approval_for_artifact("hla_document", hla_id)
                    if approval:
                        _str_ids(approval)
                        approval["checklist"] = _safe_json(approval.get("checklist"))
                except Exception:
                    pass

                # Other versions for same requirement
                try:
                    req_id = hla.get("requirement_id")
                    if req_id:
                        all_hlas = await list_hla_documents(ctx=ctx, requirement_id=str(req_id))
                        versions = [_str_ids(h) or h for h in all_hlas if str(h.get("id", "")) != hla_id]
                except Exception:
                    pass

        except Exception as exc:
            logger.warning("HLA detail error: %s", exc)
            error = str(exc)

        if hla is None and not error:
            error = "HLA document not found"

        from spec2sphere.governance.approvals import CHECKLISTS

        checklist_template = CHECKLISTS.get("hla_document", [])

        return _render(
            request,
            "partials/architecture_detail.html",
            {
                "active_page": "pipeline",
                "hla": hla,
                "approval": approval,
                "placements": placements,
                "versions": versions,
                "checklist_template": checklist_template,
                "error": error,
            },
        )

    @router.post("/ui/pipeline/architecture/{hla_id}/submit-review", response_class=HTMLResponse)
    async def submit_hla_review(hla_id: str, request: Request):
        """Submit HLA for review."""
        try:
            ctx = await _get_ctx()
            from spec2sphere.governance.approvals import submit_for_review

            approval = await submit_for_review(
                artifact_type="hla_document",
                artifact_id=hla_id,
                ctx=ctx,
                reviewer_id=None,
            )
            _str_ids(approval)
            approval_id = approval.get("id", "")
            return HTMLResponse(
                f'<div class="p-3 bg-amber-50 border border-amber-200 rounded-lg">'
                f'<p class="text-sm font-medium text-amber-700">HLA submitted for review.</p>'
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

    # ── Approvals ─────────────────────────────────────────────────────────────

    @router.get("/ui/pipeline/approvals/{approval_id}", response_class=HTMLResponse)
    async def approval_detail(approval_id: str, request: Request):
        """Approval detail with full checklist and decision panel."""
        approval: Optional[dict] = None
        artifact: Optional[dict] = None
        error: Optional[str] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.governance.approvals import get_approval, CHECKLISTS

            approval = await get_approval(approval_id)
            if approval:
                _str_ids(approval)
                approval["checklist"] = _safe_json(approval.get("checklist"))

                artifact_type = approval.get("artifact_type", "")
                artifact_id = str(approval.get("artifact_id", ""))

                try:
                    if artifact_type == "requirement":
                        from spec2sphere.pipeline.intake import get_requirement

                        artifact = await get_requirement(artifact_id)
                        if artifact:
                            _str_ids(artifact)
                    elif artifact_type == "hla_document":
                        from spec2sphere.pipeline.hla_generator import get_hla

                        artifact = await get_hla(artifact_id)
                        if artifact:
                            _str_ids(artifact)
                            artifact["content"] = _safe_json(artifact.get("content"))
                except Exception:
                    pass

        except Exception as exc:
            logger.warning("Approval detail error: %s", exc)
            error = str(exc)

        if approval is None and not error:
            error = "Approval not found"

        from spec2sphere.governance.approvals import CHECKLISTS

        artifact_type = (approval or {}).get("artifact_type", "requirement")
        checklist_template = CHECKLISTS.get(artifact_type, [])

        return _render(
            request,
            "partials/approval_detail.html",
            {
                "active_page": "pipeline",
                "approval": approval,
                "artifact": artifact,
                "checklist_template": checklist_template,
                "error": error,
            },
        )

    @router.post("/ui/pipeline/approvals/{approval_id}/decide", response_class=HTMLResponse)
    async def decide_approval(approval_id: str, request: Request):
        """Approve, reject, or request rework on an artifact."""
        try:
            form = await request.form()
            decision = str(form.get("decision", ""))
            comments = str(form.get("comments", ""))
            ctx = await _get_ctx()

            from spec2sphere.governance.approvals import review_artifact

            approval = await review_artifact(
                approval_id=approval_id,
                decision=decision,
                ctx=ctx,
                comments=comments,
            )
            _str_ids(approval)
            status = approval.get("status", decision)
            cls_map = {
                "approved": "bg-green-50 border-green-200 text-green-700",
                "rejected": "bg-red-50 border-red-200 text-red-700",
                "rework": "bg-blue-50 border-blue-200 text-blue-700",
            }
            cls = cls_map.get(status, "bg-gray-50 border-gray-200 text-gray-700")
            comments_html = f'<p class="text-xs mt-1">{comments}</p>' if comments else ""
            return HTMLResponse(
                f'<div class="p-3 border rounded-lg {cls}">'
                f'<p class="text-sm font-medium">Decision recorded: <strong>{status}</strong></p>'
                f"{comments_html}"
                f"</div>"
            )
        except Exception as exc:
            return HTMLResponse(
                f'<div class="p-3 bg-red-50 border border-red-200 rounded-lg">'
                f'<p class="text-sm text-red-700">Decision failed: {exc}</p>'
                f"</div>"
            )

    @router.put("/ui/pipeline/approvals/{approval_id}/checklist", response_class=HTMLResponse)
    async def update_checklist_route(approval_id: str, request: Request):
        """Update individual checklist item checkboxes."""
        try:
            form = await request.form()
            ctx = await _get_ctx()

            from spec2sphere.governance.approvals import update_checklist

            # Form sends checked boxes as key=on; unchecked boxes are absent
            updates: dict[str, bool] = {}
            from spec2sphere.governance.approvals import get_approval, CHECKLISTS

            approval = await get_approval(approval_id)
            if approval:
                artifact_type = approval.get("artifact_type", "requirement")
                for item in CHECKLISTS.get(artifact_type, []):
                    key = item["key"]
                    updates[key] = form.get(key) == "on"

            await update_checklist(approval_id=approval_id, checklist_updates=updates, ctx=ctx)
            return HTMLResponse('<p class="text-xs text-green-600 font-medium">Checklist saved.</p>')
        except Exception as exc:
            return HTMLResponse(f'<p class="text-xs text-red-500">Save failed: {exc}</p>')

    # ── Notifications ─────────────────────────────────────────────────────────

    @router.get("/ui/notifications", response_class=HTMLResponse)
    async def notifications_list(request: Request):
        """Notification list — HTMX partial."""
        notifications: list[dict] = []
        unread_count: int = 0
        error: Optional[str] = None
        unread_only = request.query_params.get("unread_only", "false") == "true"

        try:
            from spec2sphere.governance.notifications import list_notifications, get_unread_count

            ctx = await _get_ctx()
            uid = str(ctx.user_id)
            notifications = await list_notifications(
                user_id=uid,
                unread_only=unread_only,
                limit=30,
            )
            unread_count = await get_unread_count(uid)
            for n in notifications:
                _str_ids(n)
        except Exception as exc:
            logger.warning("Notifications load error: %s", exc)
            error = str(exc)

        return _render(
            request,
            "partials/notifications.html",
            {
                "active_page": "notifications",
                "notifications": notifications,
                "unread_count": unread_count,
                "unread_only": unread_only,
                "error": error,
            },
        )

    @router.get("/ui/notifications/badge", response_class=HTMLResponse)
    async def notifications_badge(request: Request):
        """Badge count fragment — polled by topbar every 30s."""
        try:
            from spec2sphere.governance.notifications import get_unread_count

            ctx = await _get_ctx()
            count = await get_unread_count(str(ctx.user_id))
            if count > 0:
                return HTMLResponse(
                    f'<a href="/ui/notifications" class="relative inline-flex">'
                    f'<svg class="w-5 h-5 text-gray-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
                    f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" '
                    f'd="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>'
                    f"</svg>"
                    f'<span class="absolute -top-1 -right-1 bg-red-500 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center font-bold">'
                    f"{min(count, 9)}{'+' if count > 9 else ''}"
                    f"</span>"
                    f"</a>"
                )
            return HTMLResponse(
                '<svg class="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" '
                'd="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>'
                "</svg>"
            )
        except Exception:
            return HTMLResponse("")

    @router.post("/ui/notifications/{notif_id}/read", response_class=HTMLResponse)
    async def mark_notification_read(notif_id: str, request: Request):
        """Mark a notification as read. Returns empty — HTMX outerHTML swap removes it."""
        try:
            from spec2sphere.governance.notifications import mark_read

            await mark_read(notif_id)
        except Exception as exc:
            logger.warning("Mark read %s failed: %s", notif_id, exc)
        return HTMLResponse("")

    return router
