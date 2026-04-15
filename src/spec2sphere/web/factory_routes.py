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
        active_run_id: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            rows = await conn.fetch(
                """
                SELECT dr.id, dr.status, dr.started_at, dr.completed_at,
                       dr.summary,
                       p.name AS project_name
                FROM deployment_runs dr
                LEFT JOIN projects p ON p.id = dr.project_id
                ORDER BY dr.created_at DESC
                LIMIT 20
                """
            )
            runs = [_str_record(r) for r in rows]
            # Find active run for SSE stream
            active_row = await conn.fetchrow(
                "SELECT id FROM deployment_runs WHERE status = 'running' ORDER BY created_at DESC LIMIT 1"
            )
            if active_row:
                active_run_id = str(active_row["id"])
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
                "active_run_id": active_run_id,
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
                SELECT id, artifact_name, artifact_type, status, started_at,
                       completed_at, error_message, route_chosen, route_reason
                FROM deployment_steps
                WHERE run_id = $1
                ORDER BY started_at ASC
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
                       rr.delta, rr.delta_status AS status, rr.approved_by, rr.created_at,
                       ts.version AS test_spec_version,
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

        from spec2sphere.factory.reconciliation import compute_aggregate_summary  # noqa: PLC0415

        summary = compute_aggregate_summary([dict(r) for r in results])

        return _render(
            request,
            "reconciliation.html",
            {
                "results": results,
                "error": error,
                "status_classes": RECON_STATUS_CLASSES,
                "active_page": "reconciliation",
                "summary": summary,
            },
        )

    @router.get("/api/reconciliation/results/{result_id}", tags=["reconciliation"])
    async def get_reconciliation_detail(result_id: str):
        """Get detailed reconciliation result with full query results."""
        from uuid import UUID

        conn = await _get_conn()
        try:
            row = await conn.fetchrow(
                """
                SELECT rr.*, ts.test_mode, ts.tolerance_rules,
                       p.name as project_name
                FROM reconciliation_results rr
                LEFT JOIN test_specs ts ON ts.id = rr.test_spec_id
                LEFT JOIN projects p ON p.id = rr.project_id
                WHERE rr.id = $1
                """,
                UUID(result_id),
            )
        finally:
            await conn.close()
        if not row:
            from fastapi import HTTPException

            raise HTTPException(404, "Result not found")
        return _str_record(dict(row))

    @router.post("/api/reconciliation/approve/{result_id}", tags=["reconciliation"])
    async def reconciliation_approve(result_id: str, comment: str = "", user_id: str = "admin"):
        """Approve a reconciliation result with optional comment."""
        from uuid import UUID

        conn = await _get_conn()
        try:
            await conn.execute(
                """
                UPDATE reconciliation_results
                SET approved_by = $1, explanation = COALESCE(explanation, '') || $2
                WHERE id = $3
                """,
                UUID(user_id) if user_id != "admin" else None,
                ("\n--- Approved: " + comment) if comment else "",
                UUID(result_id),
            )
        finally:
            await conn.close()
        return {"status": "approved"}

    @router.get("/api/factory/progress/stream", tags=["factory"])
    async def factory_progress_stream(run_id: str):
        """SSE stream of deployment progress for a run."""
        from starlette.responses import StreamingResponse
        import asyncio
        import json as _json
        from uuid import UUID

        async def event_generator():
            while True:
                conn = await _get_conn()
                try:
                    run = await conn.fetchrow(
                        "SELECT status, summary FROM deployment_runs WHERE id = $1",
                        UUID(run_id),
                    )
                    steps = await conn.fetch(
                        "SELECT artifact_name, status, route_chosen, duration_seconds FROM deployment_steps WHERE run_id = $1 ORDER BY created_at",
                        UUID(run_id),
                    )
                finally:
                    await conn.close()

                data = {
                    "run_status": run["status"] if run else "unknown",
                    "steps": [_str_record(dict(s)) for s in steps],
                }
                yield f"data: {_json.dumps(data)}\n\n"

                if run and run["status"] in ("completed", "failed", "cancelled"):
                    break
                await asyncio.sleep(2)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

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
                SELECT vq.id, vq.page_id, vq.result AS status, vq.screenshot_path,
                       vq.differences, vq.created_at,
                       sb.title AS blueprint_name,
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
                SELECT rf.id, rf.route, rf.platform AS route_type, rf.object_type,
                       rf.action, rf.successes AS success_count,
                       (rf.attempts - rf.successes) AS failure_count,
                       rf.attempts AS total_attempts,
                       (rf.avg_duration_seconds * 1000.0) AS avg_duration_ms,
                       rf.fitness_score,
                       rf.updated_at AS last_failure_at, rf.updated_at,
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
        task_name = ""

        try:
            from spec2sphere.browser.novnc import get_novnc_url, get_viewer_count  # noqa: PLC0415

            if tenant:
                try:
                    tenant_uuid = UUID(tenant)
                    novnc_url = get_novnc_url(tenant_uuid, env or "sandbox", external=True)
                    viewer_count = get_viewer_count(tenant_uuid, env or "sandbox")
                except (ValueError, TypeError) as exc:
                    logger.debug("browser_viewer: invalid tenant UUID %s: %s", tenant, exc)
        except Exception as exc:
            logger.warning("browser_viewer novnc import: %s", exc)

        # Fetch the active deployment run name for "Watching" overlay
        conn = None
        try:
            conn = await _get_conn()
            active_run = await conn.fetchrow(
                """
                SELECT dr.id, p.name AS project_name
                FROM deployment_runs dr
                LEFT JOIN projects p ON p.id = dr.project_id
                WHERE dr.status = 'running'
                ORDER BY dr.created_at DESC
                LIMIT 1
                """
            )
            if active_run:
                task_name = active_run["project_name"] or str(active_run["id"])
        except Exception as exc:
            logger.debug("browser_viewer: could not fetch active run: %s", exc)
        finally:
            if conn:
                await conn.close()

        return _render(
            request,
            "browser_viewer.html",
            {
                "novnc_url": novnc_url,
                "viewer_count": viewer_count,
                "tenant": tenant,
                "env": env,
                "task_name": task_name,
                "active_page": "browser",
            },
        )

    return router
