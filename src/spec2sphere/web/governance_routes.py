"""Governance routes: reports, audit log, lab, and release management.

Provides HTMX-driven pages for:
  - Reports & documentation generation (HTML/Markdown/PDF)
  - Audit log viewer with filtering
  - Artifact Learning Lab (experiments + learned templates)
  - Release package assembly and download
"""

from __future__ import annotations

import logging
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates

from spec2sphere.db import _get_conn

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))

_OUTPUT_DIR = Path("output")


def _render(request: Request, template_name: str, ctx: dict) -> HTMLResponse:
    """Render a Jinja2 partial template (looked up in partials/ subdirectory)."""
    ctx["request"] = request
    ctx.setdefault("active_page", "reports")
    return _templates.TemplateResponse(request, f"partials/{template_name}", ctx)


def _str_record(row) -> dict:
    import uuid as _uuid

    d = dict(row)
    for k, v in list(d.items()):
        if isinstance(v, _uuid.UUID):
            d[k] = str(v)
    return d


async def _fetch_project_data(conn, project_id: str) -> dict:
    """Fetch all project data needed for report generation."""
    project = await conn.fetchrow("SELECT * FROM projects WHERE id = $1", project_id)
    if not project:
        return {}
    data: dict = {"project": _str_record(project)}

    customer_row = await conn.fetchrow("SELECT * FROM customers WHERE id = $1", data["project"].get("customer_id"))
    data["customer"] = _str_record(customer_row) if customer_row else {}

    rows = await conn.fetch("SELECT * FROM requirements WHERE project_id = $1 ORDER BY created_at", project_id)
    data["requirements"] = [_str_record(r) for r in rows]

    rows = await conn.fetch("SELECT * FROM hla_documents WHERE project_id = $1 ORDER BY created_at", project_id)
    data["hla_documents"] = [_str_record(r) for r in rows]

    rows = await conn.fetch("SELECT * FROM tech_specs WHERE project_id = $1 ORDER BY created_at", project_id)
    data["tech_specs"] = [_str_record(r) for r in rows]

    rows = await conn.fetch(
        "SELECT * FROM architecture_decisions WHERE project_id = $1 ORDER BY created_at", project_id
    )
    data["architecture_decisions"] = [_str_record(r) for r in rows]

    rows = await conn.fetch("SELECT * FROM technical_objects WHERE project_id = $1 ORDER BY created_at", project_id)
    data["technical_objects"] = [_str_record(r) for r in rows]

    rows = await conn.fetch(
        "SELECT * FROM reconciliation_results WHERE project_id = $1 ORDER BY created_at DESC LIMIT 100",
        project_id,
    )
    data["reconciliation_results"] = [_str_record(r) for r in rows]

    rows = await conn.fetch(
        "SELECT * FROM approvals WHERE project_id = $1 ORDER BY created_at DESC LIMIT 50",
        project_id,
    )
    data["approvals"] = [_str_record(r) for r in rows]

    return data


def create_governance_routes() -> APIRouter:
    """Return an APIRouter with reports, audit log, lab, and release routes."""
    router = APIRouter()

    # ── Reports Page ──────────────────────────────────────────────────────────

    @router.get("/ui/reports", response_class=HTMLResponse)
    async def reports_page(request: Request):
        """Reports & documentation — list release packages + static report files."""
        release_packages: list[dict] = []
        reports: list[dict] = []
        error: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            rows = await conn.fetch(
                """
                SELECT rp.id, rp.version, rp.status, rp.created_at,
                       p.name AS project_name
                FROM release_packages rp
                LEFT JOIN projects p ON p.id = rp.project_id
                ORDER BY rp.created_at DESC
                LIMIT 50
                """
            )
            release_packages = [_str_record(r) for r in rows]

            # Also list available projects for the generate form
            proj_rows = await conn.fetch("SELECT id, name FROM projects ORDER BY name LIMIT 100")
            projects = [_str_record(r) for r in proj_rows]
        except Exception as exc:
            logger.warning("reports_page DB error: %s", exc)
            error = str(exc)
            projects = []
        finally:
            if conn:
                try:
                    await conn.close()
                except Exception:
                    pass

        # Static reports from output/reports/
        reports_dir = _OUTPUT_DIR / "reports"
        if reports_dir.exists():
            for f in sorted(reports_dir.iterdir()):
                if f.is_file():
                    reports.append(
                        {
                            "name": f.name,
                            "size": f.stat().st_size,
                            "url": f"/reports/{f.name}",
                        }
                    )

        return _render(
            request,
            "reports_v2.html",
            {
                "reports": reports,
                "release_packages": release_packages,
                "projects": projects,
                "error": error,
                "active_page": "reports",
            },
        )

    # ── Audit Log Page ────────────────────────────────────────────────────────

    @router.get("/ui/audit-log", response_class=HTMLResponse)
    async def audit_log_page(
        request: Request,
        user: Optional[str] = None,
        action: Optional[str] = None,
        resource_type: Optional[str] = None,
        trace_id: Optional[str] = None,
        limit: int = 50,
    ):
        """Audit log — filterable view of all audit_log entries."""
        entries: list[dict] = []
        error: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            conditions = ["1=1"]
            params: list = []
            idx = 1

            if user:
                conditions.append(f"user_id::text ILIKE ${idx}")
                params.append(f"%{user}%")
                idx += 1
            if action:
                conditions.append(f"action ILIKE ${idx}")
                params.append(f"%{action}%")
                idx += 1
            if resource_type:
                conditions.append(f"resource_type ILIKE ${idx}")
                params.append(f"%{resource_type}%")
                idx += 1
            if trace_id:
                conditions.append(f"trace_id::text = ${idx}")
                params.append(trace_id)
                idx += 1

            where = " AND ".join(conditions)
            rows = await conn.fetch(
                f"""
                SELECT id, created_at, action, resource_type, resource_id,
                       user_id, status_code, duration_ms, trace_id, details
                FROM audit_log
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT {min(limit, 500)}
                """,
                *params,
            )
            entries = [_str_record(r) for r in rows]
        except Exception as exc:
            logger.warning("audit_log_page DB error: %s", exc)
            error = str(exc)
        finally:
            if conn:
                try:
                    await conn.close()
                except Exception:
                    pass

        return _render(
            request,
            "audit_log.html",
            {
                "entries": entries,
                "error": error,
                "filter_user": user or "",
                "filter_action": action or "",
                "filter_resource": resource_type or "",
                "filter_trace": trace_id or "",
                "active_page": "audit-log",
            },
        )

    # ── Lab Page ──────────────────────────────────────────────────────────────

    @router.get("/ui/lab", response_class=HTMLResponse)
    async def lab_page(request: Request):
        """Artifact Learning Lab — experiments and learned templates."""
        experiments: list[dict] = []
        templates: list[dict] = []
        error: Optional[str] = None
        conn = None
        try:
            conn = await _get_conn()
            exp_rows = await conn.fetch(
                """
                SELECT id, platform, object_type, experiment_type, route,
                       status, created_at
                FROM lab_experiments
                ORDER BY created_at DESC
                LIMIT 30
                """
            )
            experiments = [_str_record(r) for r in exp_rows]

            tmpl_rows = await conn.fetch(
                """
                SELECT id, platform, object_type, approved, confidence,
                       reviewer_id, created_at
                FROM learned_templates
                ORDER BY created_at DESC
                LIMIT 30
                """
            )
            templates = [_str_record(r) for r in tmpl_rows]
        except Exception as exc:
            logger.warning("lab_page DB error: %s", exc)
            error = str(exc)
        finally:
            if conn:
                try:
                    await conn.close()
                except Exception:
                    pass

        return _render(
            request,
            "lab.html",
            {
                "experiments": experiments,
                "templates": templates,
                "error": error,
                "active_page": "lab",
            },
        )

    # ── API: Generate Report ──────────────────────────────────────────────────

    @router.post("/api/governance/generate-report")
    async def generate_report(request: Request):
        """Generate an HTML, Markdown, or PDF report for a project."""
        body = await request.json()
        project_id = body.get("project_id", "")
        fmt = body.get("format", "html")

        conn = None
        try:
            conn = await _get_conn()
            data = await _fetch_project_data(conn, project_id)
        except Exception as exc:
            logger.warning("generate_report DB error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)
        finally:
            if conn:
                try:
                    await conn.close()
                except Exception:
                    pass

        if not data:
            return JSONResponse({"error": "Project not found"}, status_code=404)

        try:
            if fmt == "html":
                from spec2sphere.governance.doc_generator import render_html_report  # noqa: PLC0415

                content = render_html_report(data)
                return Response(
                    content=content,
                    media_type="text/html",
                    headers={"Content-Disposition": f'inline; filename="report_{project_id}.html"'},
                )
            elif fmt == "markdown":
                from spec2sphere.governance.doc_generator import render_markdown_report  # noqa: PLC0415

                content = render_markdown_report(data)
                return Response(
                    content=content,
                    media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="report_{project_id}.md"'},
                )
            elif fmt == "pdf":
                from spec2sphere.governance.doc_generator import render_pdf_report  # noqa: PLC0415

                content = render_pdf_report(data)
                return Response(
                    content=content,
                    media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="report_{project_id}.pdf"'},
                )
            else:
                return JSONResponse({"error": f"Unknown format: {fmt}"}, status_code=400)
        except Exception as exc:
            logger.error("generate_report render error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

    # ── API: Assemble Release ─────────────────────────────────────────────────

    @router.post("/api/governance/release")
    async def assemble_release(request: Request):
        """Assemble a release ZIP for a project and store a reference in DB."""
        body = await request.json()
        project_id = body.get("project_id", "")
        version = body.get("version", "1.0.0")

        conn = None
        try:
            conn = await _get_conn()
            data = await _fetch_project_data(conn, project_id)
            if not data:
                return JSONResponse({"error": "Project not found"}, status_code=404)
        except Exception as exc:
            logger.warning("assemble_release DB error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

        try:
            from spec2sphere.governance.release import assemble_release_package  # noqa: PLC0415

            zip_bytes = assemble_release_package(data, version=version)
        except Exception as exc:
            logger.error("assemble_release_package error: %s", exc)
            if conn:
                try:
                    await conn.close()
                except Exception:
                    pass
            return JSONResponse({"error": str(exc)}, status_code=500)

        release_id = str(uuid.uuid4())
        try:
            await conn.execute(
                """
                INSERT INTO release_packages (id, project_id, version, status, created_at)
                VALUES ($1, $2, $3, 'ready', NOW())
                ON CONFLICT (id) DO NOTHING
                """,
                release_id,
                project_id,
                version,
            )
        except Exception as exc:
            logger.warning("Could not store release_package record: %s", exc)
        finally:
            try:
                await conn.close()
            except Exception:
                pass

        project_name = (data.get("project") or {}).get("name", "project")
        filename = f"release_{project_name}_{version}.zip".replace(" ", "_")

        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # ── API: Download Release ─────────────────────────────────────────────────

    @router.get("/api/governance/release/{release_id}/download")
    async def download_release(release_id: str):
        """Download a previously assembled release package (future work)."""
        return JSONResponse(
            {"error": "Release package storage not yet implemented. Use /api/governance/release to regenerate."},
            status_code=404,
        )

    # ── API: Graduate Template ────────────────────────────────────────────────

    @router.post("/api/lab/templates/{template_id}/graduate")
    async def graduate_template_route(template_id: str, request: Request):
        """Approve or reject a learned template."""
        body = await request.json()
        approved = bool(body.get("approved", False))

        try:
            from spec2sphere.artifact_lab.template_store import graduate_template  # noqa: PLC0415

            await graduate_template(
                template_id=template_id,
                approved=approved,
                reviewer_id="ui-user",
            )
            return JSONResponse({"status": "approved" if approved else "rejected", "template_id": template_id})
        except Exception as exc:
            logger.error("graduate_template error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

    return router
