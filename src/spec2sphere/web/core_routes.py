"""Core UI and API routes for Knowledge Browser and Landscape Explorer.

Mounted at the app level (no prefix) alongside the existing UI router.
UI routes live under /ui/knowledge and /ui/landscape.
API routes live under /api/landscape.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _render(request: Request, template: str, ctx: dict) -> HTMLResponse:
    """Render a Jinja2 template."""
    ctx["request"] = request
    return templates.TemplateResponse(request, template, ctx)


def _get_llm():
    """Best-effort LLM provider creation. Returns None if unavailable."""
    try:
        import os

        from spec2sphere.config import LLMConfig
        from spec2sphere.llm import create_llm_provider

        provider = os.environ.get("LLM_PROVIDER", "none")
        if provider and provider != "none":
            return create_llm_provider(LLMConfig(provider=provider))
    except Exception:
        pass
    return None


async def _get_ctx():
    """Return the default single-tenant ContextEnvelope."""
    from spec2sphere.tenant.context import get_default_context

    return await get_default_context()



def _escape(s: str) -> str:
    """HTML-escape a string for safe inline embedding in generated fragments."""
    import html as _h
    return _h.escape(s)


def _category_options(selected: str) -> str:
    """Return <option> tags for the knowledge category selector."""
    cats = [
        "naming", "layering", "anti_pattern", "template", "quality",
        "governance", "standard", "pattern", "glossary", "document",
    ]
    return "".join(
        f'<option value="{c}" {"selected" if c == selected else ""}>' +
        f'{c.replace("_", " ").title()}</option>'
        for c in cats
    )

def create_core_routes() -> APIRouter:
    """Return an APIRouter with knowledge + landscape UI and API routes."""
    router = APIRouter()

    # ──────────────────────────────────────────────────────────────────────────
    # Knowledge UI routes
    # ──────────────────────────────────────────────────────────────────────────

    @router.get("/ui/knowledge", response_class=HTMLResponse)
    async def knowledge_browser(request: Request):
        """Knowledge Browser page with semantic search and document upload."""
        q: str = request.query_params.get("q", "")
        category: str = request.query_params.get("category", "")
        layer: str = request.query_params.get("layer", "")

        items: list[dict] = []
        categories: list[str] = []
        stats: Optional[dict] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.core.knowledge.knowledge_service import (
                list_knowledge_items,
                search_knowledge,
            )

            if q:
                items = await search_knowledge(
                    query=q,
                    ctx=ctx,
                    top_k=30,
                    llm=_get_llm(),
                )
                # Post-filter by category/layer if set (search returns cross-layer)
                if category:
                    items = [i for i in items if i.get("category") == category]
                if layer:
                    items = [i for i in items if i.get("source_layer") == layer]
            else:
                items = await list_knowledge_items(
                    ctx=ctx,
                    category=category or None,
                    layer=layer or None,
                    limit=50,
                )
                # Normalise: list_knowledge_items doesn't set source_layer
                for item in items:
                    if "source_layer" not in item:
                        if item.get("project_id"):
                            item["source_layer"] = "project"
                        elif item.get("customer_id"):
                            item["source_layer"] = "customer"
                        else:
                            item["source_layer"] = "global"

            # Derive distinct categories from results
            categories = sorted(set(i.get("category", "") for i in items if i.get("category")))

            # Build simple layer stats
            stats = {"global": 0, "customer": 0, "project": 0, "total": len(items)}
            for item in items:
                lyr = item.get("source_layer", "global")
                if lyr in stats:
                    stats[lyr] += 1

        except Exception as exc:
            logger.warning("Knowledge browser load error: %s", exc)

        # Stringify UUIDs so Jinja2 can render them
        for item in items:
            for key in ("id", "tenant_id", "customer_id", "project_id"):
                if item.get(key) is not None:
                    item[key] = str(item[key])

        return _render(
            request,
            "partials/knowledge.html",
            {
                "active_page": "knowledge",
                "items": items,
                "categories": categories,
                "q": q,
                "category": category,
                "layer": layer,
                "stats": stats,
            },
        )

    @router.post("/ui/knowledge/upload", response_class=HTMLResponse)
    async def upload_standard(request: Request, file: UploadFile = File(...)):
        """Ingest an uploaded document into the knowledge base."""
        try:
            data = await file.read()
            content_type = file.content_type or "application/octet-stream"

            ctx = await _get_ctx()
            from spec2sphere.core.knowledge.knowledge_service import ingest_documents

            llm = _get_llm()
            result = await ingest_documents(
                files=[(file.filename or "upload", data, content_type)],
                ctx=ctx,
                llm=llm,
            )
            ingested = result.get("ingested", 0)
            errors = result.get("errors", [])
            if errors:
                error_html = "".join(f"<p class='text-red-500'>{e}</p>" for e in errors[:3])
                return HTMLResponse(
                    f'<p class="text-amber-600">Ingested {ingested} chunk(s) with {len(errors)} error(s):</p>'
                    f"{error_html}"
                )
            return HTMLResponse(
                f'<p class="text-green-600">Ingested {ingested} chunk(s) from <strong>{file.filename}</strong>.</p>'
            )
        except Exception as exc:
            logger.error("Upload failed: %s", exc)
            return HTMLResponse(f'<p class="text-red-500">Upload failed: {exc}</p>')

    @router.delete("/ui/knowledge/{item_id}", response_class=HTMLResponse)
    async def delete_knowledge(item_id: str, request: Request):
        """Delete a knowledge item. Returns empty string so HTMX outerHTML swap removes the row."""
        try:
            from spec2sphere.core.knowledge.knowledge_service import delete_knowledge_item

            await delete_knowledge_item(item_id)
        except Exception as exc:
            logger.warning("Delete knowledge item %s failed: %s", item_id, exc)
        # Return empty — HTMX outerHTML swap will remove the element
        return HTMLResponse("")

    @router.get("/ui/knowledge/{item_id}/edit", response_class=HTMLResponse)
    async def edit_knowledge_form(item_id: str, request: Request):
        """Return an inline edit form for a knowledge item (HTMX outerHTML swap)."""
        try:
            from spec2sphere.core.knowledge.knowledge_service import get_knowledge_item

            item = await get_knowledge_item(item_id)
            if not item:
                return HTMLResponse('<p class="text-red-500 text-sm">Item not found</p>')
            html = (
                f'''<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-petrol ring-2 ring-petrol/20">
          <form hx-put="/ui/knowledge/{item_id}" hx-target="closest div.bg-white" hx-swap="outerHTML">
            <div class="space-y-2">
              <input type="text" name="title" value="{_escape(str(item.get("title", "")))}"
                     class="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm" placeholder="Title">
              <select name="category" class="rounded-md border border-gray-300 px-3 py-1.5 text-sm">
                {_category_options(str(item.get("category", "")))}
              </select>
              <textarea name="content" rows="4"
                        class="w-full rounded-md border border-gray-300 px-3 py-1.5 text-sm">{_escape(str(item.get("content", "")))}</textarea>
            </div>
            <div class="flex gap-2 mt-3">
              <button type="submit" class="bg-petrol text-white px-3 py-1 rounded text-sm hover:bg-petrol-light">Save</button>
              <button type="button"
                      hx-get="/ui/knowledge"
                      hx-target="#content-inner"
                      hx-select="#content-inner"
                      class="bg-gray-200 text-gray-700 px-3 py-1 rounded text-sm hover:bg-gray-300">Cancel</button>
            </div>
          </form>
        </div>'''
            )
            return HTMLResponse(html)
        except Exception as exc:
            return HTMLResponse(f'<p class="text-red-500 text-sm">Error: {exc}</p>')

    @router.put("/ui/knowledge/{item_id}", response_class=HTMLResponse)
    async def update_knowledge(item_id: str, request: Request):
        """Update a knowledge item from the inline edit form."""
        try:
            form = await request.form()
            title = str(form.get("title", "")) or None
            content = str(form.get("content", "")) or None
            category = str(form.get("category", "")) or None

            from spec2sphere.core.knowledge.knowledge_service import update_knowledge_item

            llm = _get_llm()
            await update_knowledge_item(
                item_id,
                title=title,
                content=content,
                category=category,
                llm=llm,
            )
            return HTMLResponse(
                '<div class="bg-white rounded-lg shadow-sm p-4 border-l-4 border-green-400">' +
                '<p class="text-sm text-green-600 font-medium">Updated successfully.</p>' +
                '<p class="text-xs text-gray-400 mt-1">Refresh the page to see the updated item.</p>' +
                '</div>'
            )
        except Exception as exc:
            logger.warning("Update knowledge item %s failed: %s", item_id, exc)
            return HTMLResponse(f'<p class="text-red-500 text-sm">Update failed: {exc}</p>')


    # ──────────────────────────────────────────────────────────────────────────
    # Landscape UI routes
    # ──────────────────────────────────────────────────────────────────────────

    @router.get("/ui/landscape", response_class=HTMLResponse)
    async def landscape_explorer(request: Request):
        """Landscape Explorer page with object inventory, dependency graph, and audit."""
        platform: str = request.query_params.get("platform", "")
        object_type: str = request.query_params.get("object_type", "")
        layer: str = request.query_params.get("layer", "")
        q: str = request.query_params.get("q", "")

        objects: list[dict] = []
        stats: Optional[dict] = None
        object_types: list[str] = []
        layers: list[str] = []

        try:
            ctx = await _get_ctx()
            from spec2sphere.core.scanner.landscape_store import (
                get_landscape_objects,
                get_landscape_stats,
            )

            objects = await get_landscape_objects(
                ctx=ctx,
                platform=platform or None,
                object_type=object_type or None,
                layer=layer or None,
                q=q or None,
                limit=200,
            )
            stats = await get_landscape_stats(ctx=ctx)

            # Derive filter options from full stats
            object_types = sorted(stats.get("by_object_type", {}).keys())
            layers = sorted(l for l in stats.get("by_layer", {}).keys() if l)

        except Exception as exc:
            logger.warning("Landscape explorer load error: %s", exc)

        return _render(
            request,
            "partials/landscape.html",
            {
                "active_page": "landscape",
                "objects": objects,
                "stats": stats,
                "object_types": object_types,
                "layers": layers,
                "platform": platform,
                "object_type": object_type,
                "layer": layer,
                "q": q,
            },
        )

    @router.get("/ui/landscape/{object_id}", response_class=HTMLResponse)
    async def landscape_detail(request: Request, object_id: str):
        """HTMX partial: detail panel for a single landscape object."""
        obj: Optional[dict] = None
        try:
            from spec2sphere.core.scanner.landscape_store import get_landscape_object

            obj = await get_landscape_object(object_id)
        except Exception as exc:
            logger.warning("Landscape object %s load error: %s", object_id, exc)

        if obj is None:
            return HTMLResponse('<p class="text-red-400 text-xs">Object not found.</p>')

        # Build a simple detail HTML fragment
        deps = obj.get("dependencies")
        if isinstance(deps, str):
            import json

            try:
                deps = json.loads(deps)
            except Exception:
                deps = []

        dep_html = ""
        if deps:
            dep_html = "<h4 class='text-xs font-semibold text-gray-500 uppercase mt-3 mb-1'>Dependencies</h4><ul class='space-y-0.5'>"
            for dep in deps[:10]:
                dep_html += f"<li class='text-xs text-gray-600'>→ {dep.get('target_id', '')}"
                if dep.get("dependency_type"):
                    dep_html += f" <span class='text-gray-400'>({dep['dependency_type']})</span>"
                dep_html += "</li>"
            dep_html += "</ul>"
            if len(deps) > 10:
                dep_html += f"<p class='text-xs text-gray-400'>…and {len(deps) - 10} more</p>"

        platform_colors = {"dsp": "text-blue-600", "sac": "text-amber-600"}
        plat_cls = platform_colors.get(obj.get("platform", ""), "text-petrol")

        doc_preview = ""
        if obj.get("documentation"):
            doc_text = str(obj["documentation"])[:400]
            doc_preview = (
                f"<h4 class='text-xs font-semibold text-gray-500 uppercase mt-3 mb-1'>Documentation</h4>"
                f"<p class='text-xs text-gray-600 leading-relaxed'>{doc_text}"
                f"{'…' if len(str(obj.get('documentation', ''))) > 400 else ''}</p>"
            )

        html = f"""
<div class="space-y-1">
  <p class="font-semibold text-gray-900 text-sm">{obj.get("object_name", "")}</p>
  <p class="font-mono text-xs text-gray-400">{obj.get("technical_name", "")}</p>
  <div class="flex flex-wrap gap-2 mt-2">
    <span class="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-600">{obj.get("object_type", "")}</span>
    <span class="px-2 py-0.5 rounded text-xs font-medium {plat_cls}">{(obj.get("platform") or "").upper()}</span>
    {f'<span class="px-2 py-0.5 rounded text-xs bg-gray-50 text-gray-500">{obj.get("layer")}</span>' if obj.get("layer") else ""}
  </div>
  {f'<p class="text-xs text-gray-400 mt-2">Scanned: {str(obj.get("last_scanned", ""))[:10]}</p>' if obj.get("last_scanned") else ""}
  {dep_html}
  {doc_preview}
</div>
"""
        return HTMLResponse(html)

    # ──────────────────────────────────────────────────────────────────────────
    # Landscape API routes
    # ──────────────────────────────────────────────────────────────────────────

    @router.get("/api/landscape/graph")
    async def landscape_graph(request: Request):
        """Return vis.js-compatible graph JSON built from landscape_objects dependencies."""
        try:
            ctx = await _get_ctx()
            from spec2sphere.core.scanner.landscape_store import get_landscape_objects
            import json

            objects = await get_landscape_objects(ctx=ctx, limit=500)

            platform_colors = {
                "dsp": "#60a5fa",  # blue-400
                "sac": "#C8963E",  # accent/gold
                "bw": "#05415A",  # petrol
            }

            nodes = []
            edges = []
            seen_node_ids: set[str] = set()

            for obj in objects:
                nid = str(obj["id"])
                if nid not in seen_node_ids:
                    nodes.append(
                        {
                            "id": nid,
                            "label": obj.get("object_name", nid)[:30],
                            "title": f"{obj.get('object_type', '')} | {obj.get('platform', '').upper()}",
                            "color": platform_colors.get(obj.get("platform", ""), "#d1d5db"),
                            "group": obj.get("platform", "unknown"),
                        }
                    )
                    seen_node_ids.add(nid)

                deps_raw = obj.get("dependencies")
                if isinstance(deps_raw, str):
                    try:
                        deps_raw = json.loads(deps_raw)
                    except Exception:
                        deps_raw = []
                if isinstance(deps_raw, list):
                    for dep in deps_raw:
                        target = dep.get("target_id", "")
                        if target:
                            edges.append(
                                {
                                    "from": nid,
                                    "to": target,
                                    "label": dep.get("dependency_type", ""),
                                }
                            )

            return JSONResponse({"nodes": nodes, "edges": edges})

        except Exception as exc:
            logger.error("Landscape graph build error: %s", exc)
            return JSONResponse({"nodes": [], "edges": [], "error": str(exc)})

    @router.post("/api/landscape/scan")
    async def trigger_scan(request: Request):
        """Trigger a background DSP/SAC scan via Celery task if available."""
        try:
            from spec2sphere.tasks.scan_tasks import run_scan  # type: ignore

            task = run_scan.delay()
            return JSONResponse({"status": "triggered", "task_id": str(task.id)})
        except ImportError:
            return JSONResponse(
                {"status": "no_celery", "message": "Celery task not available — run scan from Scanner page"}
            )
        except Exception as exc:
            logger.error("Scan trigger error: %s", exc)
            return JSONResponse({"status": "error", "message": str(exc)}, status_code=500)

    @router.get("/api/landscape/audit")
    async def landscape_audit(request: Request):
        """Full documentation audit with 4-dimension scoring per object."""
        try:
            ctx = await _get_ctx()
            from spec2sphere.core.audit.doc_audit import audit_documentation

            report = await audit_documentation(ctx)
            return JSONResponse(
                {
                    "total_objects": report.total_objects,
                    "audited_objects": report.audited_objects,
                    "average_score": round(report.average_score, 1),
                    "summary": report.summary,
                    "recommendations": report.recommendations[:10],
                    "scorecards": [
                        {
                            "object_id": sc.object_id,
                            "object_name": sc.object_name,
                            "platform": sc.platform,
                            "total_score": round(sc.total_score, 1),
                            "documented_fields": round(sc.documented_fields, 1),
                            "naming_compliance": round(sc.naming_compliance, 1),
                            "description_quality": round(sc.description_quality, 1),
                            "cross_references": round(sc.cross_references, 1),
                            "recommendations": sc.recommendations[:3],
                        }
                        for sc in report.scorecards[:50]
                    ],
                }
            )
        except Exception as exc:
            logger.error("Landscape audit error: %s", exc)
            return JSONResponse({"error": str(exc)}, status_code=500)

    return router
