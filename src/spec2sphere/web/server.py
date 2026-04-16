"""FastAPI web server for SAP Doc Agent.

Serves documentation as HTML for M365 Copilot knowledge crawling,
and provides API endpoints for Copilot Actions.

Run: uvicorn spec2sphere.web.server:create_app --factory --port 8260
"""

from __future__ import annotations

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

try:
    from spec2sphere.tasks.scan_tasks import run_scan
except ImportError:
    run_scan = None

try:
    from spec2sphere.tasks.chain_tasks import build_chains as _build_chains_task
except ImportError:
    _build_chains_task = None

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


async def _register_with_oracle() -> None:
    """Best-effort Oracle registration."""
    import httpx

    try:
        manifest = {
            "service_name": "spec2sphere",
            "port": 8260,
            "description": "SAP Datasphere documentation agent — scanners, audit, knowledge engine",
            "endpoints": [
                {"method": "GET", "path": "/health", "purpose": "Health check"},
                {"method": "GET", "path": "/objects", "purpose": "List DSP objects"},
                {"method": "GET", "path": "/docs/{object_id}", "purpose": "Object documentation HTML"},
                {"method": "POST", "path": "/audit", "purpose": "Run audit on documents"},
                {"method": "POST", "path": "/scan/start", "purpose": "Start scanner"},
                {"method": "GET", "path": "/scan/status", "purpose": "Scanner status"},
                {"method": "GET", "path": "/ui/factory", "purpose": "Factory monitor"},
                {"method": "GET", "path": "/ui/reconciliation", "purpose": "Data reconciliation"},
                {"method": "GET", "path": "/ui/visual-qa", "purpose": "Visual QA"},
                {"method": "GET", "path": "/ui/lab/fitness", "purpose": "Route fitness dashboard"},
                {"method": "GET", "path": "/ui/browser-view", "purpose": "noVNC browser viewer"},
                {"method": "POST", "path": "/api/factory/deploy/dsp", "purpose": "Trigger DSP deployment"},
                {"method": "POST", "path": "/api/factory/deploy/sac", "purpose": "Trigger SAC deployment"},
                {"method": "GET", "path": "/ui/reports", "purpose": "Reports & documentation browser"},
                {"method": "GET", "path": "/ui/audit-log", "purpose": "Audit log viewer"},
                {"method": "GET", "path": "/ui/lab", "purpose": "Artifact Learning Lab"},
                {"method": "POST", "path": "/api/governance/generate-report", "purpose": "Generate as-built report"},
                {"method": "POST", "path": "/api/governance/release", "purpose": "Assemble release package"},
                {"method": "POST", "path": "/api/lab/templates/{id}/graduate", "purpose": "Graduate learned template"},
                {"method": "GET", "path": "/ui/agent-terminal", "purpose": "Agent terminal viewer (tmux sessions)"},
                {"method": "GET", "path": "/api/agent-terminal/sessions", "purpose": "List agent sessions"},
                {"method": "POST", "path": "/api/agent-terminal/sessions", "purpose": "Create agent session"},
                {"method": "GET", "path": "/copilot", "purpose": "Copilot knowledge hub (unauthenticated)"},
                {"method": "GET", "path": "/api/copilot/sections", "purpose": "List knowledge sections"},
                {"method": "GET", "path": "/api/copilot/search", "purpose": "Search knowledge content"},
                {"method": "GET", "path": "/mcp/sse", "purpose": "MCP SSE endpoint for Copilot integration"},
                {"method": "POST", "path": "/mcp/messages", "purpose": "MCP JSON-RPC message endpoint"},
            ],
            "nats_subjects": [],
            "source_paths": [
                {"repo": "sap-doc-agent", "paths": ["src/spec2sphere/"]},
            ],
        }
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post("http://192.168.0.50:8225/oracle/register", json=manifest)
    except Exception:
        pass


def create_app(
    output_dir: str = "output",
    horvath_standard_path: str = "standards/horvath/documentation_standard.yaml",
) -> FastAPI:
    """Create the FastAPI app."""
    output_path = Path(output_dir)
    standard_path = Path(horvath_standard_path)
    config_path = output_path.parent / "config.yaml"

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI):
        """Startup: ensure tables, bootstrap single-tenant, configure modules."""
        import asyncio

        asyncio.create_task(_register_with_oracle())

        # 1. Ensure scanner tables
        try:
            from spec2sphere.db import ensure_tables

            await ensure_tables()
        except Exception as e:
            logger.warning("Failed to ensure scanner tables: %s", e)

        # 2. Bootstrap default tenant/customer for single-tenant mode
        try:
            from spec2sphere.db import _get_conn
            from spec2sphere.tenant.context import _ensure_default_tenant

            conn = await _get_conn()
            try:
                await _ensure_default_tenant(conn)
            finally:
                await conn.close()
        except Exception as e:
            logger.warning("Could not bootstrap default tenant (DB may not be ready): %s", e)

        # 3. Seed Horváth design tokens (idempotent — skips existing rows)
        try:
            from spec2sphere.core.design_system.tokens import seed_horvath_defaults

            n = await seed_horvath_defaults()
            if n:
                logger.info("Seeded %d Horváth design tokens", n)
        except Exception as e:
            logger.warning("Failed to seed Horváth design tokens: %s", e)

        # 3b. Seed Horváth knowledge-base standards from standards/horvath/*.yaml
        try:
            import uuid as _uuid
            from pathlib import Path as _Path

            import asyncpg as _asyncpg
            import yaml as _yaml

            from spec2sphere.tenant.context import _DEFAULT_TENANT_ID

            _standards_dir = _Path(__file__).parents[3] / "standards" / "horvath"
            _yaml_files = list(_standards_dir.glob("*.yaml"))

            if _yaml_files and _DEFAULT_TENANT_ID:
                _db_url = (
                    __import__("os")
                    .environ.get("DATABASE_URL", "")
                    .replace("postgresql+psycopg://", "postgresql://")
                    .replace("postgresql+asyncpg://", "postgresql://")
                )
                _conn = await _asyncpg.connect(_db_url)
                try:
                    _kb_inserted = 0
                    for _yf in _yaml_files:
                        _title = _yf.stem.replace("_", " ").title() + " (Horváth Standard)"
                        _exists = await _conn.fetchrow(
                            "SELECT 1 FROM knowledge_items WHERE tenant_id IS NOT DISTINCT FROM $1 AND customer_id IS NULL AND title = $2",
                            _DEFAULT_TENANT_ID,
                            _title,
                        )
                        if _exists:
                            continue
                        with open(_yf) as _fh:
                            _raw = _yaml.safe_load(_fh) or {}
                        _content = _raw.get("description") or _raw.get("name") or ""
                        if not _content:
                            # Serialize the whole YAML as content so it's searchable
                            _content = _yf.read_text()
                        await _conn.execute(
                            """
                            INSERT INTO knowledge_items
                                (id, tenant_id, customer_id, project_id, category, title, content, source, confidence)
                            VALUES ($1, $2, NULL, NULL, 'standard', $3, $4, $5, 1.0)
                            """,
                            _uuid.uuid4(),
                            _DEFAULT_TENANT_ID,
                            _title,
                            _content,
                            _yf.name,
                        )
                        _kb_inserted += 1
                    if _kb_inserted:
                        logger.info("Seeded %d Horváth knowledge-base standards", _kb_inserted)
                finally:
                    await _conn.close()
        except Exception as e:
            logger.warning("Failed to seed Horváth knowledge-base standards: %s", e)

        # 4. Configure modules from config.yaml
        try:
            from spec2sphere.modules import configure_modules, mount_enabled_routes

            cfg_path = config_path
            if cfg_path.exists():
                import yaml

                with open(cfg_path) as f:
                    raw = yaml.safe_load(f) or {}
                modules_cfg = raw.get("modules", {})
            else:
                modules_cfg = {}
            configure_modules(modules_cfg)
            mount_enabled_routes(app_instance)
        except Exception as e:
            logger.warning("Failed to configure modules: %s", e)

        # 5. Mount workspace routes when multi_tenant enabled
        try:
            from spec2sphere.modules import is_enabled

            if is_enabled("multi_tenant"):
                from spec2sphere.tenant.routes import create_workspace_router

                app_instance.include_router(create_workspace_router())
                logger.info("Mounted workspace switcher routes (multi_tenant enabled)")
        except Exception as e:
            logger.warning("Failed to mount workspace routes: %s", e)

        yield

        # Shutdown browser pool if initialized
        try:
            from spec2sphere.browser.pool import _pool

            if _pool is not None:
                await _pool.shutdown()
        except Exception:
            pass

    app = FastAPI(
        title="Spec2Sphere API",
        description=(
            "Spec2Sphere — Horvath Analytics Delivery Factory. "
            "AI-governed SAP Datasphere + SAC delivery accelerator. "
            "Transforms business requirements and legacy SAP knowledge into "
            "validated, deployable SAP objects and SAC dashboards."
        ),
        version="2.0.0",
        lifespan=lifespan,
    )

    # Mount static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Mount UI router
    from spec2sphere.web.auth import AuthMiddleware, hash_password
    from spec2sphere.web.ui import create_ui_router

    ui_router = create_ui_router(output_path, config_path=config_path)
    app.include_router(ui_router)

    # Mount core routes (knowledge browser + landscape explorer)
    try:
        from spec2sphere.web.core_routes import create_core_routes

        app.include_router(create_core_routes())
    except ImportError as exc:
        logger.warning("Could not mount core routes: %s", exc)

    # Mount pipeline routes (requirements, HLA, approvals, notifications)
    try:
        from spec2sphere.web.pipeline_routes import create_pipeline_routes

        app.include_router(create_pipeline_routes())
    except ImportError as exc:
        logger.warning("Could not mount pipeline routes: %s", exc)

    # Mount factory routes (factory monitor, reconciliation, visual QA, route fitness)
    try:
        from spec2sphere.web.factory_routes import create_factory_routes

        app.include_router(create_factory_routes())
    except ImportError as exc:
        logger.warning("Could not mount factory routes: %s", exc)

    # Mount governance routes (reports, audit log, lab)
    try:
        from spec2sphere.web.governance_routes import create_governance_routes

        app.include_router(create_governance_routes())
    except ImportError as exc:
        logger.warning("Could not mount governance routes: %s", exc)

    # Mount terminal routes (agent session viewer)
    try:
        from spec2sphere.web.terminal_routes import create_terminal_routes

        app.include_router(create_terminal_routes())
    except ImportError as exc:
        logger.warning("Could not mount terminal routes: %s", exc)

    # Mount migration routers
    try:
        from spec2sphere.web.migration_routes import (
            create_migration_api_router,
            create_migration_ui_router,
        )

        app.include_router(create_migration_api_router(output_path))
        app.include_router(create_migration_ui_router(output_path))
    except ImportError:
        pass

    # Mount copilot routes (knowledge hub + MCP server)
    try:
        from spec2sphere.web.copilot_routes import create_copilot_routes

        app.include_router(create_copilot_routes())
    except ImportError as exc:
        logger.warning("Could not mount copilot routes: %s", exc)

    # Mount LLM routing API
    try:
        from spec2sphere.web.llm_routing import router as llm_routing_router

        app.include_router(llm_routing_router)
    except ImportError as exc:
        logger.warning("Could not mount LLM routing API: %s", exc)

    # Auth middleware (password from env, defaults to "admin" for dev)
    # In multi-tenant mode, user email+password login is also supported
    pw_hash = os.environ.get("SAP_DOC_AGENT_UI_PASSWORD_HASH", hash_password("admin"))
    secret = os.environ.get("SAP_DOC_AGENT_SECRET_KEY", "dev-secret-change-me")
    app.add_middleware(AuthMiddleware, password_hash=pw_hash, secret_key=secret)

    # Audit log middleware — fire-and-forget, never blocks responses
    try:
        from spec2sphere.tenant.audit import AuditMiddleware

        app.add_middleware(AuditMiddleware)
    except Exception as exc:
        logger.warning("Could not add audit middleware: %s", exc)

    # Browser pool health endpoint
    @app.get("/api/browser/health", tags=["browser"])
    async def browser_health():
        """Check Chrome CDP availability."""
        from spec2sphere.browser.pool import get_pool

        return await get_pool().health_check()

    # --- HTML documentation serving ---

    @app.get("/", include_in_schema=False)
    async def landing_page(request: Request):
        """Redirect browsers to UI dashboard; return JSON for programmatic access."""
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            from starlette.responses import RedirectResponse

            return RedirectResponse("/ui/dashboard")
        objects_count = 0
        try:
            from spec2sphere.db import get_object_count

            objects_count = await get_object_count()
        except Exception:
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
        objects_count = 0
        graph_loaded = False
        try:
            from spec2sphere.db import get_object_count

            objects_count = await get_object_count()
            graph_loaded = objects_count > 0
        except Exception:
            graph_loaded = (output_path / "graph.json").exists()
            objects_count = (
                sum(1 for _ in (output_path / "objects").rglob("*.md")) if (output_path / "objects").exists() else 0
            )
        return {"status": "ok", "objects": objects_count, "graph_loaded": graph_loaded}

    # --- API endpoints for M365 Copilot Actions ---

    @app.post(
        "/api/audit",
        summary="Run documentation audit",
        operation_id="runDocumentationAudit",
        description="Evaluate documentation against Horvath best-practice standard. Submit document titles and content, get back a quality score and list of issues.",
    )
    async def api_audit(request: AuditRequest):
        """Run a documentation audit against Horvath best-practice."""
        from spec2sphere.agents.doc_review import DocReviewAgent, load_documentation_standard

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
            from spec2sphere.config import AppConfig

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
            from spec2sphere.config import AppConfig

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
            # Chain: run_scan → build_chains (auto-trigger chain building)
            scan_kwargs = {"scanner_type": scanner_type, "config_path": config_path, "run_id": run_id}
            if _build_chains_task is not None:
                chain_kwargs = {"output_dir": str(output_path), "scan_id": run_id}
                task = run_scan.apply_async(
                    kwargs=scan_kwargs,
                    priority=body.get("priority", 9),
                    link=_build_chains_task.si(**chain_kwargs),
                )
            else:
                task = run_scan.apply_async(
                    kwargs=scan_kwargs,
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
        from spec2sphere.tasks.celery_app import celery_app as _celery_app

        result = AsyncResult(task_id, app=_celery_app)
        return _JSONResponse(
            {"task_id": task_id, "status": result.status, "result": result.result if result.ready() else None}
        )

    @app.get("/api/jobs")
    async def list_jobs():
        from fastapi.responses import JSONResponse as _JSONResponse

        return _JSONResponse({"jobs": [], "message": "job listing requires Redis connection"})

    # --- Chain endpoints ---

    @app.post("/api/chains/build", summary="Trigger chain building")
    async def trigger_build_chains():
        """Build chains from existing graph.json. Runs synchronously."""
        from fastapi.responses import JSONResponse as _JSONResponse
        from spec2sphere.scanner.chain_builder import build_chains_from_graph
        from spec2sphere.scanner.output import render_chain_markdown

        graph_path = output_path / "graph.json"
        if not graph_path.exists():
            return _JSONResponse({"error": "no graph.json found"}, status_code=404)
        graph = json.loads(graph_path.read_text())
        objects_dir = output_path / "objects"
        chains = build_chains_from_graph(graph, objects_dir=objects_dir if objects_dir.exists() else None)
        chains_dir = output_path / "chains"
        chains_dir.mkdir(exist_ok=True)
        for chain in chains:
            (chains_dir / f"{chain.chain_id}.json").write_text(chain.model_dump_json(indent=2))
            (chains_dir / f"{chain.chain_id}.md").write_text(render_chain_markdown(chain))
        return _JSONResponse(
            {"status": "completed", "chain_count": len(chains)},
        )

    @app.get("/api/chains", summary="List all data flow chains")
    async def list_chains():
        """List all discovered data flow chains from the latest scan."""
        from fastapi.responses import JSONResponse as _JSONResponse

        chains_dir = output_path / "chains"
        if not chains_dir.exists():
            return _JSONResponse([])
        chains = []
        for f in sorted(chains_dir.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                chains.append(
                    {
                        "chain_id": data.get("chain_id"),
                        "name": data.get("name", ""),
                        "step_count": len(data.get("steps", [])),
                        "terminal_object_id": data.get("terminal_object_id"),
                        "confidence": data.get("confidence", 0),
                    }
                )
            except (json.JSONDecodeError, OSError):
                continue
        return _JSONResponse(chains)

    @app.get("/api/chains/{chain_id}", summary="Get chain detail")
    async def get_chain(chain_id: str):
        """Get full detail for a specific data flow chain."""
        from fastapi.responses import JSONResponse as _JSONResponse

        chain_file = output_path / "chains" / f"{chain_id}.json"
        if not chain_file.exists():
            return _JSONResponse({"error": "chain not found"}, status_code=404)
        return _JSONResponse(json.loads(chain_file.read_text()))

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
        from spec2sphere.metrics import get_metrics_text

        content, content_type = get_metrics_text()
        return Response(content=content, media_type=content_type)

    # --- System status & management ---

    @app.get("/api/system/status", summary="System status", operation_id="getSystemStatus")
    async def system_status():
        """Check connectivity of all backing services."""
        from fastapi.responses import JSONResponse as _JSONResponse

        checks = {}
        overall = "ok"

        # Database
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

        # Redis
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

        # LLM
        provider_name = os.environ.get("LLM_PROVIDER", "none")
        if provider_name and provider_name != "none":
            try:
                from spec2sphere.config import LLMConfig
                from spec2sphere.llm import create_llm_provider

                cfg = LLMConfig(provider=provider_name)
                provider = create_llm_provider(cfg)
                if provider.is_available():
                    checks["llm"] = "ok"
                else:
                    checks["llm"] = "unavailable"
                    overall = "degraded"
            except Exception as e:
                checks["llm"] = f"error: {e}"
                overall = "degraded"
        else:
            checks["llm"] = "disabled"

        # Celery
        if redis_url:
            try:
                import redis as redis_lib

                r = redis_lib.from_url(redis_url)
                # Check if any celery workers have registered
                keys = r.keys("celery-task-meta-*")
                # Also check for worker heartbeat keys
                worker_keys = r.keys("_kombu.binding.*")
                checks["celery"] = "ok" if worker_keys else "no_workers"
                if not worker_keys:
                    overall = "degraded"
            except Exception as e:
                checks["celery"] = f"error: {e}"
                overall = "degraded"
        else:
            checks["celery"] = "unconfigured"

        return _JSONResponse(
            {
                "status": overall,
                "checks": checks,
                "provider": provider_name,
                "version": "1.1.0",
            }
        )

    @app.post("/api/system/test-llm", summary="Test LLM connection", operation_id="testLLM")
    async def test_llm_connection():
        """Send a simple test prompt to the configured LLM provider and measure latency."""
        from fastapi.responses import JSONResponse as _JSONResponse

        provider_name = os.environ.get("LLM_PROVIDER", "none")
        if not provider_name or provider_name == "none":
            return _JSONResponse({"success": False, "error": "No LLM provider configured"})

        try:
            import time

            from spec2sphere.config import LLMConfig
            from spec2sphere.llm import create_llm_provider

            cfg = LLMConfig(provider=provider_name)
            provider = create_llm_provider(cfg)

            start = time.monotonic()
            result = await provider.generate(
                "Respond with exactly: OK",
                system="You are a connectivity test. Respond with exactly the word OK.",
                tier="test_llm",
            )
            latency = round((time.monotonic() - start) * 1000)

            if result:
                return _JSONResponse(
                    {
                        "success": True,
                        "model": getattr(provider, "_model", provider_name),
                        "latency_ms": latency,
                        "response_preview": result[:100],
                    }
                )
            else:
                return _JSONResponse({"success": False, "error": "Provider returned empty response"})
        except Exception as e:
            return _JSONResponse({"success": False, "error": str(e)})

    @app.put("/api/settings/password", summary="Change UI password", operation_id="changePassword")
    async def change_password(request: Request):
        """Update the UI password. Generates a bcrypt hash and stores it."""
        from fastapi.responses import JSONResponse as _JSONResponse

        body = await request.json()
        new_password = body.get("password", "")
        if not new_password or len(new_password) < 6:
            return _JSONResponse({"error": "Password must be at least 6 characters"}, status_code=400)

        new_hash = hash_password(new_password)
        # Write to .env file if it exists, otherwise to a dedicated file
        env_file = output_path.parent / ".env"
        pw_line = f"SAP_DOC_AGENT_UI_PASSWORD_HASH={new_hash}"

        if env_file.exists():
            content = env_file.read_text()
            if "SAP_DOC_AGENT_UI_PASSWORD_HASH=" in content:
                lines = content.split("\n")
                lines = [pw_line if l.startswith("SAP_DOC_AGENT_UI_PASSWORD_HASH=") else l for l in lines]
                env_file.write_text("\n".join(lines))
            else:
                env_file.write_text(content.rstrip() + "\n" + pw_line + "\n")
        else:
            env_file.write_text(pw_line + "\n")

        # Also update the in-memory middleware
        os.environ["SAP_DOC_AGENT_UI_PASSWORD_HASH"] = new_hash
        # Update the middleware's hash
        for middleware in app.user_middleware:
            if hasattr(middleware, "cls") and middleware.cls.__name__ == "AuthMiddleware":
                break
        # The middleware instance is harder to reach; advise restart
        return _JSONResponse({"status": "updated", "message": "Password updated. Please log in again."})

    # --- Standards + Knowledge endpoints (Phase 4) ---

    @app.post("/api/standards/upload")
    async def upload_standard(request: Request):
        """Upload a customer documentation standard file."""
        from fastapi.responses import JSONResponse as _JSONResponse

        form = await request.form()
        file = form.get("file")
        if not file:
            return _JSONResponse({"error": "No file provided"}, status_code=400)
        file_data = await file.read()
        name = form.get("name", file.filename)
        content_type = file.content_type or "application/octet-stream"
        max_bytes = int(os.environ.get("UPLOAD_MAX_MB", "50")) * 1024 * 1024
        if len(file_data) > max_bytes:
            return _JSONResponse({"error": "File too large"}, status_code=413)
        try:
            from spec2sphere.standards import db as standards_db

            standard_id = await standards_db.create_standard(name, file.filename, content_type)
            await standards_db.store_standard_file(standard_id, file_data, file.filename, content_type)
            # Enqueue processing task
            try:
                from spec2sphere.tasks.agent_tasks import process_standard_upload

                task = process_standard_upload.apply_async(
                    kwargs={"standard_id": standard_id, "config_path": "config.yaml"}
                )
                task_id = task.id
            except (ImportError, Exception):
                task_id = None
            return _JSONResponse(
                {"standard_id": standard_id, "task_id": task_id, "status": "processing"}, status_code=202
            )
        except Exception as e:
            return _JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/standards")
    async def list_standards_endpoint():
        from fastapi.responses import JSONResponse as _JSONResponse

        try:
            from spec2sphere.standards import db as standards_db

            standards = await standards_db.list_standards()
            for s in standards:
                for k, v in s.items():
                    if hasattr(v, "isoformat"):
                        s[k] = v.isoformat()
                    elif hasattr(v, "hex"):
                        s[k] = str(v)
            return _JSONResponse({"standards": standards})
        except Exception as e:
            return _JSONResponse({"standards": [], "error": str(e)})

    @app.get("/api/standards/{standard_id}/download")
    async def download_standard(standard_id: str):
        from fastapi.responses import JSONResponse as _JSONResponse, Response as _FastAPIResponse

        try:
            from spec2sphere.standards import db as standards_db

            file_row = await standards_db.get_standard_file(standard_id)
            if not file_row:
                return _JSONResponse({"error": "File not found"}, status_code=404)
            return _FastAPIResponse(
                content=bytes(file_row["file_data"]),
                media_type=file_row["content_type"],
                headers={"Content-Disposition": f'attachment; filename="{file_row["filename"]}"'},
            )
        except Exception as e:
            return _JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/standards/{standard_id}")
    async def get_standard_endpoint(standard_id: str):
        from fastapi.responses import JSONResponse as _JSONResponse

        try:
            from spec2sphere.standards import db as standards_db

            std = await standards_db.get_standard(standard_id)
            if not std:
                return _JSONResponse({"error": "Not found"}, status_code=404)
            for k, v in std.items():
                if hasattr(v, "isoformat"):
                    std[k] = v.isoformat()
                elif hasattr(v, "hex"):
                    std[k] = str(v)
            return _JSONResponse(std)
        except Exception as e:
            return _JSONResponse({"error": str(e)}, status_code=500)

    @app.put("/api/standards/{standard_id}/rules")
    async def update_standard_rules_endpoint(standard_id: str, request: Request):
        from fastapi.responses import JSONResponse as _JSONResponse

        try:
            body = await request.json()
            from spec2sphere.standards import db as standards_db

            await standards_db.update_standard_rules(
                standard_id, body.get("parsed_rules", {}), body.get("raw_text", ""), "ready"
            )
            return _JSONResponse({"status": "updated"})
        except Exception as e:
            return _JSONResponse({"error": str(e)}, status_code=500)

    @app.delete("/api/standards/{standard_id}")
    async def delete_standard_endpoint(standard_id: str):
        from fastapi.responses import JSONResponse as _JSONResponse

        try:
            from spec2sphere.standards import db as standards_db

            await standards_db.delete_standard(standard_id)
            return _JSONResponse({"status": "deleted"})
        except Exception as e:
            return _JSONResponse({"error": str(e)}, status_code=500)

    @app.get("/api/knowledge")
    async def list_knowledge_endpoint(category: str = None):
        from fastapi.responses import JSONResponse as _JSONResponse

        try:
            from spec2sphere.standards import db as standards_db

            entries = await standards_db.list_knowledge(category)
            for e in entries:
                for k, v in e.items():
                    if hasattr(v, "isoformat"):
                        e[k] = v.isoformat()
                    elif hasattr(v, "hex"):
                        e[k] = str(v)
            return _JSONResponse({"knowledge": entries})
        except Exception as e:
            return _JSONResponse({"knowledge": [], "error": str(e)})

    @app.post("/api/knowledge")
    async def create_knowledge_endpoint(request: Request):
        from fastapi.responses import JSONResponse as _JSONResponse

        try:
            body = await request.json()
            from spec2sphere.standards import db as standards_db

            await standards_db.upsert_knowledge(body["category"], body["key"], body.get("value", {}), "manual")
            return _JSONResponse({"status": "created"}, status_code=201)
        except Exception as e:
            return _JSONResponse({"error": str(e)}, status_code=500)

    @app.put("/api/knowledge/{knowledge_id}")
    async def update_knowledge_endpoint(knowledge_id: str, request: Request):
        from fastapi.responses import JSONResponse as _JSONResponse

        try:
            body = await request.json()
            from spec2sphere.standards import db as standards_db

            await standards_db.upsert_knowledge(
                body["category"], body["key"], body.get("value", {}), body.get("source", "manual")
            )
            return _JSONResponse({"status": "updated"})
        except Exception as e:
            return _JSONResponse({"error": str(e)}, status_code=500)

    @app.delete("/api/knowledge/{knowledge_id}")
    async def delete_knowledge_endpoint(knowledge_id: str):
        from fastapi.responses import JSONResponse as _JSONResponse

        try:
            from spec2sphere.standards import db as standards_db

            await standards_db.delete_knowledge(knowledge_id)
            return _JSONResponse({"status": "deleted"})
        except Exception as e:
            return _JSONResponse({"error": str(e)}, status_code=500)

    @app.post("/api/knowledge/upload")
    async def upload_knowledge_endpoint(request: Request):
        from fastapi.responses import JSONResponse as _JSONResponse

        form = await request.form()
        file = form.get("file")
        if not file:
            return _JSONResponse({"error": "No file provided"}, status_code=400)
        file_data = await file.read()
        try:
            from spec2sphere.tasks.agent_tasks import process_knowledge_upload

            task = process_knowledge_upload.apply_async(
                kwargs={
                    "file_data_b64": __import__("base64").b64encode(file_data).decode(),
                    "filename": file.filename,
                }
            )
            return _JSONResponse({"task_id": task.id, "status": "processing"}, status_code=202)
        except Exception as e:
            return _JSONResponse({"error": str(e)}, status_code=500)

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
