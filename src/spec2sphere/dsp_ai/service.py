"""dsp-ai FastAPI service — live adapter entry point.

Started by docker compose on port 8000 (published as 8261 on the host).
CORS origin list comes from ``WIDGET_ALLOWED_ORIGINS`` (comma-separated);
empty in dev falls back to allow-all for the preview loop.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .adapters.live import router as live_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Best-effort startup: seed the Morning Brief + bootstrap the Brain
    schema. Any failure is logged and swallowed — dsp-ai must still start
    even when Postgres or Neo4j is warming up."""
    try:
        from .seeds import ensure_morning_brief_seeded

        await ensure_morning_brief_seeded()
    except Exception:
        logger.exception("Morning Brief seed failed on startup")

    try:
        from .brain.schema import bootstrap as bootstrap_brain

        await bootstrap_brain()
    except Exception:
        logger.exception("Brain schema bootstrap failed on startup")

    yield


def create_app() -> FastAPI:
    app = FastAPI(title="dsp-ai", version="0.1.0", lifespan=_lifespan)
    origins = [o.strip() for o in os.environ.get("WIDGET_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(live_router)
    from ..web.widget_routes import router as widget_router

    app.include_router(widget_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
