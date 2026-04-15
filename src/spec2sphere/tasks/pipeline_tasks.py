"""Celery tasks for the Spec2Sphere pipeline module.

Bridges async pipeline functions into synchronous Celery workers.
Each task fetches the default context, constructs an LLM provider, and
delegates to the appropriate pipeline module function.
"""

from __future__ import annotations

import asyncio
import logging

from spec2sphere.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="spec2sphere.tasks.pipeline_tasks.parse_requirement_task",
    queue="llm",
    max_retries=2,
    default_retry_delay=60,
)
def parse_requirement_task(self, requirement_id: str, project_id: str | None = None) -> dict:
    """Parse a requirement document using LLM.

    Runs the async ``parse_requirement`` coroutine inside a sync Celery worker
    via ``asyncio.run()``.

    Args:
        requirement_id: UUID string of the requirement to parse.
        project_id: Optional UUID string. When supplied it overrides the
            default context's project_id so the task can be scoped correctly.

    Returns:
        The updated requirement dict (same shape as ``parse_requirement``).
    """

    async def _run() -> dict:
        import uuid as _uuid

        from spec2sphere.app import SAPDocAgent
        from spec2sphere.pipeline.semantic_parser import parse_requirement
        from spec2sphere.tenant.context import ContextEnvelope, get_default_context

        ctx = await get_default_context()
        if project_id is not None:
            ctx = ContextEnvelope.single_tenant(
                tenant_id=ctx.tenant_id,
                customer_id=ctx.customer_id,
                project_id=_uuid.UUID(project_id),
            )

        # Obtain an LLM provider from the application singleton
        try:
            app = SAPDocAgent.from_config()
            llm = app.llm
        except Exception as exc:  # pragma: no cover
            logger.warning("parse_requirement_task: SAPDocAgent init failed, using None LLM: %s", exc)
            llm = None  # type: ignore[assignment]

        return await parse_requirement(requirement_id=requirement_id, ctx=ctx, llm=llm)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("parse_requirement_task failed for %s: %s", requirement_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="spec2sphere.tasks.pipeline_tasks.generate_hla_task",
    queue="llm",
    max_retries=2,
    default_retry_delay=60,
)
def generate_hla_task(self, requirement_id: str, project_id: str | None = None) -> dict:
    """Generate High-Level Architecture from a requirement.

    Runs the async ``generate_hla`` coroutine inside a sync Celery worker
    via ``asyncio.run()``.

    Args:
        requirement_id: UUID string of the (approved/draft) requirement.
        project_id: Optional UUID string. When supplied it overrides the
            default context's project_id.

    Returns:
        Dict with keys ``hla_id``, ``decisions_count``, ``status``.
    """

    async def _run() -> dict:
        import uuid as _uuid

        from spec2sphere.app import SAPDocAgent
        from spec2sphere.pipeline.hla_generator import generate_hla
        from spec2sphere.tenant.context import ContextEnvelope, get_default_context

        ctx = await get_default_context()
        if project_id is not None:
            ctx = ContextEnvelope.single_tenant(
                tenant_id=ctx.tenant_id,
                customer_id=ctx.customer_id,
                project_id=_uuid.UUID(project_id),
            )

        try:
            app = SAPDocAgent.from_config()
            llm = app.llm
        except Exception as exc:  # pragma: no cover
            logger.warning("generate_hla_task: SAPDocAgent init failed, using None LLM: %s", exc)
            llm = None  # type: ignore[assignment]

        return await generate_hla(requirement_id=requirement_id, ctx=ctx, llm=llm)

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("generate_hla_task failed for %s: %s", requirement_id, exc)
        raise self.retry(exc=exc)


@celery_app.task(
    bind=True,
    name="spec2sphere.tasks.pipeline_tasks.ingest_requirement_task",
    queue="general",
    max_retries=1,
    default_retry_delay=30,
)
def ingest_requirement_task(
    self,
    file_path: str,
    filename: str,
    content_type: str,
    project_id: str | None = None,
) -> dict:
    """Ingest a BRS file from disk into the requirements table.

    Useful when large documents are uploaded and processing is deferred to a
    background worker.

    Args:
        file_path: Absolute path to the file on the worker filesystem.
        filename: Original filename (used for title derivation and YAML detection).
        content_type: MIME type of the file.
        project_id: Optional UUID string for project scoping.

    Returns:
        Dict with ``requirement_id``, ``title``, ``status``.
    """

    async def _run() -> dict:
        import uuid as _uuid
        from pathlib import Path

        from spec2sphere.pipeline.intake import ingest_requirement
        from spec2sphere.tenant.context import ContextEnvelope, get_default_context

        ctx = await get_default_context()
        if project_id is not None:
            ctx = ContextEnvelope.single_tenant(
                tenant_id=ctx.tenant_id,
                customer_id=ctx.customer_id,
                project_id=_uuid.UUID(project_id),
            )

        file_data = Path(file_path).read_bytes()
        return await ingest_requirement(
            file_data=file_data,
            filename=filename,
            content_type=content_type,
            ctx=ctx,
        )

    try:
        return asyncio.run(_run())
    except Exception as exc:
        logger.error("ingest_requirement_task failed for %s: %s", filename, exc)
        raise self.retry(exc=exc)
