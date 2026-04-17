"""Pipeline UI routes: tech spec generation and review."""

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


def create_techspec_routes() -> APIRouter:
    """Return an APIRouter with tech spec routes."""
    router = APIRouter()

    @router.get("/ui/pipeline/techspec", response_class=HTMLResponse)
    async def techspec_list(request: Request):
        """List tech specs."""
        tech_specs: list[dict] = []
        error: Optional[str] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.tech_spec_generator import list_tech_specs  # noqa: PLC0415

            tech_specs = await list_tech_specs(ctx)
            for ts in tech_specs:
                _str_ids(ts)
        except Exception as exc:
            logger.warning("Tech spec list error: %s", exc)
            error = str(exc)

        rows_html = ""
        for ts in tech_specs:
            ts_id = ts.get("id", "")
            title = ts.get("title") or ts.get("name") or ts_id
            status = ts.get("status", "draft")
            badge = _status_badge(status)
            rows_html += (
                f'<tr class="hover:bg-gray-50 cursor-pointer" '
                f'    hx-get="/ui/pipeline/techspec/{ts_id}" '
                f'    hx-target="#content" hx-push-url="true" hx-select="#content-inner">'
                f'  <td class="px-4 py-3 text-sm font-medium text-gray-900">{title}</td>'
                f'  <td class="px-4 py-3 text-sm text-gray-500">{badge}</td>'
                f'  <td class="px-4 py-3 text-sm text-gray-400">{ts.get("created_at", "")[:10]}</td>'
                f"</tr>"
            )
        if not rows_html:
            rows_html = (
                '<tr><td colspan="3" class="px-4 py-6 text-center text-sm text-gray-400">'
                + (f"Error: {error}" if error else "No tech specs yet.")
                + "</td></tr>"
            )

        html = (
            '<div id="content-inner" class="p-6">'
            '<div class="flex items-center justify-between mb-6">'
            '<h2 class="font-heading text-xl text-gray-900">Tech Specs</h2>'
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

    @router.get("/ui/pipeline/techspec/{ts_id}", response_class=HTMLResponse)
    async def techspec_detail(ts_id: str, request: Request):
        """Tech spec detail with technical objects and approval panel."""
        tech_spec: Optional[dict] = None
        objects: list[dict] = []
        approval: Optional[dict] = None
        error: Optional[str] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.tech_spec_generator import get_tech_spec, get_technical_objects  # noqa: PLC0415
            from spec2sphere.governance.approvals import get_approval_for_artifact, CHECKLISTS  # noqa: PLC0415

            tech_spec = await get_tech_spec(ts_id)
            if tech_spec:
                _str_ids(tech_spec)
                tech_spec["objects"] = _safe_json(tech_spec.get("objects"))
                tech_spec["dependency_graph"] = _safe_json(tech_spec.get("dependency_graph"))
                tech_spec["deployment_order"] = _safe_json(tech_spec.get("deployment_order"))

                objects = await get_technical_objects(ts_id)
                for obj in objects:
                    _str_ids(obj)
                    obj["definition"] = _safe_json(obj.get("definition"))

                try:
                    approval = await get_approval_for_artifact("tech_spec", ts_id)
                    if approval:
                        _str_ids(approval)
                        approval["checklist"] = _safe_json(approval.get("checklist"))
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("Tech spec detail error: %s", exc)
            error = str(exc)

        if tech_spec is None and not error:
            error = "Tech spec not found"

        from spec2sphere.governance.approvals import CHECKLISTS  # noqa: PLC0415

        checklist_template = CHECKLISTS.get("tech_spec", [])

        return _render(
            request,
            "partials/techspec.html",
            {
                "active_page": "pipeline",
                "tech_spec": tech_spec,
                "objects": objects,
                "approval": approval,
                "checklist_template": checklist_template,
                "error": error,
            },
        )

    @router.post("/ui/pipeline/techspec/{hla_id}/generate", response_class=HTMLResponse)
    async def generate_techspec_route(hla_id: str, request: Request):
        """Generate a tech spec from an approved HLA."""
        try:
            ctx = await _get_ctx()
            llm = _get_llm()
            from spec2sphere.pipeline.tech_spec_generator import generate_tech_spec  # noqa: PLC0415

            result = await generate_tech_spec(hla_id, ctx, llm)
            ts_id = result.get("tech_spec_id", "") if isinstance(result, dict) else str(result)
            return HTMLResponse(
                f'<div class="p-3 bg-green-50 border border-green-200 rounded-lg">'
                f'<p class="text-sm font-medium text-green-700">Tech spec generated.</p>'
                f'<a href="/ui/pipeline/techspec/{ts_id}" '
                f'   hx-get="/ui/pipeline/techspec/{ts_id}" '
                f'   hx-target="#content" hx-push-url="true" hx-select="#content-inner" '
                f'   class="text-xs text-petrol underline mt-1 inline-block">View Tech Spec →</a>'
                f"</div>"
            )
        except Exception as exc:
            logger.error("Tech spec generation for HLA %s failed: %s", hla_id, exc)
            return HTMLResponse(
                f'<div class="p-3 bg-red-50 border border-red-200 rounded-lg">'
                f'<p class="text-sm text-red-700">Tech spec generation failed: {exc}</p>'
                f"</div>"
            )

    @router.post("/ui/pipeline/techspec/{ts_id}/submit-review", response_class=HTMLResponse)
    async def submit_techspec_review(ts_id: str, request: Request):
        """Submit tech spec for review."""
        try:
            ctx = await _get_ctx()
            from spec2sphere.governance.approvals import submit_for_review  # noqa: PLC0415

            approval = await submit_for_review(
                artifact_type="tech_spec",
                artifact_id=ts_id,
                ctx=ctx,
                reviewer_id=None,
            )
            _str_ids(approval)
            approval_id = approval.get("id", "")
            return HTMLResponse(
                f'<div class="p-3 bg-amber-50 border border-amber-200 rounded-lg">'
                f'<p class="text-sm font-medium text-amber-700">Tech spec submitted for review.</p>'
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

    @router.post("/ui/pipeline/techspec/{ts_id}/generate-tests", response_class=HTMLResponse)
    async def generate_tests_from_techspec(ts_id: str, request: Request):
        """Generate a test spec from an approved tech spec."""
        try:
            ctx = await _get_ctx()
            llm = _get_llm()
            from spec2sphere.pipeline.test_generator import generate_test_spec  # noqa: PLC0415

            result = await generate_test_spec(ts_id, ctx, llm)
            test_id = result.get("test_spec_id", "") if isinstance(result, dict) else str(result)
            return HTMLResponse(
                f'<div class="p-3 bg-green-50 border border-green-200 rounded-lg">'
                f'<p class="text-sm font-medium text-green-700">Test spec generated.</p>'
                f'<a href="/ui/pipeline/testspec/{test_id}" '
                f'   hx-get="/ui/pipeline/testspec/{test_id}" '
                f'   hx-target="#content" hx-push-url="true" hx-select="#content-inner" '
                f'   class="text-xs text-petrol underline mt-1 inline-block">View Test Spec →</a>'
                f"</div>"
            )
        except Exception as exc:
            logger.error("Test spec generation for tech spec %s failed: %s", ts_id, exc)
            return HTMLResponse(
                f'<div class="p-3 bg-red-50 border border-red-200 rounded-lg">'
                f'<p class="text-sm text-red-700">Test spec generation failed: {exc}</p>'
                f"</div>"
            )

    return router
