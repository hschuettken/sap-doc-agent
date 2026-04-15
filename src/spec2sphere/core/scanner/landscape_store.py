"""Landscape store — persist scanner results into landscape_objects table.

Tenant-scoped by (customer_id, project_id). Upserts on
(customer_id, project_id, platform, technical_name) with fallback to
object_name when technical_name is absent.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID

import asyncpg

from spec2sphere.scanner.models import ScanResult
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_conn() -> asyncpg.Connection:
    db_url = os.environ.get("DATABASE_URL", "")
    url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


def _row_to_dict(row: asyncpg.Record) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
    return d


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def store_scan_results(
    scan_result: ScanResult,
    ctx: ContextEnvelope,
    platform: str = "dsp",
) -> dict:
    """Convert ScannedObjects from ScanResult into landscape_objects rows.

    Upserts on (customer_id, project_id, platform, technical_name) where
    technical_name is non-empty, otherwise falls back to object_name.
    Stores dependencies from ScanResult.dependencies in the dependencies
    JSONB field (keyed by source object_id).
    Updates last_scanned on every call.

    Returns {"stored": int, "updated": int}.
    """
    if not scan_result.objects:
        return {"stored": 0, "updated": 0}

    # Build per-object dependency list: {object_id -> [dep dicts]}
    dep_map: dict[str, list[dict]] = {}
    for dep in scan_result.dependencies:
        dep_map.setdefault(dep.source_id, []).append(
            {
                "target_id": dep.target_id,
                "dependency_type": dep.dependency_type.value,
                "metadata": dep.metadata,
            }
        )

    conn = await _get_conn()
    stored = 0
    updated = 0
    now = datetime.now(timezone.utc)

    try:
        async with conn.transaction():
            for obj in scan_result.objects:
                tech_name = obj.technical_name or obj.object_id
                obj_name = obj.name or tech_name
                deps_json = json.dumps(dep_map.get(obj.object_id, []))

                # Check if row already exists for this scope + identity
                existing = await conn.fetchrow(
                    """
                    SELECT id FROM landscape_objects
                    WHERE customer_id = $1
                      AND ($2::uuid IS NULL OR project_id = $2)
                      AND platform = $3
                      AND (technical_name = $4 OR object_name = $4)
                    LIMIT 1
                    """,
                    ctx.customer_id,
                    ctx.project_id,
                    platform,
                    tech_name,
                )

                if existing:
                    await conn.execute(
                        """
                        UPDATE landscape_objects SET
                            object_type   = $1,
                            object_name   = $2,
                            technical_name = $3,
                            layer         = $4,
                            metadata      = $5::jsonb,
                            documentation = $6,
                            dependencies  = $7::jsonb,
                            last_scanned  = $8
                        WHERE id = $9
                        """,
                        obj.object_type.value,
                        obj_name,
                        tech_name,
                        obj.layer or None,
                        json.dumps(obj.metadata),
                        obj.description or obj.source_code or None,
                        deps_json,
                        now,
                        existing["id"],
                    )
                    updated += 1
                else:
                    await conn.execute(
                        """
                        INSERT INTO landscape_objects
                            (customer_id, project_id, platform, object_type,
                             object_name, technical_name, layer, metadata,
                             documentation, dependencies, last_scanned)
                        VALUES
                            ($1, $2, $3, $4, $5, $6, $7, $8::jsonb,
                             $9, $10::jsonb, $11)
                        """,
                        ctx.customer_id,
                        ctx.project_id,
                        platform,
                        obj.object_type.value,
                        obj_name,
                        tech_name,
                        obj.layer or None,
                        json.dumps(obj.metadata),
                        obj.description or obj.source_code or None,
                        deps_json,
                        now,
                    )
                    stored += 1

    finally:
        await conn.close()

    logger.info(
        "landscape_store: stored=%d updated=%d platform=%s customer=%s project=%s",
        stored,
        updated,
        platform,
        ctx.customer_id,
        ctx.project_id,
    )
    return {"stored": stored, "updated": updated}


async def get_landscape_objects(
    ctx: ContextEnvelope,
    platform: Optional[str] = None,
    object_type: Optional[str] = None,
    layer: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Query landscape_objects scoped by customer_id + project_id.

    Optional filters: platform, object_type, layer, text search (q matches
    object_name and technical_name, case-insensitive).
    """
    conn = await _get_conn()
    try:
        conditions: list[str] = ["customer_id = $1"]
        params: list[Any] = [ctx.customer_id]
        idx = 2

        if ctx.project_id is not None:
            conditions.append(f"project_id = ${idx}")
            params.append(ctx.project_id)
            idx += 1

        if platform is not None:
            conditions.append(f"platform = ${idx}")
            params.append(platform)
            idx += 1

        if object_type is not None:
            conditions.append(f"object_type = ${idx}")
            params.append(object_type)
            idx += 1

        if layer is not None:
            conditions.append(f"layer = ${idx}")
            params.append(layer)
            idx += 1

        if q is not None:
            conditions.append(f"(object_name ILIKE '%' || ${idx} || '%' OR technical_name ILIKE '%' || ${idx} || '%')")
            params.append(q)
            idx += 1

        where = " AND ".join(conditions)
        params.extend([limit, offset])
        rows = await conn.fetch(
            f"""
            SELECT id, customer_id, project_id, platform, object_type,
                   object_name, technical_name, layer, metadata,
                   documentation, dependencies, last_scanned, created_at
            FROM landscape_objects
            WHERE {where}
            ORDER BY platform, object_type, object_name
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *params,
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


async def get_landscape_object(object_id: str) -> Optional[dict]:
    """Fetch a single landscape_object by its UUID primary key."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT id, customer_id, project_id, platform, object_type,
                   object_name, technical_name, layer, metadata,
                   documentation, dependencies, last_scanned, created_at
            FROM landscape_objects
            WHERE id = $1
            """,
            UUID(object_id),
        )
        return _row_to_dict(row) if row else None
    finally:
        await conn.close()


async def get_landscape_stats(ctx: ContextEnvelope) -> dict:
    """Return object counts grouped by platform, object_type, and layer."""
    conn = await _get_conn()
    try:
        conditions: list[str] = ["customer_id = $1"]
        params: list[Any] = [ctx.customer_id]
        if ctx.project_id is not None:
            conditions.append("project_id = $2")
            params.append(ctx.project_id)

        where = " AND ".join(conditions)

        by_platform = await conn.fetch(
            f"SELECT platform, COUNT(*) AS cnt FROM landscape_objects WHERE {where} GROUP BY platform",
            *params,
        )
        by_type = await conn.fetch(
            f"SELECT object_type, COUNT(*) AS cnt FROM landscape_objects WHERE {where} GROUP BY object_type",
            *params,
        )
        by_layer = await conn.fetch(
            f"SELECT layer, COUNT(*) AS cnt FROM landscape_objects WHERE {where} GROUP BY layer",
            *params,
        )
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM landscape_objects WHERE {where}",
            *params,
        )

        return {
            "total": int(total or 0),
            "by_platform": {r["platform"]: int(r["cnt"]) for r in by_platform},
            "by_object_type": {r["object_type"]: int(r["cnt"]) for r in by_type},
            "by_layer": {(r["layer"] or "unknown"): int(r["cnt"]) for r in by_layer},
        }
    finally:
        await conn.close()


async def delete_landscape_objects(
    ctx: ContextEnvelope,
    platform: Optional[str] = None,
) -> int:
    """Delete landscape_objects for this customer/project scope.

    If platform is given, only objects for that platform are deleted.
    Returns the number of rows deleted.
    """
    conn = await _get_conn()
    try:
        conditions: list[str] = ["customer_id = $1"]
        params: list[Any] = [ctx.customer_id]
        idx = 2

        if ctx.project_id is not None:
            conditions.append(f"project_id = ${idx}")
            params.append(ctx.project_id)
            idx += 1

        if platform is not None:
            conditions.append(f"platform = ${idx}")
            params.append(platform)
            idx += 1

        where = " AND ".join(conditions)
        result = await conn.execute(
            f"DELETE FROM landscape_objects WHERE {where}",
            *params,
        )
        # asyncpg returns "DELETE N" string
        count = int(result.split()[-1]) if result else 0
        logger.info(
            "landscape_store: deleted=%d customer=%s project=%s platform=%s",
            count,
            ctx.customer_id,
            ctx.project_id,
            platform,
        )
        return count
    finally:
        await conn.close()
