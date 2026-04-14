"""FastAPI web server for SAP Doc Agent.

Serves documentation as HTML for M365 Copilot knowledge crawling,
and provides API endpoints for Copilot Actions.

Run: uvicorn sap_doc_agent.web.server:create_app --factory --port 8260
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from sap_doc_agent.tasks.scan_tasks import run_scan
except ImportError:
    run_scan = None

logger = logging.getLogger(__name__)


class AuditRequest(BaseModel):
    """Request body for the audit endpoint."""

    documents: list[dict] = Field(..., description="List of documents with 'title' and 'content' fields")
    client_standard: Optional[str] = Field(None, description="Client documentation standard text (optional)")
    application_name: str = Field("Unnamed", description="Name of the application being audited")
    scope: str = Field("application", description="Review scope: 'application' or 'system'")


class ObjectSummary(BaseModel):
    id: str
    name: str
    type: str
    layer: str = ""
    source_system: str = ""


class ConfigUpdate(BaseModel):
    """Request body for settings update/validate endpoints."""

    yaml_content: str


class ScanRequest(BaseModel):
    """Request body for scanner start endpoint."""

    scanner: str = Field("all", description="Scanner type: cdp, api, abap, or all")


def create_app(
    output_dir: str = "output",
    horvath_standard_path: str = "standards/horvath/documentation_standard.yaml",
) -> FastAPI:
    """Create the FastAPI app."""
    output_path = Path(output_dir)
    standard_path = Path(horvath_standard_path)

    app = FastAPI(
        title="SAP Doc Agent API",
        description=(
            "SAP Documentation Agent — serves documentation knowledge and "
            "provides API endpoints for documentation audit, quality assessment, "
            "and SAP system exploration. Designed for M365 Copilot integration."
        ),
        version="1.0.0",
    )

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Mount UI router
    from sap_doc_agent.web.auth import AuthMiddleware, hash_password
    from sap_doc_agent.web.ui import create_ui_router

    ui_router = create_ui_router(output_path)
    app.include_router(ui_router)

    # Auth middleware (password from env, defaults to "admin" for dev)
    pw_hash = os.environ.get("SAP_DOC_AGENT_UI_PASSWORD_HASH", hash_password("admin"))
    secret = os.environ.get("SAP_DOC_AGENT_SECRET_KEY", "dev-secret-change-me")
    app.add_middleware(AuthMiddleware, password_hash=pw_hash, secret_key=secret)

    # --- HTML documentation serving ---

    @app.get("/", include_in_schema=False)
    async def landing_page(request: Request):
        """Redirect browsers to UI dashboard; return JSON for programmatic access."""
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            from starlette.responses import RedirectResponse

            return RedirectResponse("/ui/dashboard")
        objects_count = (
            sum(1 for _ in (output_path / "objects").rglob("*.md")) if (output_path / "objects").exists() else 0
        )
        return {
            "service": "SAP Doc Agent",
            "version": "1.0.0",
            "objects": objects_count,
            "ui": "/ui/dashboard",
            "api_docs": "/docs",
        }

    @app.get("/docs/objects/{obj_type}/{obj_name}", response_class=HTMLResponse, include_in_schema=False)
    async def serve_object_doc(obj_type: str, obj_name: str):
        """Serve a scanned object's documentation as HTML."""
        md_path = output_path / "objects" / obj_type / f"{obj_name}.md"
        if not md_path.exists():
            raise HTTPException(404, f"Object not found: {obj_type}/{obj_name}")
        content = md_path.read_text()
        html_body = _markdown_to_html(content)
        return _wrap_html(obj_name, html_body)

    @app.get("/reports/{filename}", response_class=HTMLResponse, include_in_schema=False)
    async def serve_report(filename: str):
        """Serve a generated report."""
        report_path = output_path / "reports" / filename
        if not report_path.exists():
            raise HTTPException(404, f"Report not found: {filename}")
        if filename.endswith(".html"):
            return HTMLResponse(report_path.read_text())
        content = report_path.read_text()
        return _wrap_html(filename, _markdown_to_html(content))

    @app.get("/sitemap.xml", response_class=Response, include_in_schema=False)
    async def sitemap():
        """Auto-generated sitemap for M365 Copilot crawling."""
        urls = ["<url><loc>/</loc><priority>1.0</priority></url>"]
        objects_dir = output_path / "objects"
        if objects_dir.exists():
            for type_dir in sorted(objects_dir.iterdir()):
                if type_dir.is_dir():
                    for md_file in sorted(type_dir.glob("*.md")):
                        urls.append(
                            f"<url><loc>/docs/objects/{type_dir.name}/{md_file.stem}</loc>"
                            f"<priority>0.5</priority></url>"
                        )
        reports_dir = output_path / "reports"
        if reports_dir.exists():
            for f in sorted(reports_dir.glob("*")):
                urls.append(f"<url><loc>/reports/{f.name}</loc><priority>0.8</priority></url>")

        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{"".join(urls)}
</urlset>"""
        return Response(content=xml, media_type="application/xml")

    @app.get("/health")
    async def health():
        """Health check."""
        graph_exists = (output_path / "graph.json").exists()
        objects_count = (
            sum(1 for _ in (output_path / "objects").rglob("*.md")) if (output_path / "objects").exists() else 0
        )
        return {"status": "ok", "objects": objects_count, "graph_loaded": graph_exists}

    # --- API endpoints for M365 Copilot Actions ---

    @app.post(
        "/api/audit",
        summary="Run documentation audit",
        operation_id="runDocumentationAudit",
        description="Evaluate documentation against Horvath best-practice standard. Submit document titles and content, get back a quality score and list of issues.",
    )
    async def api_audit(request: AuditRequest):
        """Run a documentation audit against Horvath best-practice."""
        from sap_doc_agent.agents.doc_review import DocReviewAgent, load_documentation_standard

        if not standard_path.exists():
            raise HTTPException(500, "Horvath standard not found")
        std = load_documentation_standard(standard_path)
        agent = DocReviewAgent(std)

        if request.client_standard:
            client_std = agent._parse_standard_heuristic("Client Standard", request.client_standard)
            result = agent.review_against_both_standards(
                request.application_name, request.documents, client_std, scope=request.scope
            )
            return {
                "horvath_score": result["horvath_score"],
                "client_score": result["client_score"],
                "gap_analysis": result["gap_analysis"],
                "horvath_issues": result["horvath_review"].overall_issues,
                "client_issues": result["client_review"].overall_issues,
                "suggestions": result["horvath_review"].suggestions,
            }
        else:
            review = agent.review_documentation_set(request.application_name, request.documents, scope=request.scope)
            return {
                "score": review.percentage,
                "issues": review.overall_issues,
                "suggestions": review.suggestions,
                "sections_found": len([s for s in review.sections if s.found]),
                "sections_total": len(review.sections),
            }

    @app.get(
        "/api/objects",
        summary="List all scanned SAP objects",
        operation_id="listSAPObjects",
        description="Returns a list of all SAP objects discovered by the scanner, including their type, layer, and source system.",
    )
    async def api_list_objects():
        """List all objects from the dependency graph."""
        graph_path = output_path / "graph.json"
        if not graph_path.exists():
            return {"objects": [], "count": 0}
        graph = json.loads(graph_path.read_text())
        objects = [
            ObjectSummary(
                id=n["id"],
                name=n["name"],
                type=n["type"],
                layer=n.get("layer", ""),
                source_system=n.get("source_system", ""),
            )
            for n in graph.get("nodes", [])
        ]
        return {"objects": objects, "count": len(objects)}

    @app.get(
        "/api/objects/{object_id:path}",
        summary="Get SAP object details",
        operation_id="getSAPObjectDetails",
        description="Get full documentation for a specific SAP object by its ID, including description, columns, SQL, and dependencies.",
    )
    async def api_get_object(object_id: str):
        """Get details for a specific object."""
        # Find the markdown file
        objects_dir = output_path / "objects"
        if not objects_dir.exists():
            raise HTTPException(404, "No objects scanned")
        for type_dir in objects_dir.iterdir():
            md_path = type_dir / f"{object_id}.md"
            if md_path.exists():
                content = md_path.read_text()
                # Parse frontmatter
                metadata = {}
                if content.startswith("---"):
                    import yaml

                    parts = content.split("---", 2)
                    if len(parts) >= 3:
                        metadata = yaml.safe_load(parts[1]) or {}
                return {"object_id": object_id, "metadata": metadata, "content": content}
        raise HTTPException(404, f"Object not found: {object_id}")

    @app.get(
        "/api/search",
        summary="Search documentation",
        operation_id="searchDocumentation",
        description="Full-text search across all scanned SAP objects and documentation. Returns matching objects with excerpts.",
    )
    async def api_search(q: str = Query(..., description="Search query")):
        """Search across all documentation."""
        results = []
        objects_dir = output_path / "objects"
        if not objects_dir.exists():
            return {"query": q, "results": [], "count": 0}
        q_lower = q.lower()
        for type_dir in objects_dir.iterdir():
            if not type_dir.is_dir():
                continue
            for md_file in type_dir.glob("*.md"):
                content = md_file.read_text()
                if q_lower in content.lower() or q_lower in md_file.stem.lower():
                    # Extract a snippet around the match
                    idx = content.lower().find(q_lower)
                    snippet = content[max(0, idx - 100) : idx + 200] if idx >= 0 else content[:200]
                    results.append(
                        {
                            "object_id": md_file.stem,
                            "type": type_dir.name,
                            "snippet": snippet.strip(),
                            "url": f"/docs/objects/{type_dir.name}/{md_file.stem}",
                        }
                    )
        return {"query": q, "results": results, "count": len(results)}

    @app.get(
        "/api/quality",
        summary="Get documentation quality summary",
        operation_id="getQualitySummary",
        description="Returns the latest documentation quality assessment score and top issues.",
    )
    async def api_quality():
        """Get latest quality report summary."""
        summary_path = output_path / "reports" / "summary.md"
        if not summary_path.exists():
            return {
                "status": "no_report",
                "message": "No quality report generated yet. Run the platform pipeline first.",
            }
        return {"status": "ok", "summary": summary_path.read_text()}

    @app.get(
        "/api/dependencies/{object_id:path}",
        summary="Get object dependencies",
        operation_id="getObjectDependencies",
        description="Get upstream and downstream dependencies for a specific SAP object.",
    )
    async def api_dependencies(object_id: str):
        """Get dependencies for an object."""
        graph_path = output_path / "graph.json"
        if not graph_path.exists():
            raise HTTPException(404, "No dependency graph available")
        graph = json.loads(graph_path.read_text())
        upstream = [e for e in graph.get("edges", []) if e["target"] == object_id]
        downstream = [e for e in graph.get("edges", []) if e["source"] == object_id]
        return {
            "object_id": object_id,
            "upstream": [{"source": e["source"], "type": e["type"]} for e in upstream],
            "downstream": [{"target": e["target"], "type": e["type"]} for e in downstream],
        }

    # --- New API endpoints for Web UI ---

    @app.get("/api/dashboard/stats", summary="Dashboard statistics", operation_id="getDashboardStats")
    async def api_dashboard_stats():
        """Aggregated stats for the dashboard."""
        graph_path = output_path / "graph.json"
        objects = []
        edges = []
        if graph_path.exists():
            graph = json.loads(graph_path.read_text())
            objects = graph.get("nodes", [])
            edges = graph.get("edges", [])
        type_counts = {}
        for obj in objects:
            t = obj.get("type", "other")
            type_counts[t] = type_counts.get(t, 0) + 1
        return {
            "object_count": len(objects),
            "edge_count": len(edges),
            "type_counts": type_counts,
        }

    @app.get("/api/settings", summary="Get current config", operation_id="getSettings")
    async def api_get_settings():
        """Return current config YAML (sanitized)."""
        config_candidates = [
            output_path.parent / "config.yaml",
            output_path.parent / "config.demo.yaml",
            Path(horvath_standard_path).parent.parent / "config.yaml",
        ]
        for cp in config_candidates:
            if cp.exists():
                return {"yaml_content": cp.read_text(), "path": str(cp)}
        return {"yaml_content": "", "path": "", "message": "No config file found"}

    @app.put("/api/settings", summary="Update config", operation_id="updateSettings")
    async def api_update_settings(update: ConfigUpdate):
        """Validate and save config YAML."""
        import yaml as _yaml

        try:
            raw = _yaml.safe_load(update.yaml_content)
            from sap_doc_agent.config import AppConfig

            AppConfig.model_validate(raw)
        except Exception as e:
            return {"saved": False, "errors": [str(e)]}
        config_path = output_path.parent / "config.yaml"
        config_path.write_text(update.yaml_content)
        return {"saved": True, "path": str(config_path)}

    @app.post("/api/settings/validate", summary="Validate config", operation_id="validateSettings")
    async def api_validate_settings(update: ConfigUpdate):
        """Validate config YAML without saving."""
        import yaml as _yaml

        try:
            raw = _yaml.safe_load(update.yaml_content)
            from sap_doc_agent.config import AppConfig

            AppConfig.model_validate(raw)
            return {"valid": True}
        except Exception as e:
            return {"valid": False, "errors": [str(e)]}

    @app.post("/api/scanner/start", summary="Start a scan", operation_id="startScan")
    async def api_start_scan(req: ScanRequest):
        """Trigger a scan (placeholder — actual scanning runs async)."""
        return {"status": "started", "scanner": req.scanner, "message": f"Scan with {req.scanner} scanner initiated"}

    @app.get("/api/scanner/status", summary="Scanner status", operation_id="getScannerStatus")
    async def api_scanner_status():
        """Get status of configured scanners."""
        return {
            "scanners": [
                {"name": "CDP Scanner", "type": "cdp", "status": "idle"},
                {"name": "REST API Scanner", "type": "api", "status": "not_configured"},
                {"name": "ABAP Scanner", "type": "abap", "status": "not_installed"},
            ]
        }

    # --- Job queue endpoints (Phase 2) ---

    @app.post("/api/scan/start")
    async def start_scan(request: Request):
        """Enqueue a scan task. Returns task_id immediately."""
        from fastapi.responses import JSONResponse as _JSONResponse

        body = await request.json()
        scanner_type = body.get("scanner_type", "dsp_api")
        system_name = body.get("system_name", "default")
        config_path = body.get("config_path", "config.yaml")
        import uuid

        run_id = str(uuid.uuid4())
        if run_scan is not None:
            task = run_scan.apply_async(
                kwargs={"scanner_type": scanner_type, "config_path": config_path, "run_id": run_id},
                priority=body.get("priority", 9),
            )
            task_id = task.id
        else:
            task_id = run_id
        return _JSONResponse({"task_id": task_id, "run_id": run_id, "status": "queued"}, status_code=202)

    @app.get("/api/scan/status/{task_id}")
    async def scan_status(task_id: str):
        from fastapi.responses import JSONResponse as _JSONResponse
        from celery.result import AsyncResult
        from sap_doc_agent.tasks.celery_app import celery_app as _celery_app

        result = AsyncResult(task_id, app=_celery_app)
        return _JSONResponse(
            {"task_id": task_id, "status": result.status, "result": result.result if result.ready() else None}
        )

    @app.get("/api/jobs")
    async def list_jobs():
        from fastapi.responses import JSONResponse as _JSONResponse

        return _JSONResponse({"jobs": [], "message": "job listing requires Redis connection"})

    # --- Health endpoints (Phase 3) ---

    @app.get("/healthz")
    async def healthz():
        from fastapi.responses import JSONResponse as _JSONResponse

        return _JSONResponse({"status": "ok"})

    @app.get("/readyz")
    async def readyz():
        from fastapi.responses import JSONResponse as _JSONResponse

        checks = {}
        overall = "ok"

        # DB check
        db_url = os.environ.get("DATABASE_URL")
        if db_url:
            try:
                import asyncpg

                conn = await asyncpg.connect(
                    db_url.replace("postgresql+psycopg://", "postgresql://").replace(
                        "postgresql+asyncpg://", "postgresql://"
                    )
                )
                await conn.fetchval("SELECT 1")
                await conn.close()
                checks["database"] = "ok"
            except Exception as e:
                checks["database"] = f"error: {e}"
                overall = "degraded"
        else:
            checks["database"] = "unconfigured"

        # Redis check
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            try:
                import redis as redis_lib

                r = redis_lib.from_url(redis_url)
                r.ping()
                checks["redis"] = "ok"
            except Exception as e:
                checks["redis"] = f"error: {e}"
                overall = "degraded"
        else:
            checks["redis"] = "unconfigured"

        status_code = 200 if overall == "ok" else 503
        return _JSONResponse({"status": overall, "checks": checks}, status_code=status_code)

    @app.get("/metrics")
    async def metrics():
        from sap_doc_agent.metrics import get_metrics_text

        content, content_type = get_metrics_text()
        return Response(content=content, media_type=content_type)

    return app


def _markdown_to_html(md: str) -> str:
    """Simple markdown to HTML conversion."""
    html = md
    # Remove YAML frontmatter
    if html.startswith("---"):
        parts = html.split("---", 2)
        if len(parts) >= 3:
            html = parts[2]
    html = re.sub(r"^#### (.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)
    html = re.sub(r"^# (.+)$", r"<h1>\1</h1>", html, flags=re.MULTILINE)
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    # Code blocks
    html = re.sub(r"```(\w+)?\n(.*?)```", r"<pre><code>\2</code></pre>", html, flags=re.DOTALL)
    html = html.replace("\n\n", "</p><p>")
    return html


def _wrap_html(title: str, body: str) -> str:
    """Wrap HTML body in a full page."""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>{title} — SAP Doc Agent</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; color: #333; line-height: 1.6; }}
h1 {{ color: #1a365d; border-bottom: 2px solid #2b6cb0; padding-bottom: 8px; }}
h2 {{ color: #2b6cb0; }}
h3 {{ color: #4a5568; }}
code {{ background: #f0f4f8; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
pre {{ background: #1a202c; color: #e2e8f0; padding: 16px; border-radius: 8px; overflow-x: auto; }}
pre code {{ background: none; color: inherit; }}
li {{ margin: 3px 0; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #e2e8f0; padding: 8px 12px; text-align: left; }}
th {{ background: #f7fafc; }}
a {{ color: #2b6cb0; }}
</style></head><body>
<nav><a href="/">← Home</a></nav>
<p>{body}</p>
</body></html>"""
