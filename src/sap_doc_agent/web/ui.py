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
        # Gather stats
        graph_path = output_dir / "graph.json"
        objects = []
        edges = []
        if graph_path.exists():
            graph = json.loads(graph_path.read_text())
            objects = graph.get("nodes", [])
            edges = graph.get("edges", [])

        type_counts: dict[str, int] = {}
        for obj in objects:
            t = obj.get("type", "other")
            type_counts[t] = type_counts.get(t, 0) + 1

        return _render(
            request,
            "partials/dashboard.html",
            {
                "active_page": "dashboard",
                "object_count": len(objects),
                "type_counts": type_counts,
                "edge_count": len(edges),
            },
        )

    @router.get("/objects", response_class=HTMLResponse)
    async def objects_list(request: Request):
        graph_path = output_dir / "graph.json"
        objects = []
        if graph_path.exists():
            graph = json.loads(graph_path.read_text())
            objects = graph.get("nodes", [])

        q = request.query_params.get("q", "")
        obj_type = request.query_params.get("type", "")
        layer = request.query_params.get("layer", "")

        if q:
            objects = [
                o for o in objects if q.lower() in o.get("name", "").lower() or q.lower() in o.get("id", "").lower()
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
        # Find markdown file
        objects_dir = output_dir / "objects"
        content = ""
        metadata: dict = {}
        obj_type = ""
        if objects_dir.exists():
            for type_dir in objects_dir.iterdir():
                md_path = type_dir / f"{object_id}.md"
                if md_path.exists():
                    content = md_path.read_text()
                    obj_type = type_dir.name
                    if content.startswith("---"):
                        import yaml

                        parts = content.split("---", 2)
                        if len(parts) >= 3:
                            metadata = yaml.safe_load(parts[1]) or {}
                            content = parts[2]
                    break

        # Get dependencies
        graph_path = output_dir / "graph.json"
        upstream = []
        downstream = []
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
        graph_path = output_dir / "graph.json"
        graph_data = "{}"
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
        return _render(
            request,
            "partials/settings.html",
            {
                "active_page": "settings",
                "config_yaml": config_content,
            },
        )

    @router.get("/partials/health-dots", response_class=HTMLResponse)
    async def health_dots(request: Request):
        """Tiny partial for the topbar health indicators."""
        graph_exists = (output_dir / "graph.json").exists()
        objects_count = (
            sum(1 for _ in (output_dir / "objects").rglob("*.md")) if (output_dir / "objects").exists() else 0
        )
        dot_obj = "dot-green" if objects_count > 0 else "dot-amber"
        dot_graph = "dot-green" if graph_exists else "dot-red"
        return HTMLResponse(
            f'<div class="flex items-center gap-2 text-xs text-gray-500">'
            f'<span class="dot {dot_obj}"></span>'
            f"{objects_count} objects"
            f'<span class="dot {dot_graph}"></span>'
            f"graph"
            f"</div>"
        )

    return router
