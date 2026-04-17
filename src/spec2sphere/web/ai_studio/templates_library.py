"""AI Studio template library — lists JSON seeds under templates/seeds/.

Forking a template POSTs to /ai-studio/templates/{slug}/fork, which copies
the seed config into a new draft row in dsp_ai.enhancements and redirects
to the editor for the new draft.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

_SEEDS_DIR = Path(os.environ.get("SEEDS_DIR", "templates/seeds")).resolve()
_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _list_seeds() -> list[dict]:
    out = []
    if not _SEEDS_DIR.exists():
        return out
    for p in sorted(_SEEDS_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text())
            out.append(
                {
                    "slug": p.stem,
                    "name": data.get("name", p.stem),
                    "kind": data.get("kind", "unknown"),
                    "render_hint": data.get("render_hint", ""),
                    "mode": data.get("mode", ""),
                }
            )
        except Exception:
            continue
    return out


def create_templates_router() -> APIRouter:
    router = APIRouter(prefix="/templates", tags=["ai-studio"])

    @router.get("/", response_class=HTMLResponse)
    @router.get("", response_class=HTMLResponse)
    async def list_templates(request: Request):
        return _templates.TemplateResponse(
            request,
            "partials/ai_studio_templates.html",
            {
                "request": request,
                "active_page": "ai-studio",
                "sub_nav": "templates",
                "seeds": _list_seeds(),
            },
        )

    @router.post("/{slug}/fork")
    async def fork(request: Request, slug: str):
        # Session membership + author email resolution mirror routes.py
        from .routes import _current_email, _is_author

        email = _current_email(request)
        if not _is_author(email):
            raise HTTPException(403, "not an AI Studio author")
        seed_path = _SEEDS_DIR / f"{slug}.json"
        if not seed_path.exists():
            raise HTTPException(404, "template not found")
        config = json.loads(seed_path.read_text())
        new_id = str(uuid.uuid4())
        forked_name = config.get("name", slug) + " (copy)"
        kind = config.get("kind", "narrative")
        from spec2sphere.dsp_ai.db import current_customer, get_conn  # noqa: PLC0415

        async with get_conn() as conn:
            await conn.execute(
                "INSERT INTO dsp_ai.enhancements (id, name, kind, config, author, customer) "
                "VALUES ($1::uuid, $2, $3, $4::jsonb, $5, $6)",
                new_id,
                forked_name,
                kind,
                json.dumps(config),
                email,
                current_customer(),
            )
        return RedirectResponse(f"/ai-studio/{new_id}/edit", status_code=303)

    return router
