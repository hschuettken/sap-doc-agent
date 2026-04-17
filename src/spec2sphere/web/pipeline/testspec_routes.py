"""Pipeline UI routes: test spec editing and review."""

from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .shared import (
    _get_ctx,
    _render,
    _str_ids,
    _safe_json,
    _status_badge,
)

logger = logging.getLogger(__name__)


def create_testspec_routes() -> APIRouter:
    """Return an APIRouter with test spec routes."""
    router = APIRouter()

    @router.get("/ui/pipeline/testspec", response_class=HTMLResponse)
    async def testspec_list(request: Request):
        """List test specs."""
        test_specs: list[dict] = []
        error: Optional[str] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.test_generator import list_test_specs  # noqa: PLC0415

            test_specs = await list_test_specs(ctx)
            for ts in test_specs:
                _str_ids(ts)
        except Exception as exc:
            logger.warning("Test spec list error: %s", exc)
            error = str(exc)

        rows_html = ""
        for ts in test_specs:
            ts_id = ts.get("id", "")
            title = ts.get("title") or ts.get("name") or ts_id
            status = ts.get("status", "draft")
            badge = _status_badge(status)
            rows_html += (
                f'<tr class="hover:bg-gray-50 cursor-pointer" '
                f'    hx-get="/ui/pipeline/testspec/{ts_id}" '
                f'    hx-target="#content" hx-push-url="true" hx-select="#content-inner">'
                f'  <td class="px-4 py-3 text-sm font-medium text-gray-900">{title}</td>'
                f'  <td class="px-4 py-3 text-sm text-gray-500">{badge}</td>'
                f'  <td class="px-4 py-3 text-sm text-gray-400">{ts.get("created_at", "")[:10]}</td>'
                f"</tr>"
            )
        if not rows_html:
            rows_html = (
                '<tr><td colspan="3" class="px-4 py-6 text-center text-sm text-gray-400">'
                + (f"Error: {error}" if error else "No test specs yet.")
                + "</td></tr>"
            )

        html = (
            '<div id="content-inner" class="p-6">'
            '<div class="flex items-center justify-between mb-6">'
            '<h2 class="font-heading text-xl text-gray-900">Test Specs</h2>'
            "</div>"
            '<div class="bg-white rounded-lg shadow-sm overflow-hidden">'
            '<table class="w-full text-left">'
            "<thead><tr>"
            '<th class="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Title</th>'
            '<th class="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Status</th>'
            '<th class="px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Created</th>'
            "</tr></thead>"
            f"<tbody>{rows_html}</tbody>"
            "</table></div></div>"
        )
        return HTMLResponse(html)

    @router.get("/ui/pipeline/testspec/{ts_id}", response_class=HTMLResponse)
    async def testspec_detail(ts_id: str, request: Request):
        """Test spec detail."""
        test_spec: Optional[dict] = None
        error: Optional[str] = None

        try:
            ctx = await _get_ctx()
            from spec2sphere.pipeline.test_generator import get_test_spec  # noqa: PLC0415

            test_spec = await get_test_spec(ts_id)
            if test_spec:
                _str_ids(test_spec)
                test_spec["test_cases"] = _safe_json(test_spec.get("test_cases"))
                test_spec["tolerance_rules"] = _safe_json(test_spec.get("tolerance_rules"))
        except Exception as exc:
            logger.warning("Test spec detail error: %s", exc)
            error = str(exc)

        if test_spec is None and not error:
            error = "Test spec not found"

        return _render(
            request,
            "partials/testspec.html",
            {
                "active_page": "pipeline",
                "test_spec": test_spec,
                "error": error,
            },
        )

    @router.put("/ui/pipeline/testspec/{ts_id}/tolerances", response_class=HTMLResponse)
    async def update_testspec_tolerances(ts_id: str, request: Request):
        """Update tolerance_rules JSONB on a test spec from form data."""
        try:
            form = await request.form()
            import os
            import asyncpg  # noqa: PLC0415

            db_url = os.environ.get("DATABASE_URL", "")
            pg_url = db_url.replace("postgresql+psycopg://", "postgresql://").replace(
                "postgresql+asyncpg://", "postgresql://"
            )

            # Build tolerance_rules dict from form fields
            tolerance_rules: dict = {}
            for key, val in form.items():
                tolerance_rules[key] = str(val)

            conn = await asyncpg.connect(pg_url)
            try:
                await conn.execute(
                    "UPDATE test_specs SET tolerance_rules = $1::jsonb WHERE id = $2::uuid",
                    json.dumps(tolerance_rules),
                    ts_id,
                )
            finally:
                await conn.close()

            return HTMLResponse('<p class="text-xs text-green-600 font-medium">Tolerance rules saved.</p>')
        except Exception as exc:
            logger.error("Update tolerances for test spec %s failed: %s", ts_id, exc)
            return HTMLResponse(f'<p class="text-xs text-red-500">Save failed: {exc}</p>')

    @router.put("/ui/pipeline/testspec/{ts_id}/mode", response_class=HTMLResponse)
    async def update_testspec_mode(ts_id: str, request: Request):
        """Toggle test mode between preservation and improvement."""
        try:
            form = await request.form()
            new_mode = str(form.get("test_mode", "preservation"))
            if new_mode not in ("preservation", "improvement"):
                new_mode = "preservation"

            import os
            import asyncpg  # noqa: PLC0415

            db_url = os.environ.get("DATABASE_URL", "")
            pg_url = db_url.replace("postgresql+psycopg://", "postgresql://").replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            conn = await asyncpg.connect(pg_url)
            try:
                await conn.execute(
                    "UPDATE test_specs SET test_mode = $1 WHERE id = $2::uuid",
                    new_mode,
                    ts_id,
                )
            finally:
                await conn.close()

            active_pres = new_mode == "preservation"
            pres_cls = "bg-blue-600 text-white" if active_pres else "bg-white text-gray-500 hover:bg-gray-50"
            impr_cls = "bg-purple-600 text-white" if not active_pres else "bg-white text-gray-500 hover:bg-gray-50"
            html = (
                f'<div id="test-mode-toggle" '
                f'class="inline-flex rounded-full border border-gray-200 overflow-hidden text-xs font-medium">'
                f'<form hx-put="/ui/pipeline/testspec/{ts_id}/mode" '
                f'hx-target="#test-mode-toggle" hx-swap="outerHTML" class="inline">'
                f'<input type="hidden" name="test_mode" value="preservation">'
                f'<button type="submit" class="px-3 py-1 flex items-center gap-1.5 transition-colors {pres_cls}">'
                f'<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
                f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
                f'd="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 '
                f"01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 "
                f'5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>'
                f"</svg>Preservation</button></form>"
                f'<form hx-put="/ui/pipeline/testspec/{ts_id}/mode" '
                f'hx-target="#test-mode-toggle" hx-swap="outerHTML" class="inline">'
                f'<input type="hidden" name="test_mode" value="improvement">'
                f'<button type="submit" class="px-3 py-1 flex items-center gap-1.5 transition-colors {impr_cls}">'
                f'<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">'
                f'<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" '
                f'd="M13 10V3L4 14h7v7l9-11h-7z"/>'
                f"</svg>Improvement</button></form>"
                f"</div>"
            )
            return HTMLResponse(html)
        except Exception as exc:
            logger.error("Update test mode for test spec %s failed: %s", ts_id, exc)
            return HTMLResponse(f'<div class="p-2 text-xs text-red-500">Failed: {exc}</div>')

    @router.put("/ui/pipeline/testspec/{ts_id}/deltas", response_class=HTMLResponse)
    async def update_testspec_deltas(ts_id: str, request: Request):
        """Update expected deltas for improvement mode."""
        try:
            form = await request.form()
            deltas = []
            idx = 0
            while True:
                name = form.get(f"delta_name_{idx}")
                if name is None:
                    break
                desc = str(form.get(f"delta_desc_{idx}", ""))
                if str(name).strip():
                    deltas.append({"name": str(name).strip(), "description": desc.strip()})
                idx += 1

            import os
            import asyncpg  # noqa: PLC0415

            db_url = os.environ.get("DATABASE_URL", "")
            pg_url = db_url.replace("postgresql+psycopg://", "postgresql://").replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            conn = await asyncpg.connect(pg_url)
            try:
                await conn.execute(
                    "UPDATE test_specs SET expected_deltas = $1::jsonb WHERE id = $2::uuid",
                    json.dumps(deltas),
                    ts_id,
                )
            finally:
                await conn.close()

            return HTMLResponse(f'<p class="text-xs text-green-600 font-medium">{len(deltas)} delta(s) saved.</p>')
        except Exception as exc:
            logger.error("Update deltas for test spec %s failed: %s", ts_id, exc)
            return HTMLResponse(f'<p class="text-xs text-red-500">Save failed: {exc}</p>')

    return router
