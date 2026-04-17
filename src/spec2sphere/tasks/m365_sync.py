"""Celery task: periodic M365 Graph Connector sync.

Pushes all Spec2Sphere content into the M365 external connection (search index)
so it's findable via Copilot for M365.

The task runs every 4 hours via Celery Beat (registered in schedules.py).
When the required env vars (M365_TENANT_ID, M365_CLIENT_ID, M365_CLIENT_SECRET,
M365_CONNECTION_ID) are not set, the task logs a skip message and exits cleanly —
no exception is raised, no alert is emitted.
"""

from __future__ import annotations

import asyncio
import logging
import os

from spec2sphere.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

_REQUIRED_VARS = ("M365_TENANT_ID", "M365_CLIENT_ID", "M365_CLIENT_SECRET", "M365_CONNECTION_ID")


def _m365_configured() -> bool:
    """Return True only when all four required env vars are non-empty."""
    return all(os.environ.get(v, "").strip() for v in _REQUIRED_VARS)


@celery_app.task(
    name="spec2sphere.tasks.m365_sync.sync_m365_graph_index",
    bind=True,
    max_retries=3,
    default_retry_delay=300,  # 5 minutes between retries
    acks_late=True,
)
def sync_m365_graph_index(self, incremental: bool = False):  # noqa: FBT001, FBT002
    """Push Spec2Sphere content into the M365 Graph Connector index.

    Args:
        incremental: When True, only push items modified since the last run.
                     Defaults to False (full sync). The scheduled beat entry
                     always uses the default (full sync) for reliability.
    """
    if not _m365_configured():
        logger.info(
            "sync_m365_graph_index: skipping — M365 env vars not configured "
            "(%s). Set all four vars to enable the sync.",
            ", ".join(_REQUIRED_VARS),
        )
        return {"status": "skipped", "reason": "M365 env vars not configured"}

    try:
        result = asyncio.run(_run_sync(incremental=incremental))
        logger.info("sync_m365_graph_index completed: %s", result)
        return result
    except Exception as exc:
        logger.error("sync_m365_graph_index failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc) from exc


async def _run_sync(incremental: bool) -> dict:
    """Async implementation — called from the synchronous Celery task via asyncio.run()."""
    from spec2sphere.copilot.graph_connector import GraphConnectorClient

    client = GraphConnectorClient(_allow_unconfigured=False)

    if incremental:
        from datetime import datetime, timedelta, timezone

        # Default lookback: 5 hours (covers the 4h beat interval with margin)
        since = datetime.now(tz=timezone.utc) - timedelta(hours=5)
        return await client.incremental_sync(since)
    else:
        return await client.full_sync()
