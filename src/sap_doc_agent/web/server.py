"""FastAPI web server for SAP Doc Agent.

Serves documentation as HTML for M365 Copilot knowledge crawling,
and provides API endpoints for Copilot Actions.

Run: uvicorn sap_doc_agent.web.server:create_app --factory --port 8260
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

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

    # --- HTML documentation serving ---

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def landing_page():
        """Landing page with links to all documentation."""
        # Build index from output dir
        pages = []
        objects_dir = output_path / "objects"
        if objects_dir.exists():
            for type_dir in sorted(objects_dir.iterdir()):
                if type_dir.is_dir():
                    for md_file in sorted(type_dir.glob("*.md")):
                        pages.append(
                            {
                                "title": md_file.stem,
                                "url": f"/docs/objects/{type_dir.name}/{md_file.stem}",
                                "type": type_dir.name,
                            }
                        )

        page_list = "".join(f'<li><a href="{p["url"]}">[{p["type"]}] {p["title"]}</a></li>' for p in pages)
        reports_list = ""
        reports_dir = output_path / "reports"
        if reports_dir.exists():
            for f in sorted(reports_dir.glob("*")):
                reports_list += f'<li><a href="/reports/{f.name}">{f.name}</a></li>'

        return f"""<!DOCTYPE html>
<html><head><title>SAP Doc Agent</title>
<style>
body {{ font-family: sans-serif; max-width: 900px; margin: 40px auto; padding: 0 20px; }}
h1 {{ color: #1a365d; }}
h2 {{ color: #2b6cb0; }}
a {{ color: #2b6cb0; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}
li {{ margin: 4px 0; }}
</style></head><body>
<h1>SAP Documentation Agent</h1>
<p>Documentation knowledge base for M365 Copilot.</p>
<h2>Objects ({len(pages)})</h2>
<ul>{page_list or "<li>No objects scanned yet</li>"}</ul>
<h2>Reports</h2>
<ul>{reports_list or "<li>No reports generated yet</li>"}</ul>
<p><a href="/sitemap.xml">Sitemap</a> | <a href="/docs">API Documentation</a> | <a href="/health">Health</a></p>
</body></html>"""

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
