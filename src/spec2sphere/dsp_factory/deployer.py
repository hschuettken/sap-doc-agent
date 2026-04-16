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

        # Re-deploy the prior definition via the route system
        logger.info("Rolling back %s to prior definition", step["artifact_name"])
        obj = {
            "name": step["artifact_name"],
            "object_type": step["artifact_type"],
            "platform": step["platform"],
            "definition": prior_definition,
        }
        try:
            await _execute_route(ctx, step["route_chosen"], obj, environment)
            await conn.execute(
                "UPDATE deployment_steps SET status = 'rolled_back', completed_at = now() WHERE id = $1",
                step_id,
            )
            return {"status": "rolled_back", "step_id": str(step_id)}
        except Exception as exc:
            logger.warning("Rollback execution failed for %s: %s", step["artifact_name"], exc)
            await conn.execute(
                "UPDATE deployment_steps SET status = 'rollback_failed', error_message = $1, completed_at = now() WHERE id = $2",
                str(exc),
                step_id,
            )
            return {"status": "rollback_failed", "step_id": str(step_id), "error": str(exc)}
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
    import os  # noqa: PLC0415

    from spec2sphere.browser.cdp_helpers import get_cdp_session_for_tenant  # noqa: PLC0415

    dsp_base_url = os.environ.get("DSP_BASE_URL", "")
    if not dsp_base_url:
        raise RuntimeError("DSP_BASE_URL is not set — cannot construct DSP SQL console URL for CDP deploy")

    session = await get_cdp_session_for_tenant(ctx.tenant_id, environment)
    if session is None:
        raise RuntimeError("Chrome CDP not available — no session returned for tenant")

    object_name: str = obj.get("name", "unknown")
    sql: str = obj.get("generated_artifact") or obj.get("definition", {}).get("sql", "")
    if not sql:
        raise RuntimeError(f"No SQL found in object {object_name!r} for CDP deploy")

    # Construct SQL console URL — DSP uses hash-based routing per space/object
    sql_console_url = f"{dsp_base_url.rstrip('/')}/dwaas-ui/index.html#/sql-console"

    try:
        if await session.is_session_expired():
            raise RuntimeError("CDP session is expired — re-authentication required")

        logger.info("CDP deploy: navigating to SQL console for object=%r env=%r", object_name, environment)
        await session.navigate(sql_console_url)
        await session.wait_for_element(".ace_editor")

        # Clear existing content and type the new SQL
        # Ace editor doesn't fire change events — select all, delete, then type
        await session.click(".ace_editor")
        await session.press_key("a", modifiers=["Control"])  # Select all
        await session.press_key("Delete")
        await session.type_text(".ace_editor", sql)

        # Save: Ctrl+S then wait for busy indicator to clear (DSP quirk)
        await session.sap_save()
        await session.wait_for_busy_clear()

        # Deploy: click deploy button, confirm dialog, wait for busy to clear
        await session.sap_deploy()
        await session.wait_for_busy_clear()

        # Verify no errors appeared
        errors = await session.check_for_errors()
        if errors:
            raise RuntimeError(f"CDP deploy reported errors for {object_name!r}: {errors}")

        logger.info("CDP deploy succeeded: object=%r env=%r", object_name, environment)

    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"CDP deploy failed for object {object_name!r}: {exc}") from exc
    finally:
        await session.close()


async def _deploy_via_api(
    ctx: ContextEnvelope,
    obj: dict,
    environment: str,
) -> None:
    """Deploy via SAP Datasphere REST API."""
    import json as _json  # noqa: PLC0415
    import os  # noqa: PLC0415

    import httpx  # noqa: PLC0415

    dsp_base_url = os.environ.get("DSP_BASE_URL", "")
    dsp_api_token = os.environ.get("DSP_API_TOKEN", "")
    if not dsp_base_url:
        raise RuntimeError("DSP_BASE_URL is not set — cannot call DSP REST API")

    object_name: str = obj.get("name", "unknown")
    object_type: str = obj.get("object_type", "relational_view")

    # DSP REST API endpoint for view/object management
    api_url = f"{dsp_base_url.rstrip('/')}/api/v1/dwc/repository/objects"

    headers = {"Content-Type": "application/json"}
    if dsp_api_token:
        headers["Authorization"] = f"Bearer {dsp_api_token}"

    payload = {
        "name": object_name,
        "type": object_type,
        "definition": obj.get("definition", {}),
        "sql": obj.get("generated_artifact") or obj.get("definition", {}).get("sql", ""),
    }

    logger.info(
        "API deploy: POST %s object=%r env=%r customer=%s",
        api_url,
        object_name,
        environment,
        ctx.customer_id,
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(api_url, headers=headers, content=_json.dumps(payload))
            if resp.status_code not in (200, 201, 204):
                raise RuntimeError(f"DSP API returned {resp.status_code} for {object_name!r}: {resp.text[:500]}")
    except httpx.ConnectError as exc:
        raise RuntimeError(f"Could not connect to DSP API at {api_url}: {exc}") from exc
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"DSP API deploy failed for {object_name!r}: {exc}") from exc

    logger.info("API deploy succeeded: object=%r env=%r", object_name, environment)


async def _deploy_via_csn(
    ctx: ContextEnvelope,
    obj: dict,
    environment: str,
) -> None:
    """Deploy by generating a CSN definition and importing it into DSP."""
    import json as _json  # noqa: PLC0415
    import os  # noqa: PLC0415

    import httpx  # noqa: PLC0415

    from spec2sphere.browser.cdp_helpers import get_cdp_session_for_tenant  # noqa: PLC0415

    csn = generate_csn_definition(obj)
    object_name: str = obj.get("name", "unknown")
    logger.info(
        "CSN deploy: object=%r env=%r csn_keys=%r",
        object_name,
        environment,
        list(csn.get("definitions", {}).keys()),
    )

    dsp_base_url = os.environ.get("DSP_BASE_URL", "")
    if not dsp_base_url:
        raise RuntimeError("DSP_BASE_URL is not set — cannot perform CSN import deploy")

    csn_json = _json.dumps(csn)

    # Try REST import endpoint first (preferred, no UI needed)
    dsp_api_token = os.environ.get("DSP_API_TOKEN", "")
    import_url = f"{dsp_base_url.rstrip('/')}/api/v1/dwc/repository/import"
    headers = {"Content-Type": "application/json"}
    if dsp_api_token:
        headers["Authorization"] = f"Bearer {dsp_api_token}"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(import_url, headers=headers, content=csn_json)
            if resp.status_code in (200, 201, 204):
                logger.info("CSN import via REST succeeded: object=%r env=%r", object_name, environment)
                return
            logger.warning(
                "CSN REST import returned %d for %r — falling back to CDP import UI",
                resp.status_code,
                object_name,
            )
    except httpx.ConnectError:
        logger.warning("DSP REST import endpoint unreachable — falling back to CDP import UI")
    except Exception as exc:
        logger.warning("DSP REST import failed for %r: %s — falling back to CDP", object_name, exc)

    # CDP fallback: navigate to DSP import UI and upload the CSN JSON
    session = await get_cdp_session_for_tenant(ctx.tenant_id, environment)
    if session is None:
        raise RuntimeError(f"CSN deploy for {object_name!r}: REST import failed and Chrome CDP not available")

    import_ui_url = f"{dsp_base_url.rstrip('/')}/dwaas-ui/index.html#/import"

    try:
        if await session.is_session_expired():
            raise RuntimeError("CDP session is expired — re-authentication required")

        await session.navigate(import_ui_url)

        # Wait for the import dialog to appear (space switcher area is a reliable landmark)
        await session.wait_for_element("[id$='spaceSelector']")

        # Inject the CSN JSON directly via evaluate — DSP import UI uses an internal model
        inject_result = await session.evaluate(
            f"""
            (function() {{
                const csn = {csn_json};
                if (window.sap && window.sap.fpa && window.sap.fpa.shell) {{
                    window.sap.fpa.shell.importCSN(csn);
                    return 'injected';
                }}
                return 'no-shell-api';
            }})()
            """
        )

        if inject_result != "injected":
            raise RuntimeError(f"CSN inject via CDP returned {inject_result!r} — SAP shell API not accessible")

        await session.wait_for_busy_clear()

        errors = await session.check_for_errors()
        if errors:
            raise RuntimeError(f"CSN import reported errors for {object_name!r}: {errors}")

        logger.info("CSN deploy via CDP succeeded: object=%r env=%r", object_name, environment)

    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"CSN CDP import failed for {object_name!r}: {exc}") from exc
    finally:
        await session.close()
