"""UI routes for the SAP Doc Agent web interface."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _render(request: Request, template: str, ctx: dict) -> HTMLResponse:
    """Render a Jinja2 template using the current Starlette TemplateResponse API."""
    ctx["request"] = request
    return templates.TemplateResponse(request, template, ctx)


def create_ui_router(output_dir: Path, config_path: Path | None = None) -> APIRouter:
    """Create the UI router with all page routes."""
    router = APIRouter(prefix="/ui")

    @router.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request):
        import os

        # Gather stats — try DB first, fall back to files
        objects = []
        edges = []
        try:
            from spec2sphere.db import get_graph_data

            graph = await get_graph_data()
            objects = graph.get("nodes", [])
            edges = graph.get("edges", [])
        except Exception:
            graph_path = output_dir / "graph.json"
            if graph_path.exists():
                graph = json.loads(graph_path.read_text())
                objects = graph.get("nodes", [])
                edges = graph.get("edges", [])

        type_counts: dict[str, int] = {}
        for obj in objects:
            t = obj.get("type", "other")
            type_counts[t] = type_counts.get(t, 0) + 1

        # Check if any scans have been run
        has_scans = len(objects) > 0 or (output_dir / "graph.json").exists()

        # LLM status for getting started
        llm_provider = os.environ.get("LLM_PROVIDER", "none")
        llm_configured = llm_provider and llm_provider != "none"

        return _render(
            request,
            "partials/dashboard.html",
            {
                "active_page": "dashboard",
                "object_count": len(objects),
                "type_counts": type_counts,
                "edge_count": len(edges),
                "has_scans": has_scans,
                "llm_configured": llm_configured,
                "llm_provider": llm_provider,
            },
        )

    @router.get("/objects", response_class=HTMLResponse)
    async def objects_list(request: Request):
        q = request.query_params.get("q", "")
        obj_type = request.query_params.get("type", "")
        layer = request.query_params.get("layer", "")

        objects = []
        try:
            from spec2sphere.db import list_objects as db_list_objects

            objects = await db_list_objects(
                object_type=obj_type or None,
                layer=layer or None,
                q=q or None,
            )
            # Normalize field names to match template expectations (id/type vs object_id/object_type)
            for o in objects:
                if "id" not in o:
                    o["id"] = o.get("object_id", "")
                if "type" not in o:
                    o["type"] = o.get("object_type", "")
        except Exception:
            graph_path = output_dir / "graph.json"
            if graph_path.exists():
                graph = json.loads(graph_path.read_text())
                objects = graph.get("nodes", [])
                if q:
                    objects = [
                        o
                        for o in objects
                        if q.lower() in o.get("name", "").lower() or q.lower() in o.get("id", "").lower()
                    ]
                if obj_type:
                    objects = [o for o in objects if o.get("type") == obj_type]
                if layer:
                    objects = [o for o in objects if o.get("layer") == layer]

        all_types = sorted(set(o.get("type", "") for o in objects))
        all_layers = sorted(set(o.get("layer", "") for o in objects if o.get("layer")))

        return _render(
            request,
            "partials/objects.html",
            {
                "active_page": "objects",
                "objects": objects,
                "all_types": all_types,
                "all_layers": all_layers,
                "q": q,
                "selected_type": obj_type,
                "selected_layer": layer,
            },
        )

    @router.get("/objects/{object_id:path}", response_class=HTMLResponse)
    async def object_detail(request: Request, object_id: str):
        content = ""
        metadata: dict = {}
        obj_type = ""
        upstream = []
        downstream = []

        db_obj = None
        try:
            from spec2sphere.db import get_object as db_get_object, get_graph_data

            db_obj = await db_get_object(object_id)
            if db_obj:
                obj_type = db_obj.get("object_type", "")
                metadata = {
                    "object_id": db_obj.get("object_id", ""),
                    "object_type": obj_type,
                    "name": db_obj.get("name", ""),
                    "source_system": db_obj.get("source_system", ""),
                    "package": db_obj.get("package", ""),
                    "owner": db_obj.get("owner", ""),
                    "layer": db_obj.get("layer", ""),
                    "technical_name": db_obj.get("technical_name", ""),
                    "scanned_at": db_obj.get("scanned_at", ""),
                    **(db_obj.get("metadata") or {}),
                }
                content = db_obj.get("source_code", "")

            graph = await get_graph_data()
            upstream = [e for e in graph.get("edges", []) if e["target"] == object_id]
            downstream = [e for e in graph.get("edges", []) if e["source"] == object_id]
        except Exception:
            pass

        # File fallback if DB didn't give us an object
        if db_obj is None:
            objects_dir = output_dir / "objects"
            if objects_dir.exists():
                for type_dir in objects_dir.iterdir():
                    md_path = type_dir / f"{object_id}.md"
                    if md_path.exists():
                        raw = md_path.read_text()
                        obj_type = type_dir.name
                        if raw.startswith("---"):
                            import yaml

                            parts = raw.split("---", 2)
                            if len(parts) >= 3:
                                metadata = yaml.safe_load(parts[1]) or {}
                                content = parts[2]
                        else:
                            content = raw
                        break

            graph_path = output_dir / "graph.json"
            if graph_path.exists():
                graph = json.loads(graph_path.read_text())
                upstream = [e for e in graph.get("edges", []) if e["target"] == object_id]
                downstream = [e for e in graph.get("edges", []) if e["source"] == object_id]

        return _render(
            request,
            "partials/object_detail.html",
            {
                "active_page": "objects",
                "object_id": object_id,
                "metadata": metadata,
                "content": content,
                "obj_type": obj_type,
                "upstream": upstream,
                "downstream": downstream,
            },
        )

    @router.get("/chains", response_class=HTMLResponse)
    async def chains_list(request: Request):
        """List all data flow chains."""
        chains_dir = output_dir / "chains"
        chains = []
        if chains_dir.exists():
            for f in sorted(chains_dir.glob("*.json")):
                try:
                    data = json.loads(f.read_text())
                    chains.append(data)
                except (json.JSONDecodeError, OSError):
                    continue
        return _render(
            request,
            "partials/chains.html",
            {
                "active_page": "chains",
                "chains": chains,
            },
        )

    @router.get("/chains/{chain_id}", response_class=HTMLResponse)
    async def chain_detail(request: Request, chain_id: str):
        """View a single chain in detail."""
        chain_file = output_dir / "chains" / f"{chain_id}.json"
        if not chain_file.exists():
            from fastapi.responses import RedirectResponse

            return RedirectResponse("/ui/chains")
        chain = json.loads(chain_file.read_text())
        return _render(
            request,
            "partials/chain_detail.html",
            {
                "active_page": "chains",
                "chain": chain,
            },
        )

    @router.get("/quality", response_class=HTMLResponse)
    async def quality(request: Request):
        reports_dir = output_dir / "reports"
        summary = ""
        if (reports_dir / "summary.md").exists():
            summary = (reports_dir / "summary.md").read_text()
        return _render(
            request,
            "partials/quality.html",
            {
                "active_page": "quality",
                "summary": summary,
            },
        )

    @router.get("/graph", response_class=HTMLResponse)
    async def graph_page(request: Request):
        graph_data = "{}"
        try:
            from spec2sphere.db import get_graph_data

            graph = await get_graph_data()
            graph_data = json.dumps(graph)
        except Exception:
            graph_path = output_dir / "graph.json"
            if graph_path.exists():
                graph_data = graph_path.read_text()
        return _render(
            request,
            "partials/graph.html",
            {
                "active_page": "graph",
                "graph_data": graph_data,
            },
        )

    @router.get("/reports", response_class=HTMLResponse)
    async def reports(request: Request):
        reports_dir = output_dir / "reports"
        report_files = []
        if reports_dir.exists():
            for f in sorted(reports_dir.iterdir()):
                if f.is_file():
                    report_files.append(
                        {
                            "name": f.name,
                            "size": f.stat().st_size,
                            "url": f"/reports/{f.name}",
                        }
                    )
        return _render(
            request,
            "partials/reports.html",
            {
                "active_page": "reports",
                "reports": report_files,
            },
        )

    @router.get("/audit", response_class=HTMLResponse)
    async def audit(request: Request):
        return _render(request, "partials/audit.html", {"active_page": "audit"})

    @router.get("/scanner", response_class=HTMLResponse)
    async def scanner(request: Request):
        return _render(request, "partials/scanner.html", {"active_page": "scanner"})

    @router.get("/settings", response_class=HTMLResponse)
    async def settings(request: Request):
        config_content = ""
        if config_path and config_path.exists():
            config_content = config_path.read_text()

        # Gather LLM provider info from environment
        import os

        active_provider = os.environ.get("LLM_PROVIDER", "none")
        env_vars = {
            "AZURE_OPENAI_ENDPOINT": os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            "AZURE_OPENAI_API_KEY": os.environ.get("AZURE_OPENAI_API_KEY", ""),
            "AZURE_OPENAI_DEPLOYMENT": os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
            "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
            "OPENAI_MODEL": os.environ.get("OPENAI_MODEL", "gpt-4o"),
            "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", ""),
            "ANTHROPIC_MODEL": os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
            "GEMINI_MODEL": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
            "OLLAMA_BASE_URL": os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            "OLLAMA_MODEL": os.environ.get("OLLAMA_MODEL", ""),
            "VLLM_BASE_URL": os.environ.get("VLLM_BASE_URL", ""),
            "VLLM_MODEL": os.environ.get("VLLM_MODEL", ""),
            "VLLM_API_KEY": os.environ.get("VLLM_API_KEY", ""),
            "LLM_ROUTER_URL": os.environ.get("LLM_ROUTER_URL", ""),
            "LLM_ROUTER_API_KEY": os.environ.get("LLM_ROUTER_API_KEY", ""),
            "LLM_ROUTER_MODEL": os.environ.get("LLM_ROUTER_MODEL", "default"),
            "LLM_TOKEN_BUDGET_PER_HOUR": os.environ.get("LLM_TOKEN_BUDGET_PER_HOUR", ""),
            "LLM_MAX_CONCURRENT": os.environ.get("LLM_MAX_CONCURRENT", "4"),
            "SAP_RATE_LIMIT_RPS": os.environ.get("SAP_RATE_LIMIT_RPS", "10"),
            "DATABASE_URL": os.environ.get("DATABASE_URL", ""),
            "REDIS_URL": os.environ.get("REDIS_URL", ""),
        }

        # Determine LLM status
        llm_status = "not_configured"
        llm_status_label = "Not Configured"
        llm_model = ""
        if active_provider and active_provider != "none":
            llm_status = "configured"
            llm_status_label = f"{active_provider.capitalize()} configured"
            model_keys = {
                "azure": "AZURE_OPENAI_DEPLOYMENT",
                "openai": "OPENAI_MODEL",
                "anthropic": "ANTHROPIC_MODEL",
                "gemini": "GEMINI_MODEL",
                "ollama": "OLLAMA_MODEL",
                "vllm": "VLLM_MODEL",
                "router": "LLM_ROUTER_MODEL",
            }
            llm_model = env_vars.get(model_keys.get(active_provider, ""), "")

        return _render(
            request,
            "partials/settings.html",
            {
                "active_page": "settings",
                "config_yaml": config_content,
                "active_provider": active_provider,
                "env_vars": env_vars,
                "llm_status": llm_status,
                "llm_status_label": llm_status_label,
                "llm_model": llm_model,
            },
        )

    @router.get("/admin", response_class=HTMLResponse)
    async def admin_page(request: Request):
        return _render(request, "partials/admin.html", {"active_page": "admin"})

    @router.get("/partials/health-dots", response_class=HTMLResponse)
    async def health_dots(request: Request):
        """Tiny partial for the topbar health indicators."""
        import os

        objects_count = 0
        try:
            from spec2sphere.db import get_object_count

            objects_count = await get_object_count()
        except Exception:
            objects_count = (
                sum(1 for _ in (output_dir / "objects").rglob("*.md")) if (output_dir / "objects").exists() else 0
            )

        # DB check
        db_ok = False
        try:
            import asyncpg

            db_url = os.environ.get("DATABASE_URL", "")
            if db_url:
                conn = await asyncpg.connect(
                    db_url.replace("postgresql+psycopg://", "postgresql://").replace(
                        "postgresql+asyncpg://", "postgresql://"
                    )
                )
                await conn.fetchval("SELECT 1")
                await conn.close()
                db_ok = True
        except Exception:
            pass

        # LLM check
        llm_provider = os.environ.get("LLM_PROVIDER", "none")
        llm_configured = llm_provider and llm_provider != "none"

        dot_db = "dot-green" if db_ok else "dot-red"
        dot_obj = "dot-green" if objects_count > 0 else "dot-amber"
        dot_llm = "dot-green" if llm_configured else "dot-amber"

        return HTMLResponse(
            f'<div class="flex items-center gap-3 text-xs text-gray-500">'
            f'<span class="flex items-center gap-1"><span class="dot {dot_db}"></span>DB</span>'
            f'<span class="flex items-center gap-1"><span class="dot {dot_obj}"></span>{objects_count} obj</span>'
            f'<span class="flex items-center gap-1"><span class="dot {dot_llm}"></span>LLM</span>'
            f"</div>"
        )

    @router.get("/partials/system-status", response_class=HTMLResponse)
    async def system_status_partial(request: Request):
        """Inline system status for dashboard card."""
        import os

        items = []

        # DB
        db_ok = False
        try:
            import asyncpg

            db_url = os.environ.get("DATABASE_URL", "")
            if db_url:
                conn = await asyncpg.connect(
                    db_url.replace("postgresql+psycopg://", "postgresql://").replace(
                        "postgresql+asyncpg://", "postgresql://"
                    )
                )
                await conn.fetchval("SELECT 1")
                await conn.close()
                db_ok = True
        except Exception:
            pass
        items.append(("PostgreSQL", db_ok, "Database"))

        # Redis
        redis_ok = False
        try:
            import redis as redis_lib

            redis_url = os.environ.get("REDIS_URL", "")
            if redis_url:
                r = redis_lib.from_url(redis_url)
                r.ping()
                redis_ok = True
        except Exception:
            pass
        items.append(("Redis", redis_ok, "Queue & cache"))

        # LLM
        llm_provider = os.environ.get("LLM_PROVIDER", "none")
        llm_active = llm_provider and llm_provider != "none"
        items.append(("LLM", llm_active, f"{llm_provider}" if llm_active else "Disabled"))

        html_parts = []
        for name, ok, detail in items:
            dot = "dot-green" if ok else ("dot-amber" if name == "LLM" and not llm_active else "dot-red")
            if name == "LLM" and not llm_active:
                dot = "dot-amber"
            html_parts.append(
                f'<div class="flex items-center justify-between py-1.5">'
                f'<span class="flex items-center gap-2 text-sm"><span class="dot {dot}"></span>{name}</span>'
                f'<span class="text-xs text-gray-400">{detail}</span></div>'
            )

        return HTMLResponse("".join(html_parts))

    return router
