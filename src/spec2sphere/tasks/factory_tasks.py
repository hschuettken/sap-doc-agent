"""Celery tasks for DSP/SAC factory deployment and data reconciliation.

Bridges async factory functions into synchronous Celery workers using a
per-task event loop so that asyncpg and other async dependencies work
correctly inside sync Celery processes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from celery import shared_task

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Async bridge helper
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run a coroutine in a fresh event loop and return its result."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# DSP deployment task
# ---------------------------------------------------------------------------


@shared_task(name="spec2sphere.tasks.factory_tasks.run_dsp_deployment")
def run_dsp_deployment(
    tenant_id: str,
    customer_id: str,
    project_id: str,
    tech_spec_id: str,
    environment: str,
) -> dict[str, Any]:
    """Deploy all DSP technical objects for a tech spec.

    Fetches technical_objects where tech_spec_id matches and platform='dsp',
    generates a topologically-sorted deployment manifest, then deploys each
    object in order via the multi-route deployer.

    Args:
        tenant_id: UUID string for the tenant.
        customer_id: UUID string for the customer.
        project_id: UUID string for the project.
        tech_spec_id: UUID string for the technical spec to deploy.
        environment: Target environment (sandbox | test | production).

    Returns:
        Dict with keys: run_id, status, results (list of per-object outcomes).
    """

    async def _deploy() -> dict[str, Any]:
        from spec2sphere.db import _get_conn
        from spec2sphere.dsp_factory.artifact_generator import generate_deployment_manifest
        from spec2sphere.dsp_factory.deployer import create_deployment_run, deploy_object
        from spec2sphere.tenant.context import ContextEnvelope

        ctx = ContextEnvelope.single_tenant(
            tenant_id=UUID(tenant_id),
            customer_id=UUID(customer_id),
            project_id=UUID(project_id),
        )

        # Create a deployment run record
        run_info = await create_deployment_run(ctx, tech_spec_id=tech_spec_id)
        run_id: str = run_info["run_id"]

        # Fetch technical objects for this spec on the dsp platform
        conn = await _get_conn()
        try:
            rows = await conn.fetch(
                """
                SELECT id, name, object_type, dependencies, sql_definition, columns
                FROM technical_objects
                WHERE tech_spec_id = $1
                  AND platform = 'dsp'
                ORDER BY name
                """,
                tech_spec_id,
            )
            objects = [dict(r) for r in rows]
        finally:
            await conn.close()

        # Topological sort
        manifest = generate_deployment_manifest(objects)

        # Deploy each object in manifest order
        results: list[dict[str, Any]] = []
        overall_status = "completed"

        for obj in manifest:
            result = await deploy_object(ctx, run_id, obj, environment=environment)
            results.append(result)
            if result.get("status") == "failed":
                overall_status = "failed"

        # Update deployment_runs row
        summary = {
            "total": len(results),
            "deployed": sum(1 for r in results if r.get("status") == "deployed"),
            "failed": sum(1 for r in results if r.get("status") == "failed"),
        }
        conn = await _get_conn()
        try:
            await conn.execute(
                """
                UPDATE deployment_runs
                SET status = $1,
                    summary = $2::jsonb,
                    completed_at = NOW()
                WHERE id = $3
                """,
                overall_status,
                json.dumps(summary),
                run_id,
            )
        finally:
            await conn.close()

        # SSE: notify frontends the active-factory pane should refresh.
        try:
            from spec2sphere.dsp_ai.events import emit

            await emit(
                "factory_status_changed",
                {"run_id": str(run_id), "status": overall_status},
            )
        except Exception:
            pass  # best-effort

        return {"run_id": run_id, "status": overall_status, "results": results}

    return _run_async(_deploy())


# ---------------------------------------------------------------------------
# SAC deployment task
# ---------------------------------------------------------------------------


@shared_task(name="spec2sphere.tasks.factory_tasks.run_sac_deployment")
def run_sac_deployment(
    tenant_id: str,
    customer_id: str,
    project_id: str,
    blueprint_id: str,
    environment: str,
) -> dict[str, Any]:
    """Deploy a SAC story from a blueprint via browser automation.

    Fetches the sac_blueprint from DB, connects a SACPlaywrightAdapter, and
    drives the full story-creation sequence.

    Args:
        tenant_id: UUID string for the tenant.
        customer_id: UUID string for the customer.
        project_id: UUID string for the project.
        blueprint_id: UUID string for the SAC blueprint to deploy.
        environment: Target environment (sandbox | test | production).

    Returns:
        Dict with keys: run_id, status, story_id, pages, screenshots.
    """

    async def _deploy() -> dict[str, Any]:
        from spec2sphere.db import _get_conn
        from spec2sphere.dsp_factory.deployer import create_deployment_run
        from spec2sphere.sac_factory.playwright_adapter import SACPlaywrightAdapter
        from spec2sphere.tenant.context import ContextEnvelope

        ctx = ContextEnvelope.single_tenant(
            tenant_id=UUID(tenant_id),
            customer_id=UUID(customer_id),
            project_id=UUID(project_id),
        )

        # Create a deployment run record
        run_info = await create_deployment_run(ctx, blueprint_id=blueprint_id)
        run_id: str = run_info["run_id"]

        # Fetch the SAC blueprint
        conn = await _get_conn()
        try:
            row = await conn.fetchrow(
                """
                SELECT id, blueprint_json
                FROM sac_blueprints
                WHERE id = $1
                """,
                blueprint_id,
            )
            if row is None:
                raise ValueError(f"SAC blueprint not found: {blueprint_id}")
            blueprint_raw = row["blueprint_json"]
            blueprint: dict[str, Any] = blueprint_raw if isinstance(blueprint_raw, dict) else json.loads(blueprint_raw)
        finally:
            await conn.close()

        # Deploy via Playwright adapter
        adapter = SACPlaywrightAdapter(tenant_id=UUID(tenant_id), environment=environment)
        await adapter.connect()
        deploy_result = await adapter.deploy_from_blueprint(blueprint)

        overall_status = deploy_result.get("status", "completed")

        # Update deployment_runs row
        summary = {
            "story_id": deploy_result.get("story_id"),
            "page_count": len(deploy_result.get("pages", [])),
        }
        conn = await _get_conn()
        try:
            await conn.execute(
                """
                UPDATE deployment_runs
                SET status = $1,
                    summary = $2::jsonb,
                    completed_at = NOW()
                WHERE id = $3
                """,
                overall_status,
                json.dumps(summary),
                run_id,
            )
        finally:
            await conn.close()

        try:
            from spec2sphere.dsp_ai.events import emit

            await emit(
                "factory_status_changed",
                {"run_id": str(run_id), "status": overall_status},
            )
        except Exception:
            pass

        return {
            "run_id": run_id,
            "status": overall_status,
            "story_id": deploy_result.get("story_id"),
            "pages": deploy_result.get("pages", []),
            "screenshots": deploy_result.get("screenshots", []),
        }

    return _run_async(_deploy())


# ---------------------------------------------------------------------------
# Reconciliation task
# ---------------------------------------------------------------------------

# DSP test spec categories that contain reconciliation cases
_DSP_TEST_CATEGORIES = (
    "structural",
    "volume",
    "aggregate",
    "edge_case",
    "sample_trace",
)


@shared_task(name="spec2sphere.tasks.factory_tasks.run_reconciliation")
def run_reconciliation(
    tenant_id: str,
    customer_id: str,
    project_id: str,
    test_spec_id: str,
) -> dict[str, Any]:
    """Execute all reconciliation test cases from a test spec.

    Loads the test spec from DB, flattens test cases from DSP categories
    (structural, volume, aggregate, edge_case, sample_trace) into a unified
    list, runs the reconciliation engine, and returns a summary.

    Args:
        tenant_id: UUID string for the tenant.
        customer_id: UUID string for the customer.
        project_id: UUID string for the project.
        test_spec_id: UUID string of the test spec to reconcile.

    Returns:
        Dict with keys: status, summary, results.
    """

    async def _reconcile() -> dict[str, Any]:
        from spec2sphere.db import _get_conn
        from spec2sphere.factory.reconciliation import compute_aggregate_summary, run_reconciliation
        from spec2sphere.tenant.context import ContextEnvelope

        ctx = ContextEnvelope.single_tenant(
            tenant_id=UUID(tenant_id),
            customer_id=UUID(customer_id),
            project_id=UUID(project_id),
        )

        # Fetch the test spec
        conn = await _get_conn()
        try:
            row = await conn.fetchrow(
                """
                SELECT id, test_cases
                FROM test_specs
                WHERE id = $1
                """,
                test_spec_id,
            )
            if row is None:
                raise ValueError(f"Test spec not found: {test_spec_id}")
            raw_cases = row["test_cases"]
            spec_data: Any = raw_cases if isinstance(raw_cases, dict) else json.loads(raw_cases)
        finally:
            await conn.close()

        # Flatten cases from DSP category buckets into a single list
        test_cases: list[dict[str, Any]] = []
        if isinstance(spec_data, list):
            # Already a flat list
            test_cases = spec_data
        elif isinstance(spec_data, dict):
            for category in _DSP_TEST_CATEGORIES:
                bucket = spec_data.get(category, [])
                if isinstance(bucket, list):
                    for case in bucket:
                        if isinstance(case, dict):
                            # Tag with category if not already present
                            tagged = dict(case)
                            tagged.setdefault("category", category)
                            test_cases.append(tagged)

        # Run the reconciliation engine
        results = await run_reconciliation(ctx, test_spec_id, test_cases)
        summary = compute_aggregate_summary(results)

        overall_status = "completed"
        if summary.get("defect_pct", 0) > 0 or summary.get("review_pct", 0) > 0:
            overall_status = "needs_review"

        return {
            "status": overall_status,
            "summary": summary,
            "results": results,
        }

    return _run_async(_reconcile())
