"""Shared constants and helper utilities for pipeline UI routes."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── Status badge colours ──────────────────────────────────────────────────────
STATUS_CLASSES = {
    "draft": "bg-gray-100 text-gray-600",
    "pending_review": "bg-amber-100 text-amber-700",
    "approved": "bg-green-100 text-green-700",
    "rejected": "bg-red-100 text-red-700",
    "rework": "bg-blue-100 text-blue-700",
    "generating": "bg-purple-100 text-purple-700",
    "parsed": "bg-teal-100 text-teal-700",
    "ingested": "bg-indigo-100 text-indigo-700",
}

# ── Pipeline stage definitions ────────────────────────────────────────────────
PIPELINE_STAGES = [
    {
        "key": "intake",
        "label": "Intake",
        "url": "/ui/pipeline/requirements",
        "icon": "M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12",
    },
    {
        "key": "interpretation",
        "label": "Interpretation",
        "url": "/ui/pipeline/requirements",
        "icon": "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2",
    },
    {
        "key": "hla",
        "label": "HLA",
        "url": "/ui/pipeline/architecture",
        "icon": "M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z",
    },
    {
        "key": "tech_spec",
        "label": "Tech Spec",
        "url": "/ui/pipeline/techspec",
        "icon": "M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4",
    },
    {
        "key": "test_spec",
        "label": "Test Spec",
        "url": "/ui/pipeline/testspec",
        "icon": "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4",
    },
    {
        "key": "build",
        "label": "Build",
        "url": "#",
        "icon": "M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z",
    },
    {
        "key": "deploy",
        "label": "Deploy",
        "url": "#",
        "icon": "M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2",
    },
    {
        "key": "qa",
        "label": "QA",
        "url": "#",
        "icon": "M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z",
    },
    {"key": "release", "label": "Release", "url": "#", "icon": "M7 16V4m0 0L3 8m4-4l4 4m6 0v12m0 0l4-4m-4 4l-4-4"},
    {
        "key": "docs",
        "label": "Docs",
        "url": "#",
        "icon": "M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253",
    },
]


def _render(request: Request, template: str, ctx: dict) -> HTMLResponse:
    ctx["request"] = request
    ctx.setdefault("status_classes", STATUS_CLASSES)
    return templates.TemplateResponse(request, template, ctx)


def _get_llm():
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
    from spec2sphere.tenant.context import get_default_context

    return await get_default_context()


def _status_badge(status: str) -> str:
    cls = STATUS_CLASSES.get(status or "draft", "bg-gray-100 text-gray-600")
    return f'<span class="inline-block px-2 py-0.5 rounded-full text-xs font-medium {cls}">{status or "draft"}</span>'


def _safe_json(val) -> dict | list:
    """Return parsed JSON if val is a string, or the value itself."""
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return {}
    return val or {}


def _str_ids(d: dict) -> dict:
    """Stringify UUID fields in a dict so Jinja2 can render them."""
    import uuid as _uuid

    for k, v in list(d.items()):
        if isinstance(v, _uuid.UUID):
            d[k] = str(v)
    return d
