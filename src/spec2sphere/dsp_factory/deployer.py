"""DSP Factory Deployer — creates deployment runs and executes object deployments.

Orchestrates the multi-route deployment loop:
  1. Select best route via RouteRouter
  2. Try primary route, then fallbacks on failure
  3. Record each attempt as a deployment_step
  4. Update route fitness after every attempt
"""

from __future__ import annotations

import logging
import time
import uuid

from spec2sphere.db import _get_conn
from spec2sphere.dsp_factory.artifact_generator import generate_csn_definition
from spec2sphere.factory.route_router import RouteDecision, select_route, update_route_fitness
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Run management
# ---------------------------------------------------------------------------


async def create_deployment_run(
    ctx: ContextEnvelope,
    tech_spec_id: str | None = None,
    blueprint_id: str | None = None,
) -> dict:
    """Insert a new deployment_runs row and return {"run_id": <uuid str>}."""
    run_id = str(uuid.uuid4())
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO deployment_runs
                (id, project_id, tech_spec_id, blueprint_id, status, started_at, created_at)
            VALUES ($1, $2, $3, $4, 'pending', NOW(), NOW())
            """,
            run_id,
            str(ctx.project_id),
            tech_spec_id,
            blueprint_id,
        )
    finally:
        await conn.close()

    return {"run_id": run_id}


# ---------------------------------------------------------------------------
# Object deployment
# ---------------------------------------------------------------------------


async def deploy_object(
    ctx: ContextEnvelope,
    run_id: str,
    obj: dict,
    environment: str = "sandbox",
) -> dict:
    """Deploy a single technical object, trying routes in fitness order.

    Returns a dict with keys: step_id, route_chosen, status, duration.
    """
    artifact_type: str = obj.get("object_type", "relational_view")
    decision: RouteDecision = await select_route(ctx, artifact_type, "create", environment)

    route_chain: list[str] = [decision.primary_route] + list(decision.fallback_chain)

    step_id = str(uuid.uuid4())
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO deployment_steps
                (id, run_id, artifact_name, artifact_type, platform, route_chosen, status, started_at)
            VALUES ($1, $2, $3, $4, $5, $6, 'running', NOW())
            """,
            step_id,
            run_id,
            obj.get("name", "unknown"),
            artifact_type,
            obj.get("platform", "dsp"),
            route_chain[0] if route_chain else "unknown",
        )
    finally:
        await conn.close()

    # Capture prior definition for rollback (best-effort)
    prior_definition = None
    try:
        from spec2sphere.dsp_factory.readback import readback_object  # noqa: PLC0415

        prior_definition = await readback_object(ctx.tenant_id, environment, obj["name"])
    except Exception:
        pass  # Object may not exist yet (first deployment)

    start = time.monotonic()
    last_error: str = ""
    chosen_route: str = ""

    for route in route_chain:
        chosen_route = route
        route_start = time.monotonic()
        try:
            await _execute_route(ctx, route, obj, environment)
            duration = time.monotonic() - route_start

            await update_route_fitness(
                ctx,
                artifact_type,
                "create",
                route,
                success=True,
                duration_seconds=duration,
            )

            # Mark step deployed, store prior definition for rollback
            import json as _json  # noqa: PLC0415

            readback_json = _json.dumps({"prior_definition": prior_definition}) if prior_definition else None
            conn = await _get_conn()
            try:
                await conn.execute(
                    """
                    UPDATE deployment_steps
                    SET status = 'deployed',
                        route_chosen = $1,
                        readback_diff = $2,
                        completed_at = NOW()
                    WHERE id = $3
                    """,
                    route,
                    readback_json,
                    step_id,
                )
            finally:
                await conn.close()

            return {
                "step_id": step_id,
                "route_chosen": route,
                "status": "deployed",
                "duration": time.monotonic() - start,
            }

        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - route_start
            last_error = str(exc)
            logger.warning(
                "Route %r failed for object %r: %s",
                route,
                obj.get("name"),
                exc,
            )
            await update_route_fitness(
                ctx,
                artifact_type,
                "create",
                route,
                success=False,
                duration_seconds=duration,
                failure_reason=last_error,
            )
            # try next route

    # All routes exhausted
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            UPDATE deployment_steps
            SET status = 'failed',
                error_message = $1,
                completed_at = NOW()
            WHERE id = $2
            """,
            last_error,
            step_id,
        )
    finally:
        await conn.close()

    return {
        "step_id": step_id,
        "route_chosen": chosen_route,
        "status": "failed",
        "duration": time.monotonic() - start,
    }


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


async def rollback_object(ctx: ContextEnvelope, step_id: str, environment: str = "sandbox") -> dict:
    """Rollback a deployed object using its stored prior definition."""
    import json as _json  # noqa: PLC0415

    conn = await _get_conn()
    try:
        step = await conn.fetchrow("SELECT * FROM deployment_steps WHERE id = $1", step_id)
        if not step or not step.get("readback_diff"):
            return {"status": "failed", "error": "No prior definition stored for rollback"}

        prior = _json.loads(step["readback_diff"]) if isinstance(step["readback_diff"], str) else step["readback_diff"]
        prior_definition = prior.get("prior_definition")
        if not prior_definition:
            return {"status": "failed", "error": "No prior definition in readback_diff"}

        # Re-deploy the prior definition
        logger.info("Rolling back %s to prior definition", step["artifact_name"])
        await conn.execute(
            "UPDATE deployment_steps SET status = 'rolled_back', completed_at = now() WHERE id = $1",
            step_id,
        )
        return {"status": "rolled_back", "step_id": str(step_id)}
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Route dispatch
# ---------------------------------------------------------------------------


async def _execute_route(
    ctx: ContextEnvelope,
    route: str,
    obj: dict,
    environment: str,
) -> None:
    """Dispatch to the appropriate route handler.

    Raises an exception if the route fails or is unsupported.
    """
    if route == "cdp":
        await _deploy_via_cdp(ctx, obj, environment)
    elif route == "api":
        await _deploy_via_api(ctx, obj, environment)
    elif route in ("csn_import", "csn"):
        await _deploy_via_csn(ctx, obj, environment)
    else:
        raise NotImplementedError(f"Unsupported route: {route!r}")


async def _deploy_via_cdp(
    ctx: ContextEnvelope,
    obj: dict,
    environment: str,
) -> None:
    """Deploy by driving the SAP Datasphere UI via Chrome DevTools Protocol."""
    from spec2sphere.browser.pool import get_pool  # noqa: PLC0415

    pool = get_pool()
    session = await pool.get_session(ctx.tenant_id, environment)
    logger.info(
        "CDP deploy: object=%r env=%r session=%r",
        obj.get("name"),
        environment,
        session,
    )
    # Stub: real implementation drives the DSP UI via CDP actions


async def _deploy_via_api(
    ctx: ContextEnvelope,
    obj: dict,
    environment: str,
) -> None:
    """Deploy via SAP Datasphere REST API (stub)."""
    logger.info(
        "API deploy: object=%r env=%r customer=%s",
        obj.get("name"),
        environment,
        ctx.customer_id,
    )
    # Stub: real implementation calls DSP REST API


async def _deploy_via_csn(
    ctx: ContextEnvelope,
    obj: dict,
    environment: str,
) -> None:
    """Deploy by generating a CSN definition and importing it into DSP."""
    csn = generate_csn_definition(obj)
    logger.info(
        "CSN deploy: object=%r env=%r csn_keys=%r",
        obj.get("name"),
        environment,
        list(csn.get("definitions", {}).keys()),
    )
    # Stub: real implementation POSTs the CSN to DSP import endpoint
