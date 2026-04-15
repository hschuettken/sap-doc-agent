"""Factory Monitor, Reconciliation, Visual QA, and Route Fitness UI routes.

Provides HTMX-driven pages for:
  - Deployment factory monitor (runs, steps, live browser view)
  - Reconciliation results with approval actions
  - Visual QA results grid
  - Route fitness lab
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from spec2sphere.db import _get_conn

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


# ── Status colour maps ────────────────────────────────────────────────────────

RUN_STATUS_CLASSES = {
    "running": "bg-blue-100 text-blue-700",
    "completed": "bg-green-100 text-green-700",
    "failed": "bg-red-100 text-red-700",
    "queued": "bg-amber-100 text-amber-700",
    "cancelled": "bg-gray-100 text-gray-500",
}

RECON_STATUS_CLASSES = {
    "pass": "bg-green-100 text-green-700",
    "within_tolerance": "bg-yellow-100 text-yellow-700",
    "expected_difference": "bg-blue-100 text-blue-700",
    "probable_defect": "bg-red-100 text-red-700",
    "needs_review": "bg-gray-100 text-gray-600",
}

ROUTE_TYPE_CLASSES = {
    "sql": "bg-indigo-100 text-indigo-700",
    "rest": "bg-teal-100 text-teal-700",
    "file": "bg-amber-100 text-amber-700",
    "cdp": "bg-purple-100 text-purple-700",
}


def _render(request: Request, template_name: str, ctx: dict) -> HTMLResponse:
    """Render a Jinja2 partial template (looked up in partials/ subdirectory)."""
    ctx["request"] = request
    ctx.setdefault("active_page", "factory")
    return _templates.TemplateResponse(request, f"partials/{template_name}", ctx)


# ── Helper: stringify UUID values in a record dict ────────────────────────────


def _str_record(row) -> dict:
    import uuid as _uuid

    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, _uuid.UUID):
            d[k] = str(v)
    return d


def create_factory_routes() -> APIRouter:
    """Return an APIRouter with all factory monitor, reconciliation, visual QA, and fitness routes."""
    router = APIRouter()

    # ── Factory Monitor ───────────────────────────────────────────────────────

    @router.get("/ui/factory", response_class=HTMLResponse)
    async def factory_monitor(request: Request):
        """Factory monitor — list of recent deployment runs."""
        runs: list[dict] = []
        error: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            rows = await conn.fetch(
                """
                SELECT dr.id, dr.status, dr.started_at, dr.completed_at,
                       dr.summary, dr.environment,
                       p.name AS project_name
                FROM deployment_runs dr
                LEFT JOIN projects p ON p.id = dr.project_id
                ORDER BY dr.created_at DESC
                LIMIT 20
                """
            )
            runs = [_str_record(r) for r in rows]
        except Exception as exc:
            logger.warning("factory_monitor: %s", exc)
            error = str(exc)
        finally:
            if conn:
                await conn.close()

        return _render(
            request,
            "factory.html",
            {
                "runs": runs,
                "error": error,
                "status_classes": RUN_STATUS_CLASSES,
                "active_page": "factory",
            },
        )

    @router.get("/api/factory/runs/{run_id}/steps")
    async def factory_run_steps(run_id: str, request: Request):
        """Return deployment steps for a run as JSON."""
        steps: list[dict] = []
        conn = None
        try:
            conn = await _get_conn()
            rows = await conn.fetch(
                """
                SELECT id, object_name, object_type, status, started_at,
                       completed_at, error_message, step_order
                FROM deployment_steps
                WHERE run_id = $1
                ORDER BY step_order ASC, started_at ASC
                """,
                run_id,
            )
            steps = [_str_record(r) for r in rows]
        except Exception as exc:
            logger.warning("factory_run_steps(%s): %s", run_id, exc)
        finally:
            if conn:
                await conn.close()

        return JSONResponse({"run_id": run_id, "steps": steps})

    @router.get("/api/factory/active")
    async def factory_active(request: Request):
        """Check if any deployment run is currently active."""
        conn = None
        try:
            conn = await _get_conn()
            row = await conn.fetchrow(
                """
                SELECT id FROM deployment_runs
                WHERE status = 'running'
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            if row:
                return JSONResponse({"active": True, "run_id": str(row["id"])})
        except Exception as exc:
            logger.warning("factory_active: %s", exc)
        finally:
            if conn:
                await conn.close()

        return JSONResponse({"active": False, "run_id": None})

    @router.post("/api/factory/deploy/dsp")
    async def factory_deploy_dsp(request: Request):
        """Trigger run_dsp_deployment Celery task."""
        body = await request.json()
        tech_spec_id = body.get("tech_spec_id", "")
        tenant_id = body.get("tenant_id", "")
        customer_id = body.get("customer_id", "")
        project_id = body.get("project_id", "")
        environment = body.get("environment", "sandbox")

        try:
            from spec2sphere.tasks.factory_tasks import run_dsp_deployment

            result = run_dsp_deployment.delay(
                tenant_id=tenant_id,
                customer_id=customer_id,
                project_id=project_id,
                tech_spec_id=tech_spec_id,
                environment=environment,
            )
            return JSONResponse({"task_id": result.id, "status": "queued"})
        except Exception as exc:
            logger.warning("factory_deploy_dsp: %s", exc)
            return JSONResponse({"task_id": None, "status": "error", "error": str(exc)}, status_code=500)

    @router.post("/api/factory/deploy/sac")
    async def factory_deploy_sac(request: Request):
        """Trigger run_sac_deployment Celery task."""
        body = await request.json()
        blueprint_id = body.get("blueprint_id", "")
        tenant_id = body.get("tenant_id", "")
        customer_id = body.get("customer_id", "")
        project_id = body.get("project_id", "")
        environment = body.get("environment", "sandbox")

        try:
            from spec2sphere.tasks.factory_tasks import run_sac_deployment

            result = run_sac_deployment.delay(
                tenant_id=tenant_id,
                customer_id=customer_id,
                project_id=project_id,
                blueprint_id=blueprint_id,
                environment=environment,
            )
            return JSONResponse({"task_id": result.id, "status": "queued"})
        except Exception as exc:
            logger.warning("factory_deploy_sac: %s", exc)
            return JSONResponse({"task_id": None, "status": "error", "error": str(exc)}, status_code=500)

    # ── Reconciliation ────────────────────────────────────────────────────────

    @router.get("/ui/reconciliation", response_class=HTMLResponse)
    async def reconciliation_list(request: Request):
        """Reconciliation results list."""
        results: list[dict] = []
        error: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            rows = await conn.fetch(
                """
                SELECT rr.id, rr.test_case_key, rr.baseline_value, rr.candidate_value,
                       rr.delta, rr.status, rr.approved_by, rr.created_at,
                       ts.name AS test_spec_name,
                       p.name AS project_name
                FROM reconciliation_results rr
                LEFT JOIN test_specs ts ON ts.id = rr.test_spec_id
                LEFT JOIN projects p ON p.id = rr.project_id
                ORDER BY rr.created_at DESC
                LIMIT 50
                """
            )
            results = [_str_record(r) for r in rows]
        except Exception as exc:
            logger.warning("reconciliation_list: %s", exc)
            error = str(exc)
        finally:
            if conn:
                await conn.close()

        return _render(
            request,
            "reconciliation.html",
            {
                "results": results,
                "error": error,
                "status_classes": RECON_STATUS_CLASSES,
                "active_page": "reconciliation",
            },
        )

    @router.post("/api/reconciliation/approve/{result_id}")
    async def reconciliation_approve(result_id: str, request: Request):
        """Approve a reconciliation result."""
        body: dict = {}
        try:
            body = await request.json()
        except Exception:
            pass

        approved_by = body.get("approved_by", "system")
        conn = None
        try:
            conn = await _get_conn()
            await conn.execute(
                """
                UPDATE reconciliation_results
                SET approved_by = $1, updated_at = NOW()
                WHERE id = $2
                """,
                approved_by,
                result_id,
            )
            return JSONResponse({"success": True, "result_id": result_id, "approved_by": approved_by})
        except Exception as exc:
            logger.warning("reconciliation_approve(%s): %s", result_id, exc)
            return JSONResponse({"success": False, "error": str(exc)}, status_code=500)
        finally:
            if conn:
                await conn.close()

    # ── Visual QA ─────────────────────────────────────────────────────────────

    @router.get("/ui/visual-qa", response_class=HTMLResponse)
    async def visual_qa_list(request: Request):
        """Visual QA results grid."""
        results: list[dict] = []
        error: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            rows = await conn.fetch(
                """
                SELECT vq.id, vq.title, vq.status, vq.screenshot_path,
                       vq.differences, vq.created_at,
                       sb.name AS blueprint_name,
                       p.name AS project_name
                FROM visual_qa_results vq
                LEFT JOIN sac_blueprints sb ON sb.id = vq.blueprint_id
                LEFT JOIN projects p ON p.id = vq.project_id
                ORDER BY vq.created_at DESC
                LIMIT 50
                """
            )
            results = [_str_record(r) for r in rows]
        except Exception as exc:
            logger.warning("visual_qa_list: %s", exc)
            error = str(exc)
        finally:
            if conn:
                await conn.close()

        return _render(
            request,
            "visual_qa.html",
            {
                "results": results,
                "error": error,
                "active_page": "visual-qa",
            },
        )

    # ── Route Fitness ─────────────────────────────────────────────────────────

    @router.get("/ui/lab/fitness", response_class=HTMLResponse)
    async def route_fitness_list(request: Request):
        """Route fitness scores lab view."""
        fitness_rows: list[dict] = []
        error: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            rows = await conn.fetch(
                """
                SELECT rf.id, rf.route, rf.route_type, rf.object_type,
                       rf.action, rf.success_count, rf.failure_count,
                       rf.total_attempts, rf.avg_duration_ms, rf.fitness_score,
                       rf.last_failure_at, rf.updated_at,
                       c.name AS customer_name
                FROM route_fitness rf
                LEFT JOIN customers c ON c.id = rf.customer_id
                ORDER BY rf.fitness_score ASC
                LIMIT 100
                """
            )
            fitness_rows = [_str_record(r) for r in rows]
        except Exception as exc:
            logger.warning("route_fitness_list: %s", exc)
            error = str(exc)
        finally:
            if conn:
                await conn.close()

        # Compute success rate per row
        for row in fitness_rows:
            total = row.get("total_attempts") or 0
            success = row.get("success_count") or 0
            row["success_rate"] = round((success / total) * 100, 1) if total > 0 else 0.0

        return _render(
            request,
            "route_fitness.html",
            {
                "fitness_rows": fitness_rows,
                "error": error,
                "route_type_classes": ROUTE_TYPE_CLASSES,
                "active_page": "lab",
            },
        )

    # ── Browser Viewer ────────────────────────────────────────────────────────

    @router.get("/ui/browser-view", response_class=HTMLResponse)
    async def browser_viewer(
        request: Request,
        tenant: Optional[str] = None,
        env: Optional[str] = "sandbox",
    ):
        """Embedded live browser view via noVNC."""
        from uuid import UUID

        novnc_url = ""
        viewer_count = 0

        try:
            from spec2sphere.browser.novnc import get_novnc_url, get_viewer_count

            if tenant:
                try:
                    tenant_uuid = UUID(tenant)
                    novnc_url = get_novnc_url(tenant_uuid, env or "sandbox", external=True)
                    viewer_count = get_viewer_count(tenant_uuid, env or "sandbox")
                except (ValueError, TypeError) as exc:
                    logger.debug("browser_viewer: invalid tenant UUID %s: %s", tenant, exc)
        except Exception as exc:
            logger.warning("browser_viewer novnc import: %s", exc)

        return _render(
            request,
            "browser_viewer.html",
            {
                "novnc_url": novnc_url,
                "viewer_count": viewer_count,
                "tenant": tenant,
                "env": env,
                "active_page": "browser",
            },
        )

    return router
