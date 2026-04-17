"""Pipeline UI routes: HLA architecture and approvals."""

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
)

logger = logging.getLogger(__name__)


def create_architecture_routes() -> APIRouter:
    """Return an APIRouter with HLA architecture and approvals routes."""
    router = APIRouter()

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
        tech_specs: list[dict] = []
        blueprints: list[dict] = []
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

                # Tech specs generated from this HLA
                try:
                    from spec2sphere.pipeline.tech_spec_generator import list_tech_specs

                    all_ts = await list_tech_specs(ctx)
                    tech_specs = [_str_ids(ts) or ts for ts in all_ts if str(ts.get("hla_id", "")) == hla_id]
                except Exception:
                    pass

                # SAC blueprints generated from this HLA (via tech_specs)
                try:
                    from spec2sphere.pipeline.blueprint_generator import list_blueprints

                    ts_ids = {str(ts.get("id", "")) for ts in tech_specs}
                    all_bp = await list_blueprints(ctx)
                    blueprints = [_str_ids(bp) or bp for bp in all_bp if str(bp.get("tech_spec_id", "")) in ts_ids]
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
                "tech_specs": tech_specs,
                "blueprints": blueprints,
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

    @router.get("/ui/pipeline/architecture/compare", response_class=HTMLResponse)
    async def compare_hla_versions(request: Request):
        """Compare two HLA versions side by side."""
        hla_a = request.query_params.get("a", "")
        hla_b = request.query_params.get("b", "")
        diff: Optional[dict] = None
        error: Optional[str] = None

        if hla_a and hla_b:
            try:
                from spec2sphere.pipeline.hla_generator import compare_hla_versions as _compare

                diff = await _compare(hla_a, hla_b)
            except Exception as exc:
                logger.warning("HLA compare error: %s", exc)
                error = str(exc)

        if diff is None and not error:
            error = "Select two HLA versions to compare (pass ?a=<id>&b=<id>)."

        # Render inline HTML fragment for errors
        if error:
            return HTMLResponse(
                f'<div class="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">'
                f'<p class="text-sm text-yellow-700">{error}</p></div>'
            )

        # Build flat added/removed/changed lists for the diff_viewer partial
        diff_added: list[dict] = []
        diff_removed: list[dict] = []
        diff_changed: list[dict] = []

        for v in diff.get("views", {}).get("added", []):
            diff_added.append({"field": "View", "value": str(v)})
        for v in diff.get("views", {}).get("removed", []):
            diff_removed.append({"field": "View", "value": str(v)})
        for v in diff.get("views", {}).get("changed", []):
            name = v.get("name", str(v)) if isinstance(v, dict) else str(v)
            diff_changed.append(
                {
                    "field": "View",
                    "name": name,
                    "before": str(v.get("before", "")) if isinstance(v, dict) else "",
                    "after": str(v.get("after", "")) if isinstance(v, dict) else "",
                }
            )

        for d in diff.get("key_decisions", {}).get("added", []):
            diff_added.append({"field": "Decision", "value": str(d)})
        for d in diff.get("key_decisions", {}).get("removed", []):
            diff_removed.append({"field": "Decision", "value": str(d)})
        for d in diff.get("key_decisions", {}).get("changed", []):
            name = d.get("name", str(d)) if isinstance(d, dict) else str(d)
            diff_changed.append(
                {
                    "field": "Decision",
                    "name": name,
                    "before": str(d.get("before", "")) if isinstance(d, dict) else "",
                    "after": str(d.get("after", "")) if isinstance(d, dict) else "",
                }
            )

        version_a = diff.get("version_a", "?")
        version_b = diff.get("version_b", "?")

        return _render(
            request,
            "partials/diff_viewer.html",
            {
                "diff": {
                    "added": diff_added,
                    "removed": diff_removed,
                    "changed": diff_changed,
                },
                "title": f"HLA Comparison: v{version_a} → v{version_b}",
                "mode": "inline",
            },
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

    return router
