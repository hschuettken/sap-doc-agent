"""Live adapter — FastAPI router mounted at ``/v1/*`` on the dsp-ai service.

Session A exposes the minimum surface to unblock the Studio preview flow:
``POST /v1/enhance/{id}`` with Redis cache + engine, plus ``/healthz`` and
``/readyz``. SSE + telemetry land in Session B.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from .. import cache
from ..config import EnhancementMode
from ..engine import run_engine

router = APIRouter()


class EnhanceRequest(BaseModel):
    user: str | None = None
    context_hints: dict[str, Any] = {}
    context_key: str | None = None
    preview: bool = False


@router.post("/v1/enhance/{enhancement_id}")
async def enhance(enhancement_id: str, body: EnhanceRequest = Body(default=None)) -> dict:
    """Run an enhancement. Preview bypasses cache + skips DSP write-back."""
    body = body or EnhanceRequest()
    key = cache.key_for(enhancement_id, body.user, body.context_hints)

    if not body.preview:
        cached = await cache.get(key)
        if cached:
            cached["_cached"] = True
            return cached

    try:
        result = await run_engine(
            enhancement_id,
            user_id=body.user,
            context_hints=body.context_hints,
            context_key=body.context_key,
            mode_override=EnhancementMode.LIVE if body.preview else None,
            preview=body.preview,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="enhancement not found")

    if not body.preview:
        await cache.set_(key, result, ttl=600)
    return result


@router.get("/v1/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/v1/readyz")
async def readyz() -> dict:
    """Best-effort pings on each dependency; degrades gracefully."""
    warnings: list[str] = []

    try:
        import asyncpg

        from ..settings import postgres_dsn

        conn = await asyncpg.connect(postgres_dsn())
        await conn.close()
    except Exception:
        warnings.append("postgres")

    try:
        await cache._get().ping()
    except Exception:
        warnings.append("redis")

    return {"status": "ok", "warnings": warnings}
