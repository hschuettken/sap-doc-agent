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
    """Read object structure by scraping the DSP UI via CDP (stub)."""
    logger.info(
        "CDP readback: object=%r env=%r tenant=%s",
        object_name,
        environment,
        tenant_id,
    )
    # Stub — real implementation navigates to the DSP view editor and parses the structure
    return {"name": object_name, "columns": [], "joins": [], "route": "cdp"}


async def _readback_via_api(tenant_id, environment: str, object_name: str) -> dict:
    """Read object structure via DSP REST API (stub)."""
    logger.info(
        "API readback: object=%r env=%r tenant=%s",
        object_name,
        environment,
        tenant_id,
    )
    # Stub — real implementation calls DSP metadata API
    return {"name": object_name, "columns": [], "joins": [], "route": "api"}
