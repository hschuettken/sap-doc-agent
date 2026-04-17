"""dsp-ai FastAPI service — live adapter entry point.

Started by docker compose on port 8000 (published as 8261 on the host).
CORS origin list comes from ``WIDGET_ALLOWED_ORIGINS`` (comma-separated);
empty in dev falls back to allow-all for the preview loop.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .adapters.live import router as live_router


def create_app() -> FastAPI:
    app = FastAPI(title="dsp-ai", version="0.1.0")
    origins = [o.strip() for o in os.environ.get("WIDGET_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    app.include_router(live_router)
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
