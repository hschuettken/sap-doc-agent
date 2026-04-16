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
    from uuid import UUID as _UUID  # noqa: PLC0415

    pid = _UUID(project_id) if isinstance(project_id, str) else project_id

    project = await conn.fetchrow("SELECT * FROM projects WHERE id = $1", pid)
    if not project:
        return {}
    data: dict = {"project": _str_record(project)}

    customer_id = project["customer_id"]
    customer_row = await conn.fetchrow("SELECT * FROM customers WHERE id = $1", customer_id)
    data["customer"] = _str_record(customer_row) if customer_row else {}

    rows = await conn.fetch("SELECT * FROM requirements WHERE project_id = $1 ORDER BY created_at", pid)
    data["requirements"] = [_str_record(r) for r in rows]

    rows = await conn.fetch("SELECT * FROM hla_documents WHERE project_id = $1 ORDER BY created_at", pid)
    data["hla_documents"] = [_str_record(r) for r in rows]

    rows = await conn.fetch("SELECT * FROM tech_specs WHERE project_id = $1 ORDER BY created_at", pid)
    data["tech_specs"] = [_str_record(r) for r in rows]

    rows = await conn.fetch("SELECT * FROM architecture_decisions WHERE project_id = $1 ORDER BY created_at", pid)
    data["architecture_decisions"] = [_str_record(r) for r in rows]

    rows = await conn.fetch("SELECT * FROM technical_objects WHERE project_id = $1 ORDER BY created_at", pid)
    data["technical_objects"] = [_str_record(r) for r in rows]

    rows = await conn.fetch(
        "SELECT * FROM reconciliation_results WHERE project_id = $1 ORDER BY created_at DESC LIMIT 100",
        pid,
    )
    data["reconciliation_results"] = [_str_record(r) for r in rows]

    rows = await conn.fetch(
        "SELECT * FROM approvals WHERE project_id = $1 ORDER BY created_at DESC LIMIT 50",
        pid,
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
            logger.error("generate_report render error: %s", exc, exc_info=True)
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

    # ── API: Experiment Detail ────────────────────────────────────────────────

    @router.get("/api/lab/experiments/{experiment_id}")
    async def get_experiment_detail(experiment_id: str):
        """Get experiment detail with diff for viewer."""
        conn = await _get_conn()
        try:
            row = await conn.fetchrow("SELECT * FROM lab_experiments WHERE id = $1::uuid", experiment_id)
        finally:
            await conn.close()
        if not row:
            return JSONResponse({"error": "Experiment not found"}, status_code=404)
        return JSONResponse(_str_record(row))

    # ── API: Mutation Catalog ─────────────────────────────────────────────────

    @router.get("/api/lab/mutations")
    async def list_mutations(platform: str = "dsp", object_type: str = "relational_view"):
        """Browse the mutation catalog."""
        from spec2sphere.artifact_lab.mutation_catalog import get_mutations  # noqa: PLC0415

        mutations = get_mutations(platform, object_type)
        return JSONResponse({"platform": platform, "object_type": object_type, "mutations": mutations})

    # ── API: Audit Compliance Summary ─────────────────────────────────────────

    @router.get("/api/audit/compliance-summary")
    async def compliance_summary():
        """Compliance summary: approval coverage and pending items."""
        conn = await _get_conn()
        try:
            stats = await conn.fetchrow("""
                SELECT
                    COUNT(*) AS total_approvals,
                    COUNT(*) FILTER (WHERE status = 'approved' OR status = 'approved_for_production') AS approved,
                    COUNT(*) FILTER (WHERE status = 'pending') AS pending,
                    COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
                    COUNT(*) FILTER (WHERE status = 'rework') AS rework
                FROM approvals
            """)
            return JSONResponse(
                _str_record(stats)
                if stats
                else {"total_approvals": 0, "approved": 0, "pending": 0, "rejected": 0, "rework": 0}
            )
        except Exception as exc:
            logger.warning("compliance_summary: %s", exc)
            return JSONResponse({"total_approvals": 0, "approved": 0, "pending": 0, "rejected": 0, "rework": 0})
        finally:
            await conn.close()

    # ── API: Demo Seed ────────────────────────────────────────────────────────

    @router.post("/api/demo/seed")
    async def demo_seed(request: Request):
        """Seed the database with Horvath Demo customer, project, and sample artifacts."""
        import json as _json  # noqa: PLC0415
        import uuid as _uuid  # noqa: PLC0415

        conn = await _get_conn()
        try:
            # Check if demo already exists and is complete
            existing = await conn.fetchrow("SELECT id FROM customers WHERE slug = 'horvath-demo'")
            if existing:
                customer_id = str(existing["id"])
                project_row = await conn.fetchrow(
                    "SELECT id FROM projects WHERE customer_id = $1 AND slug = 'sales-planning'",
                    existing["id"],
                )
                if project_row:
                    project_id = str(project_row["id"])
                    obj_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM technical_objects WHERE project_id = $1",
                        project_row["id"],
                    )
                    if obj_count and obj_count >= 3:
                        return JSONResponse(
                            {
                                "status": "already_exists",
                                "customer_id": customer_id,
                                "project_id": project_id,
                            }
                        )
                    # Partial seed — clean up and re-create
                    await conn.execute("DELETE FROM reconciliation_results WHERE project_id = $1", project_row["id"])
                    await conn.execute("DELETE FROM technical_objects WHERE project_id = $1", project_row["id"])
                    await conn.execute("DELETE FROM tech_specs WHERE project_id = $1", project_row["id"])
                    await conn.execute("DELETE FROM architecture_decisions WHERE project_id = $1", project_row["id"])
                    await conn.execute("DELETE FROM hla_documents WHERE project_id = $1", project_row["id"])
                    await conn.execute("DELETE FROM requirements WHERE project_id = $1", project_row["id"])
                    await conn.execute("DELETE FROM projects WHERE id = $1", project_row["id"])
                await conn.execute("DELETE FROM customers WHERE id = $1", existing["id"])

            # Get or create default tenant
            tenant = await conn.fetchrow("SELECT id FROM tenants LIMIT 1")
            if not tenant:
                tenant_id = str(_uuid.uuid4())
                await conn.execute(
                    "INSERT INTO tenants (id, name, slug) VALUES ($1::uuid, 'Default', 'default')",
                    tenant_id,
                )
            else:
                tenant_id = str(tenant["id"])

            # Create customer
            customer_id = str(_uuid.uuid4())
            await conn.execute(
                """INSERT INTO customers (id, tenant_id, name, slug, branding)
                   VALUES ($1::uuid, $2::uuid, 'Horvath Demo', 'horvath-demo',
                           '{"primary_color": "#05415A", "accent_color": "#C8963E"}'::jsonb)""",
                customer_id,
                tenant_id,
            )

            # Create project
            project_id = str(_uuid.uuid4())
            await conn.execute(
                """INSERT INTO projects (id, customer_id, name, slug, environment, status)
                   VALUES ($1::uuid, $2::uuid, 'Sales Planning', 'sales-planning', 'sandbox', 'active')""",
                project_id,
                customer_id,
            )

            # Create requirement
            req_id = str(_uuid.uuid4())
            await conn.execute(
                """INSERT INTO requirements (id, project_id, title, business_domain, description,
                                            parsed_entities, parsed_kpis, status)
                   VALUES ($1::uuid, $2::uuid, 'Revenue KPI Model', 'Finance',
                           'Revenue reporting with regional drill-down and product analysis',
                           '{"fact_tables": ["revenue_fact"], "dimensions": ["time", "product", "region"]}'::jsonb,
                           '[{"name": "Net Revenue", "formula": "gross - discounts"}, {"name": "Gross Margin", "formula": "(net_rev - cogs) / net_rev"}]'::jsonb,
                           'approved')""",
                req_id,
                project_id,
            )

            # Create HLA
            hla_id = str(_uuid.uuid4())
            await conn.execute(
                """INSERT INTO hla_documents (id, project_id, requirement_id, version, content, narrative, status)
                   VALUES ($1::uuid, $2::uuid, $3::uuid, 1,
                           '{"layers": ["raw", "harmonized", "mart"], "strategy": "star_schema"}'::jsonb,
                           'Three-layer architecture with star schema at mart level for SAC consumption.',
                           'approved')""",
                hla_id,
                project_id,
                req_id,
            )

            # Create architecture decisions
            for topic, choice, rationale, platform in [
                ("Aggregation Strategy", "Pre-aggregate at mart level", "Reduces SAC query time", "dsp"),
                ("Time Hierarchy", "DSP hierarchy view", "Reusable across multiple models", "dsp"),
                ("KPI Calculation", "DSP calculated columns", "Single source of truth", "dsp"),
            ]:
                await conn.execute(
                    """INSERT INTO architecture_decisions (id, project_id, requirement_id, topic, choice, rationale, platform_placement, status)
                       VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, $6, $7, 'approved')""",
                    str(_uuid.uuid4()),
                    project_id,
                    req_id,
                    topic,
                    choice,
                    rationale,
                    platform,
                )

            # Create tech spec
            spec_id = str(_uuid.uuid4())
            objects_json = _json.dumps(
                [
                    {"name": "V_RAW_REVENUE", "object_type": "relational_view", "layer": "raw"},
                    {"name": "V_HARM_REVENUE", "object_type": "relational_view", "layer": "harmonized"},
                    {"name": "V_MART_REVENUE", "object_type": "fact_view", "layer": "mart"},
                ]
            )
            deploy_order = _json.dumps(["V_RAW_REVENUE", "V_HARM_REVENUE", "V_MART_REVENUE"])
            await conn.execute(
                """INSERT INTO tech_specs (id, project_id, hla_id, version, objects, deployment_order, status)
                   VALUES ($1::uuid, $2::uuid, $3::uuid, 1, $4::jsonb, $5::jsonb, 'approved')""",
                spec_id,
                project_id,
                hla_id,
                objects_json,
                deploy_order,
            )

            # Create technical objects
            for name, obj_type, layer, sql in [
                (
                    "V_RAW_REVENUE",
                    "relational_view",
                    "raw",
                    "CREATE VIEW V_RAW_REVENUE AS\nSELECT\n  order_id,\n  product_id,\n  region_id,\n  order_date,\n  gross_amount,\n  discount_amount\nFROM SRC_SALES_ORDERS",
                ),
                (
                    "V_HARM_REVENUE",
                    "relational_view",
                    "harmonized",
                    "CREATE VIEW V_HARM_REVENUE AS\nSELECT\n  r.order_id,\n  r.product_id,\n  r.region_id,\n  r.order_date,\n  r.gross_amount,\n  r.discount_amount,\n  r.gross_amount - r.discount_amount AS net_revenue\nFROM V_RAW_REVENUE r",
                ),
                (
                    "V_MART_REVENUE",
                    "fact_view",
                    "mart",
                    "CREATE VIEW V_MART_REVENUE AS\nSELECT\n  region_id,\n  product_id,\n  DATE_TRUNC('month', order_date) AS month,\n  SUM(net_revenue) AS net_revenue,\n  SUM(gross_amount) AS gross_amount,\n  CASE WHEN SUM(net_revenue) > 0\n    THEN (SUM(net_revenue) - SUM(cogs)) / SUM(net_revenue)\n    ELSE 0 END AS gross_margin\nFROM V_HARM_REVENUE\nGROUP BY region_id, product_id, DATE_TRUNC('month', order_date)",
                ),
            ]:
                await conn.execute(
                    """INSERT INTO technical_objects (id, tech_spec_id, project_id, name, object_type, platform, layer, definition, generated_artifact, status)
                       VALUES ($1::uuid, $2::uuid, $3::uuid, $4, $5, 'dsp', $6, '{}'::jsonb, $7, 'deployed')""",
                    str(_uuid.uuid4()),
                    spec_id,
                    project_id,
                    name,
                    obj_type,
                    layer,
                    sql,
                )

            # Create reconciliation results
            for key, delta_status, baseline, candidate in [
                ("revenue_total_q1", "pass", {"total": 2450000}, {"total": 2450000}),
                ("margin_avg_q1", "within_tolerance", {"avg": 0.352}, {"avg": 0.349}),
                ("region_count", "pass", {"count": 12}, {"count": 12}),
            ]:
                await conn.execute(
                    """INSERT INTO reconciliation_results (id, project_id, test_case_key, baseline_value, candidate_value, delta_status)
                       VALUES ($1::uuid, $2::uuid, $3, $4::jsonb, $5::jsonb, $6)""",
                    str(_uuid.uuid4()),
                    project_id,
                    key,
                    _json.dumps(baseline),
                    _json.dumps(candidate),
                    delta_status,
                )

            return JSONResponse(
                {
                    "status": "seeded",
                    "customer_id": customer_id,
                    "project_id": project_id,
                    "objects_created": {
                        "customer": 1,
                        "project": 1,
                        "requirement": 1,
                        "hla": 1,
                        "decisions": 3,
                        "tech_spec": 1,
                        "technical_objects": 3,
                        "reconciliation": 3,
                    },
                }
            )
        except Exception as exc:
            logger.warning("demo_seed: %s", exc)
            return JSONResponse({"status": "error", "error": str(exc)}, status_code=500)
        finally:
            await conn.close()

    # ── API: Demo Run ─────────────────────────────────────────────────────────

    @router.post("/api/demo/run")
    async def demo_run(request: Request):
        """One-click demo: seed data + generate full report + assemble release package.

        Returns: {status, project_id, preview_url, download_urls}
        """
        import json as _json  # noqa: PLC0415

        # Step 1: Seed
        seed_resp = await demo_seed(request)
        seed_body = _json.loads(seed_resp.body)
        project_id = seed_body.get("project_id")
        if not project_id:
            return JSONResponse({"status": "error", "error": "Failed to seed demo data"}, status_code=500)

        # Step 2: Generate reports and assemble release
        try:
            conn = await _get_conn()
            try:
                data = await _fetch_project_data(conn, project_id)
            finally:
                await conn.close()

            from spec2sphere.governance.doc_generator import render_html_report, render_markdown_report  # noqa: PLC0415
            from spec2sphere.governance.release import assemble_release_package  # noqa: PLC0415

            html_report = render_html_report(data)
            md_report = render_markdown_report(data)

            # Save reports to filesystem for preview
            reports_dir = Path("output/reports")
            reports_dir.mkdir(parents=True, exist_ok=True)
            (reports_dir / "demo_report.html").write_text(html_report)
            (reports_dir / "demo_report.md").write_text(md_report)

            # Assemble release
            zip_bytes = assemble_release_package(data, version="demo-1.0")
            (reports_dir / "demo_release.zip").write_bytes(zip_bytes)

            return JSONResponse(
                {
                    "status": "complete",
                    "project_id": project_id,
                    "seed": seed_body.get("status"),
                    "reports_generated": ["demo_report.html", "demo_report.md"],
                    "release_package": "demo_release.zip",
                    "preview_url": "/reports/demo_report.html",
                    "download_urls": {
                        "html": "/reports/demo_report.html",
                        "markdown": "/reports/demo_report.md",
                        "release_zip": "/reports/demo_release.zip",
                    },
                }
            )
        except Exception as exc:
            logger.warning("demo_run: %s", exc)
            return JSONResponse({"status": "partial", "project_id": project_id, "error": str(exc)}, status_code=500)

    return router
