"""Field queries, transformation rules, version history, and scan run routes.

Provides structured access to object_fields, transformation_rules,
object_history, and scan_runs tables introduced in migration 009.

All API routes live under /api/fields, /api/objects/{id}/..., /api/rules,
and /api/scan-runs.
"""

from __future__ import annotations

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from spec2sphere.core.scanner.landscape_store import _get_conn, _row_to_dict

logger = logging.getLogger(__name__)

router = APIRouter(tags=["fields"])


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _uuid(value: str) -> UUID:
    """Parse a UUID string, raising 400 on bad format."""
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {value!r}")


# ---------------------------------------------------------------------------
# Field queries
# ---------------------------------------------------------------------------


@router.get("/api/fields", summary="Search fields across all objects")
async def search_fields(
    field_name: Optional[str] = Query(None, description="ILIKE search on field_name"),
    data_type: Optional[str] = Query(None, description="Exact match on data_type"),
    source_object: Optional[str] = Query(None, description="ILIKE search on source_object"),
    object_type: Optional[str] = Query(None, description="Filter by parent object_type"),
    platform: Optional[str] = Query(None, description="Filter by parent platform"),
    is_key: Optional[bool] = Query(None, description="Filter key fields"),
    field_role: Optional[str] = Query(None, description="Filter by field_role"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    """Search fields across all landscape objects with optional filters."""
    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if field_name is not None:
        conditions.append(f"f.field_name ILIKE '%' || ${idx} || '%'")
        params.append(field_name)
        idx += 1

    if data_type is not None:
        conditions.append(f"f.data_type = ${idx}")
        params.append(data_type)
        idx += 1

    if source_object is not None:
        conditions.append(f"f.source_object ILIKE '%' || ${idx} || '%'")
        params.append(source_object)
        idx += 1

    if object_type is not None:
        conditions.append(f"lo.object_type = ${idx}")
        params.append(object_type)
        idx += 1

    if platform is not None:
        conditions.append(f"lo.platform = ${idx}")
        params.append(platform)
        idx += 1

    if is_key is not None:
        conditions.append(f"f.is_key = ${idx}")
        params.append(is_key)
        idx += 1

    if field_role is not None:
        conditions.append(f"f.field_role = ${idx}")
        params.append(field_role)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            f"""
            SELECT
                f.id, f.landscape_object_id, f.field_name, f.field_ordinal,
                f.data_type, f.field_length, f.field_decimals, f.expression,
                f.source_object, f.source_field, f.is_key, f.is_calculated,
                f.is_aggregated, f.aggregation_type, f.field_role,
                f.description, f.metadata,
                lo.object_name, lo.technical_name, lo.platform, lo.object_type
            FROM object_fields f
            JOIN landscape_objects lo ON lo.id = f.landscape_object_id
            {where}
            ORDER BY lo.platform, lo.object_name, f.field_ordinal NULLS LAST, f.field_name
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )
        count_row = await conn.fetchrow(
            f"""
            SELECT COUNT(*) AS total
            FROM object_fields f
            JOIN landscape_objects lo ON lo.id = f.landscape_object_id
            {where}
            """,
            *params[:-2],
        )
        return {
            "items": [_row_to_dict(r) for r in rows],
            "total": count_row["total"],
            "limit": limit,
            "offset": offset,
        }
    finally:
        await conn.close()


@router.get("/api/objects/{object_id}/fields", summary="Get all fields for a landscape object")
async def get_object_fields(object_id: str) -> dict:
    """Return all fields for a specific landscape object, ordered by field_ordinal."""
    oid = _uuid(object_id)
    conn = await _get_conn()
    try:
        # Verify object exists
        obj = await conn.fetchrow(
            "SELECT id, object_name, technical_name, platform, object_type FROM landscape_objects WHERE id = $1",
            oid,
        )
        if not obj:
            raise HTTPException(status_code=404, detail=f"Object not found: {object_id}")

        rows = await conn.fetch(
            """
            SELECT
                id, landscape_object_id, field_name, field_ordinal,
                data_type, field_length, field_decimals, expression,
                source_object, source_field, is_key, is_calculated,
                is_aggregated, aggregation_type, field_role,
                description, metadata
            FROM object_fields
            WHERE landscape_object_id = $1
            ORDER BY field_ordinal NULLS LAST, field_name
            """,
            oid,
        )
        return {
            "object": _row_to_dict(obj),
            "fields": [_row_to_dict(r) for r in rows],
            "count": len(rows),
        }
    finally:
        await conn.close()


@router.get("/api/fields/stats", summary="Field statistics")
async def get_field_stats() -> dict:
    """Return field statistics: totals grouped by data_type, field_role, and platform."""
    conn = await _get_conn()
    try:
        total_row = await conn.fetchrow("SELECT COUNT(*) AS total FROM object_fields")

        by_type_rows = await conn.fetch(
            """
            SELECT data_type, COUNT(*) AS count
            FROM object_fields
            WHERE data_type IS NOT NULL
            GROUP BY data_type
            ORDER BY count DESC
            """
        )

        by_role_rows = await conn.fetch(
            """
            SELECT field_role, COUNT(*) AS count
            FROM object_fields
            WHERE field_role IS NOT NULL
            GROUP BY field_role
            ORDER BY count DESC
            """
        )

        by_platform_rows = await conn.fetch(
            """
            SELECT lo.platform, COUNT(f.id) AS count
            FROM object_fields f
            JOIN landscape_objects lo ON lo.id = f.landscape_object_id
            GROUP BY lo.platform
            ORDER BY count DESC
            """
        )

        return {
            "total_fields": total_row["total"],
            "by_data_type": {r["data_type"]: r["count"] for r in by_type_rows},
            "by_field_role": {r["field_role"]: r["count"] for r in by_role_rows},
            "by_platform": {r["platform"]: r["count"] for r in by_platform_rows},
        }
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Transformation rules
# ---------------------------------------------------------------------------


@router.get("/api/objects/{object_id}/rules", summary="Get transformation rules for an object")
async def get_object_rules(object_id: str) -> dict:
    """Return all transformation rules attached to a specific landscape object."""
    oid = _uuid(object_id)
    conn = await _get_conn()
    try:
        obj = await conn.fetchrow("SELECT id, object_name FROM landscape_objects WHERE id = $1", oid)
        if not obj:
            raise HTTPException(status_code=404, detail=f"Object not found: {object_id}")

        rows = await conn.fetch(
            """
            SELECT
                id, landscape_object_id, scan_run_id,
                source_object, target_object, source_field, target_field,
                rule_type, rule_expression, routine_name, routine_code, metadata
            FROM transformation_rules
            WHERE landscape_object_id = $1
            ORDER BY target_field, source_field
            """,
            oid,
        )
        return {
            "object_id": object_id,
            "object_name": obj["object_name"],
            "rules": [_row_to_dict(r) for r in rows],
            "count": len(rows),
        }
    finally:
        await conn.close()


@router.get("/api/rules/search", summary="Search transformation rules")
async def search_rules(
    source_field: Optional[str] = Query(None),
    target_field: Optional[str] = Query(None),
    rule_type: Optional[str] = Query(None),
    source_object: Optional[str] = Query(None),
    target_object: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> dict:
    """Search transformation rules by field names, objects, or rule type."""
    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if source_field is not None:
        conditions.append(f"source_field ILIKE '%' || ${idx} || '%'")
        params.append(source_field)
        idx += 1

    if target_field is not None:
        conditions.append(f"target_field ILIKE '%' || ${idx} || '%'")
        params.append(target_field)
        idx += 1

    if rule_type is not None:
        conditions.append(f"rule_type = ${idx}")
        params.append(rule_type)
        idx += 1

    if source_object is not None:
        conditions.append(f"source_object ILIKE '%' || ${idx} || '%'")
        params.append(source_object)
        idx += 1

    if target_object is not None:
        conditions.append(f"target_object ILIKE '%' || ${idx} || '%'")
        params.append(target_object)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.extend([limit, offset])

    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            f"""
            SELECT
                id, landscape_object_id, scan_run_id,
                source_object, target_object, source_field, target_field,
                rule_type, rule_expression, routine_name, routine_code, metadata
            FROM transformation_rules
            {where}
            ORDER BY target_object, target_field
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )
        count_row = await conn.fetchrow(
            f"SELECT COUNT(*) AS total FROM transformation_rules {where}",
            *params[:-2],
        )
        return {
            "items": [_row_to_dict(r) for r in rows],
            "total": count_row["total"],
            "limit": limit,
            "offset": offset,
        }
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Field lineage
# ---------------------------------------------------------------------------


@router.get("/api/fields/{field_name}/lineage", summary="Trace field lineage upstream")
async def get_field_lineage(field_name: str) -> dict:
    """Trace a field through the dependency chain, following source_object/source_field upstream.

    Returns a list of lineage nodes, each with the object it lives on, the
    expression mapping it, and its upstream sources (recursive).
    """
    conn = await _get_conn()
    try:
        # Collect all roots — objects that carry this field_name
        root_rows = await conn.fetch(
            """
            SELECT
                f.field_name, f.expression, f.source_object, f.source_field,
                lo.id AS object_id, lo.object_name, lo.technical_name,
                lo.platform, lo.object_type
            FROM object_fields f
            JOIN landscape_objects lo ON lo.id = f.landscape_object_id
            WHERE f.field_name = $1
            """,
            field_name,
        )

        if not root_rows:
            return {"field_name": field_name, "lineage": [], "found": 0}

        # Build lineage tree iteratively to avoid recursion limits.
        # visited set prevents infinite loops in circular dependencies.
        visited: set[tuple[str, str]] = set()  # (object_name, field_name)

        async def _build_node(obj_name: str, obj_tech: str, fname: str, expression: Optional[str]) -> dict:
            node: dict[str, Any] = {
                "object_name": obj_name,
                "technical_name": obj_tech,
                "field_name": fname,
                "expression": expression,
                "upstream": [],
            }
            key = (obj_name, fname)
            if key in visited:
                node["cycle_detected"] = True
                return node
            visited.add(key)

            # Look for upstream sources for this (object, field) combination
            src_rows = await conn.fetch(
                """
                SELECT
                    f.field_name, f.expression, f.source_object, f.source_field,
                    lo.object_name, lo.technical_name, lo.platform, lo.object_type
                FROM object_fields f
                JOIN landscape_objects lo ON lo.id = f.landscape_object_id
                WHERE lo.object_name = $1
                  AND f.field_name = $2
                  AND f.source_object IS NOT NULL
                  AND f.source_field IS NOT NULL
                LIMIT 1
                """,
                obj_name,
                fname,
            )

            for src in src_rows:
                # Find the upstream object that provides source_field
                upstream_rows = await conn.fetch(
                    """
                    SELECT
                        f.field_name, f.expression,
                        lo.object_name, lo.technical_name
                    FROM object_fields f
                    JOIN landscape_objects lo ON lo.id = f.landscape_object_id
                    WHERE (lo.object_name = $1 OR lo.technical_name = $1)
                      AND f.field_name = $2
                    LIMIT 5
                    """,
                    src["source_object"],
                    src["source_field"],
                )
                if upstream_rows:
                    for up in upstream_rows:
                        node["upstream"].append(
                            await _build_node(
                                up["object_name"],
                                up["technical_name"],
                                up["field_name"],
                                up["expression"],
                            )
                        )
                else:
                    # Source referenced but not scanned — record as stub
                    node["upstream"].append(
                        {
                            "object_name": src["source_object"],
                            "technical_name": src["source_object"],
                            "field_name": src["source_field"],
                            "expression": None,
                            "upstream": [],
                            "unresolved": True,
                        }
                    )

            return node

        lineage = []
        for row in root_rows:
            lineage.append(
                await _build_node(
                    row["object_name"],
                    row["technical_name"],
                    row["field_name"],
                    row["expression"],
                )
            )

        return {"field_name": field_name, "lineage": lineage, "found": len(lineage)}
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Version history
# ---------------------------------------------------------------------------


@router.get("/api/objects/{object_id}/history", summary="Get version history for an object")
async def get_object_history(
    object_id: str,
    limit: int = Query(20, ge=1, le=200),
) -> dict:
    """Return version snapshots for a landscape object, most recent first."""
    oid = _uuid(object_id)
    conn = await _get_conn()
    try:
        obj = await conn.fetchrow(
            "SELECT id, object_name, technical_name, version_number FROM landscape_objects WHERE id = $1",
            oid,
        )
        if not obj:
            raise HTTPException(status_code=404, detail=f"Object not found: {object_id}")

        rows = await conn.fetch(
            """
            SELECT
                id, landscape_object_id, scan_run_id, version_number,
                object_name, technical_name, object_type, platform, layer,
                content_hash, change_type, changes, captured_at
            FROM object_history
            WHERE landscape_object_id = $1
            ORDER BY version_number DESC
            LIMIT $2
            """,
            oid,
            limit,
        )
        return {
            "object_id": object_id,
            "object_name": obj["object_name"],
            "current_version": obj["version_number"],
            "history": [_row_to_dict(r) for r in rows],
            "count": len(rows),
        }
    finally:
        await conn.close()


@router.get(
    "/api/objects/{object_id}/history/{version}",
    summary="Get a specific version snapshot",
)
async def get_object_version(object_id: str, version: int) -> dict:
    """Return the full snapshot for a specific version number of a landscape object."""
    oid = _uuid(object_id)
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT
                id, landscape_object_id, scan_run_id, version_number,
                object_name, technical_name, object_type, platform, layer,
                metadata, documentation, dependencies, fields_snapshot,
                content_hash, change_type, changes, captured_at
            FROM object_history
            WHERE landscape_object_id = $1 AND version_number = $2
            """,
            oid,
            version,
        )
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Version {version} not found for object {object_id}",
            )
        return _row_to_dict(row)
    finally:
        await conn.close()


@router.get("/api/objects/{object_id}/diff", summary="Compare two object versions")
async def diff_object_versions(
    object_id: str,
    from_version: int = Query(..., alias="from", description="Source version number"),
    to_version: int = Query(..., alias="to", description="Target version number"),
) -> dict:
    """Compute a structured diff between two version snapshots of an object.

    Compares metadata, documentation, content_hash, and fields_snapshot between
    the two specified versions.
    """
    oid = _uuid(object_id)
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT
                version_number, object_name, technical_name, object_type,
                platform, layer, metadata, documentation, dependencies,
                fields_snapshot, content_hash, change_type, changes, captured_at
            FROM object_history
            WHERE landscape_object_id = $1 AND version_number = ANY($2::int[])
            ORDER BY version_number
            """,
            oid,
            [from_version, to_version],
        )

        version_map: dict[int, dict] = {r["version_number"]: _row_to_dict(r) for r in rows}

        if from_version not in version_map:
            raise HTTPException(status_code=404, detail=f"Version {from_version} not found")
        if to_version not in version_map:
            raise HTTPException(status_code=404, detail=f"Version {to_version} not found")

        v_from = version_map[from_version]
        v_to = version_map[to_version]

        # Scalar field diff
        scalar_fields = [
            "object_name",
            "technical_name",
            "object_type",
            "platform",
            "layer",
            "documentation",
            "content_hash",
        ]
        scalar_diff: dict[str, dict] = {}
        for field in scalar_fields:
            if v_from.get(field) != v_to.get(field):
                scalar_diff[field] = {"from": v_from.get(field), "to": v_to.get(field)}

        # Fields snapshot diff — by field_name
        from_fields: dict[str, dict] = {
            f["field_name"]: f
            for f in (v_from.get("fields_snapshot") or [])
            if isinstance(f, dict) and "field_name" in f
        }
        to_fields: dict[str, dict] = {
            f["field_name"]: f for f in (v_to.get("fields_snapshot") or []) if isinstance(f, dict) and "field_name" in f
        }

        added_fields = [name for name in to_fields if name not in from_fields]
        removed_fields = [name for name in from_fields if name not in to_fields]
        changed_fields: list[dict] = []
        for name in from_fields:
            if name in to_fields and from_fields[name] != to_fields[name]:
                changed_fields.append({"field_name": name, "from": from_fields[name], "to": to_fields[name]})

        return {
            "object_id": object_id,
            "from_version": from_version,
            "to_version": to_version,
            "scalar_changes": scalar_diff,
            "fields": {
                "added": added_fields,
                "removed": removed_fields,
                "changed": changed_fields,
            },
            "has_changes": bool(scalar_diff or added_fields or removed_fields or changed_fields),
        }
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Scan runs
# ---------------------------------------------------------------------------


@router.get("/api/scan-runs", summary="List scan runs")
async def list_scan_runs(
    limit: int = Query(50, ge=1, le=500),
    scanner_type: Optional[str] = Query(None),
) -> dict:
    """List scan runs, most recent first."""
    conditions: list[str] = []
    params: list[Any] = []
    idx = 1

    if scanner_type is not None:
        conditions.append(f"scanner_type = ${idx}")
        params.append(scanner_type)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)

    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            f"""
            SELECT
                id, customer_id, project_id, scanner_type, scan_config,
                status, started_at, completed_at, object_count, field_count,
                stats, change_summary, version_label
            FROM scan_runs
            {where}
            ORDER BY started_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
        return {
            "items": [_row_to_dict(r) for r in rows],
            "count": len(rows),
        }
    finally:
        await conn.close()


@router.get("/api/scan-runs/{run_id}", summary="Get scan run details")
async def get_scan_run(run_id: str) -> dict:
    """Return full details and stats for a specific scan run."""
    rid = _uuid(run_id)
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT
                id, customer_id, project_id, scanner_type, scan_config,
                status, started_at, completed_at, object_count, field_count,
                stats, change_summary, version_label
            FROM scan_runs
            WHERE id = $1
            """,
            rid,
        )
        if not row:
            raise HTTPException(status_code=404, detail=f"Scan run not found: {run_id}")

        result = _row_to_dict(row)

        # Attach object count for this run from object_history
        history_count = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM object_history WHERE scan_run_id = $1", rid)
        result["history_entries"] = history_count["cnt"]

        return result
    finally:
        await conn.close()
