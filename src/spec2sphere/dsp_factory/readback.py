"""Readback — verify that a deployed DSP object matches its specification.

Provides structural diff (column/join comparison) and route-dispatched
readback from the live DSP environment.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structural diff
# ---------------------------------------------------------------------------


def structural_diff(expected: dict, actual: dict) -> dict:
    """Compare expected spec against actual read-back structure.

    Checks:
    - Column presence (missing_column / extra_column)
    - Column type matches (type_mismatch)
    - Join count matches

    Returns:
        {"match": bool, "differences": [{"path": ..., "expected": ..., "actual": ..., "type": ...}]}
    """
    differences: list[dict] = []

    # Build column maps keyed by name
    expected_cols: dict[str, str] = {c["name"]: c.get("type", "") for c in (expected.get("columns") or [])}
    actual_cols: dict[str, str] = {c["name"]: c.get("type", "") for c in (actual.get("columns") or [])}

    # Missing columns (in expected but not actual)
    for col_name in expected_cols:
        if col_name not in actual_cols:
            differences.append(
                {
                    "path": f"columns.{col_name}",
                    "expected": col_name,
                    "actual": None,
                    "type": "missing_column",
                }
            )

    # Extra columns (in actual but not expected)
    for col_name in actual_cols:
        if col_name not in expected_cols:
            differences.append(
                {
                    "path": f"columns.{col_name}",
                    "expected": None,
                    "actual": col_name,
                    "type": "extra_column",
                }
            )

    # Type mismatches for columns that exist in both
    for col_name in expected_cols:
        if col_name in actual_cols:
            exp_type = expected_cols[col_name]
            act_type = actual_cols[col_name]
            if exp_type and act_type and exp_type != act_type:
                differences.append(
                    {
                        "path": f"columns.{col_name}.type",
                        "expected": exp_type,
                        "actual": act_type,
                        "type": "type_mismatch",
                    }
                )

    # Join count comparison
    expected_joins = expected.get("joins") or []
    actual_joins = actual.get("joins") or []
    exp_join_count = len(expected_joins) if isinstance(expected_joins, list) else expected_joins
    act_join_count = len(actual_joins) if isinstance(actual_joins, list) else actual_joins
    if exp_join_count != act_join_count:
        differences.append(
            {
                "path": "joins.count",
                "expected": exp_join_count,
                "actual": act_join_count,
                "type": "join_count_mismatch",
            }
        )

    return {"match": len(differences) == 0, "differences": differences}


# ---------------------------------------------------------------------------
# Readback dispatch
# ---------------------------------------------------------------------------


async def readback_object(
    tenant_id,
    environment: str,
    object_name: str,
    route: str = "cdp",
) -> dict:
    """Fetch the live structure of a deployed object via the specified route.

    Returns a dict with at least {"name": ..., "columns": [...], "joins": [...]}
    (stubs return minimal placeholder data).
    """
    if route == "cdp":
        return await _readback_via_cdp(tenant_id, environment, object_name)
    elif route == "api":
        return await _readback_via_api(tenant_id, environment, object_name)
    else:
        raise NotImplementedError(f"Unsupported readback route: {route!r}")


async def _readback_via_cdp(tenant_id, environment: str, object_name: str) -> dict:
    """Read object structure by scraping the DSP view editor via CDP."""
    import os  # noqa: PLC0415

    from spec2sphere.browser.cdp_helpers import get_cdp_session_for_tenant  # noqa: PLC0415

    logger.info(
        "CDP readback: object=%r env=%r tenant=%s",
        object_name,
        environment,
        tenant_id,
    )

    dsp_base_url = os.environ.get("DSP_BASE_URL", "")
    if not dsp_base_url:
        logger.warning("DSP_BASE_URL not set — CDP readback returning empty structure for %r", object_name)
        return {
            "name": object_name,
            "columns": [],
            "joins": [],
            "route": "cdp",
            "warning": "DSP_BASE_URL not configured",
        }

    session = await get_cdp_session_for_tenant(tenant_id, environment)
    if session is None:
        logger.warning("CDP session unavailable for readback of %r — returning empty structure", object_name)
        return {"name": object_name, "columns": [], "joins": [], "route": "cdp", "warning": "CDP session unavailable"}

    # DSP view editor URL — hash routing with object name
    view_url = f"{dsp_base_url.rstrip('/')}/dwaas-ui/index.html#/views/{object_name}"

    try:
        if await session.is_session_expired():
            logger.warning("CDP session expired during readback of %r — returning empty structure", object_name)
            return {"name": object_name, "columns": [], "joins": [], "route": "cdp", "warning": "session expired"}

        await session.navigate(view_url)

        # Wait for the view editor to load — column mapping panel is the reliable indicator
        try:
            await session.wait_for_element("[data-column-mapping]")
        except Exception:
            # Fallback: wait for general shell header as proxy for page load
            await session.wait_for_element("[id$='shellHeader'], [id$='shell-header']")

        # Extract column definitions via JavaScript evaluation
        # DSP view editor stores the model in the UI5 component tree
        columns_raw = await session.evaluate(
            """
            (function() {
                var result = {columns: [], joins: []};
                try {
                    // Try UI5 component model first
                    var oCore = sap.ui.getCore();
                    var models = oCore.getModel ? oCore.getModel() : null;
                    if (models) {
                        var data = models.getData ? models.getData() : null;
                        if (data && data.columns) {
                            result.columns = data.columns.map(function(c) {
                                return {name: c.name || c.technicalName, type: c.type || c.dataType || ''};
                            });
                        }
                        if (data && data.joins) {
                            result.joins = data.joins;
                        }
                        return JSON.stringify(result);
                    }
                } catch(e) {}

                // Fallback: scrape visible column list from DOM
                try {
                    var cols = document.querySelectorAll('[data-column-name], .sapDSPColumnItem');
                    cols.forEach(function(el) {
                        var name = el.getAttribute('data-column-name') || el.textContent.trim();
                        var type = el.getAttribute('data-column-type') || '';
                        if (name) result.columns.push({name: name, type: type});
                    });
                } catch(e) {}

                return JSON.stringify(result);
            })()
            """
        )

        columns: list[dict] = []
        joins: list[dict] = []

        if columns_raw:
            import json as _json  # noqa: PLC0415

            try:
                parsed = _json.loads(columns_raw) if isinstance(columns_raw, str) else columns_raw
                columns = parsed.get("columns", [])
                joins = parsed.get("joins", [])
            except Exception as exc:
                logger.warning("Could not parse CDP readback JSON for %r: %s", object_name, exc)

        logger.info(
            "CDP readback complete: object=%r columns=%d joins=%d",
            object_name,
            len(columns),
            len(joins),
        )
        return {"name": object_name, "columns": columns, "joins": joins, "route": "cdp"}

    except Exception as exc:
        logger.warning(
            "CDP readback failed for %r: %s — returning empty structure",
            object_name,
            exc,
        )
        return {
            "name": object_name,
            "columns": [],
            "joins": [],
            "route": "cdp",
            "warning": str(exc),
        }
    finally:
        await session.close()


async def _readback_via_api(tenant_id, environment: str, object_name: str) -> dict:
    """Read object structure via DSP REST API metadata endpoint."""
    import os  # noqa: PLC0415

    import httpx  # noqa: PLC0415

    logger.info(
        "API readback: object=%r env=%r tenant=%s",
        object_name,
        environment,
        tenant_id,
    )

    dsp_base_url = os.environ.get("DSP_BASE_URL", "")
    dsp_api_token = os.environ.get("DSP_API_TOKEN", "")
    if not dsp_base_url:
        logger.warning("DSP_BASE_URL not set — API readback returning empty structure for %r", object_name)
        return {
            "name": object_name,
            "columns": [],
            "joins": [],
            "route": "api",
            "warning": "DSP_BASE_URL not configured",
        }

    metadata_url = f"{dsp_base_url.rstrip('/')}/api/v1/dwc/repository/objects/{object_name}"
    headers = {}
    if dsp_api_token:
        headers["Authorization"] = f"Bearer {dsp_api_token}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(metadata_url, headers=headers)
            if resp.status_code == 404:
                logger.info("API readback: object %r not found (404)", object_name)
                return {"name": object_name, "columns": [], "joins": [], "route": "api", "warning": "object not found"}

            if resp.status_code != 200:
                raise RuntimeError(
                    f"DSP metadata API returned {resp.status_code} for {object_name!r}: {resp.text[:300]}"
                )

            data = resp.json()

    except httpx.ConnectError as exc:
        logger.warning("Could not connect to DSP metadata API for %r: %s", object_name, exc)
        return {"name": object_name, "columns": [], "joins": [], "route": "api", "warning": f"connect error: {exc}"}
    except RuntimeError as exc:
        logger.warning("API readback error for %r: %s", object_name, exc)
        return {"name": object_name, "columns": [], "joins": [], "route": "api", "warning": str(exc)}
    except Exception as exc:
        logger.warning("Unexpected API readback error for %r: %s", object_name, exc)
        return {"name": object_name, "columns": [], "joins": [], "route": "api", "warning": str(exc)}

    # Parse DSP API response — structure varies by object type
    # DSP typically returns columns under "columns" or "definition.columns"
    raw_columns = data.get("columns") or data.get("definition", {}).get("columns") or []
    columns = [
        {
            "name": c.get("name") or c.get("technicalName", ""),
            "type": c.get("type") or c.get("dataType", ""),
        }
        for c in raw_columns
        if c.get("name") or c.get("technicalName")
    ]

    raw_joins = data.get("joins") or data.get("definition", {}).get("joins") or []

    logger.info(
        "API readback complete: object=%r columns=%d joins=%d",
        object_name,
        len(columns),
        len(raw_joins),
    )
    return {"name": object_name, "columns": columns, "joins": raw_joins, "route": "api"}
