"""Pipeline UI routes: SAC blueprint generation and review."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .shared import (
    _get_ctx,
    _get_llm,
    _render,
    _str_ids,
    _safe_json,
    _status_badge,
)

logger = logging.getLogger(__name__)


def create_blueprint_routes() -> APIRouter:
    """Return an APIRouter with SAC blueprint routes."""
    router = APIRouter()

    @router.get("/ui/pipeline/blueprint", response_class=HTMLResponse)
    async def blueprint_list(request: Request):
        """List SAC blueprints."""
        blueprints: list[dict] = []
        error: Optional[str] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.blueprint_generator import list_blueprints  # noqa: PLC0415

            blueprints = await list_blueprints(ctx)
            for bp in blueprints:
                _str_ids(bp)
        except Exception as exc:
            logger.warning("Blueprint list error: %s", exc)
            error = str(exc)

        rows_html = ""
        for bp in blueprints:
            bp_id = bp.get("id", "")
            title = bp.get("title") or bp.get("name") or bp_id
            status = bp.get("status", "draft")
            badge = _status_badge(status)
            rows_html += (
                f'<tr class="hover:bg-gray-50 cursor-pointer" '
                f'    hx-get="/ui/pipeline/blueprint/{bp_id}" '
                f'    hx-target="#content" hx-push-url="true" hx-select="#content-inner">'
                f'  <td class="px-4 py-3 text-sm font-medium text-gray-900">{title}</td>'
                f'  <td class="px-4 py-3 text-sm text-gray-500">{badge}</td>'
                f'  <td class="px-4 py-3 text-sm text-gray-400">{bp.get("created_at", "")[:10]}</td>'
                f"</tr>"
            )
        if not rows_html:
            rows_html = (
                '<tr><td colspan="3" class="px-4 py-6 text-center text-sm text-gray-400">'
                + (f"Error: {error}" if error else "No blueprints yet.")
                + "</td></tr>"
            )

        html = (
            '<div id="content-inner" class="p-6">'
            '<div class="flex items-center justify-between mb-6">'
            '<h2 class="font-heading text-xl text-gray-900">SAC Blueprints</h2>'
            "</div>"
            '<div class="bg-white rounded-lg shadow-sm overflow-hidden">'
            '<table class="w-full text-left">'
            "<thead><tr>"
            '<th class="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Title</th>'
            '<th class="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>'
            '<th class="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Created</th>'
            "</tr></thead>"
            f"<tbody>{rows_html}</tbody>"
            "</table></div></div>"
        )
        return HTMLResponse(html)

    @router.get("/ui/pipeline/blueprint/{bp_id}", response_class=HTMLResponse)
    async def blueprint_detail(bp_id: str, request: Request):
        """SAC blueprint detail with approval panel."""
        blueprint: Optional[dict] = None
        approval: Optional[dict] = None
        error: Optional[str] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.blueprint_generator import get_blueprint  # noqa: PLC0415
            from spec2sphere.governance.approvals import get_approval_for_artifact, CHECKLISTS  # noqa: PLC0415

            blueprint = await get_blueprint(bp_id)
            if blueprint:
                _str_ids(blueprint)
                blueprint["pages"] = _safe_json(blueprint.get("pages"))

                try:
                    approval = await get_approval_for_artifact("sac_blueprint", bp_id)
                    if approval:
                        _str_ids(approval)
                        approval["checklist"] = _safe_json(approval.get("checklist"))
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Blueprint detail error: %s", exc)
            error = str(exc)

        if blueprint is None and not error:
            error = "Blueprint not found"

        from spec2sphere.governance.approvals import CHECKLISTS  # noqa: PLC0415

        checklist_template = CHECKLISTS.get("sac_blueprint", [])

        return _render(
            request,
            "partials/blueprint.html",
            {
                "active_page": "pipeline",
                "blueprint": blueprint,
                "approval": approval,
                "checklist_template": checklist_template,
                "error": error,
            },
        )

    @router.post("/ui/pipeline/blueprint/{hla_id}/generate", response_class=HTMLResponse)
    async def generate_blueprint_route(hla_id: str, request: Request):
        """Generate an SAC blueprint from an approved HLA."""
        try:
            ctx = await _get_ctx()
            llm = _get_llm()
            from spec2sphere.pipeline.blueprint_generator import generate_blueprint  # noqa: PLC0415

            result = await generate_blueprint(hla_id, ctx, llm)
            bp_id = result.get("blueprint_id", "") if isinstance(result, dict) else str(result)
            return HTMLResponse(
                f'<div class="p-3 bg-green-50 border border-green-200 rounded-lg">'
                f'<p class="text-sm font-medium text-green-700">SAC blueprint generated.</p>'
                f'<a href="/ui/pipeline/blueprint/{bp_id}" '
                f'   hx-get="/ui/pipeline/blueprint/{bp_id}" '
                f'   hx-target="#content" hx-push-url="true" hx-select="#content-inner" '
                f'   class="text-xs text-petrol underline mt-1 inline-block">View Blueprint →</a>'
                f"</div>"
            )
        except Exception as exc:
            logger.error("Blueprint generation for HLA %s failed: %s", hla_id, exc)
            return HTMLResponse(
                f'<div class="p-3 bg-red-50 border border-red-200 rounded-lg">'
                f'<p class="text-sm text-red-700">Blueprint generation failed: {exc}</p>'
                f"</div>"
            )

    @router.post("/ui/pipeline/blueprint/{bp_id}/submit-review", response_class=HTMLResponse)
    async def submit_blueprint_review(bp_id: str, request: Request):
        """Submit SAC blueprint for review."""
        try:
            ctx = await _get_ctx()
            from spec2sphere.governance.approvals import submit_for_review  # noqa: PLC0415

            approval = await submit_for_review(
                artifact_type="sac_blueprint",
                artifact_id=bp_id,
                ctx=ctx,
                reviewer_id=None,
            )
            _str_ids(approval)
            approval_id = approval.get("id", "")
            return HTMLResponse(
                f'<div class="p-3 bg-amber-50 border border-amber-200 rounded-lg">'
                f'<p class="text-sm font-medium text-amber-700">Blueprint submitted for review.</p>'
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

    return router
