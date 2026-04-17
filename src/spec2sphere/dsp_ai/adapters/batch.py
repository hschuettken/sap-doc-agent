"""Batch adapter — Celery tasks that run enhancements on schedule.

Scheduled by Celery Beat (BATCH_CRON) and also dispatched on demand
from the NOTIFY listener ("enhancement_published" → enqueue a backfill).
"""

from __future__ import annotations

import asyncio
import logging

import asyncpg
from celery import shared_task

from ..engine import run_engine
from ..settings import postgres_dsn

logger = logging.getLogger(__name__)


async def _active_users(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch("SELECT user_id FROM dsp_ai.user_state WHERE last_visited_at > NOW() - INTERVAL '14 days'")
    return [r["user_id"] for r in rows] or ["_default"]


async def _published_batch_enhancements(conn: asyncpg.Connection) -> list[str]:
    rows = await conn.fetch(
        "SELECT id::text FROM dsp_ai.enhancements WHERE status = 'published' AND (config->>'mode' IN ('batch', 'both'))"
    )
    return [r["id"] for r in rows]


async def _run_batch_enhancements_async() -> dict:
    conn = await asyncpg.connect(postgres_dsn())
    try:
        enh_ids = await _published_batch_enhancements(conn)
        users = await _active_users(conn)
    finally:
        await conn.close()

    ran = 0
    errors = 0
    for eid in enh_ids:
        for user in users:
            try:
                await run_engine(eid, user_id=user, context_hints={}, context_key="default")
                ran += 1
            except Exception:
                logger.exception("batch run failed for enhancement=%s user=%s", eid, user)
                errors += 1
    return {"enhancements": len(enh_ids), "users": len(users), "ran": ran, "errors": errors}


@shared_task(name="spec2sphere.dsp_ai.run_batch_enhancements", queue="ai-batch")
def run_batch_enhancements() -> dict:
    """Sync Celery entrypoint — wraps the async implementation with asyncio.run."""
    return asyncio.run(_run_batch_enhancements_async())
