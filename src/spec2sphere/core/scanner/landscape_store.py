"""Landscape store — persist scanner results into landscape_objects table.

Tenant-scoped by (customer_id, project_id). Upserts on
(customer_id, project_id, platform, technical_name) with fallback to
object_name when technical_name is absent.

Integrates:
- field_extractor: structured field metadata extracted after each upsert
- version_tracker: scan_run lifecycle + object_history snapshots before updates
"""
# ============================================================================
# DATA PRIVACY POLICY
# ============================================================================
# This store persists METADATA ONLY from connected SAP systems:
#   STORED: Object names, technical names, SQL view definitions, column
#           names and types, dependency graphs, layer assignments,
#           transformation logic, ABAP source code structure.
#   NEVER STORED: Actual transactional data, row values, aggregated
#                 business figures (revenue, quantities, etc.), personally
#                 identifiable information (PII), or any SELECT results.
#
# The scanner extracts STRUCTURE, not DATA. If a view definition contains
# hardcoded values in WHERE clauses or CASE expressions, those are part
# of the structural logic and are stored.
# ============================================================================

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
# Data privacy guard
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402 — kept here to avoid polluting top-level imports


def _validate_no_transactional_data(content: str, object_name: str) -> None:
    """Log a warning if content looks like it contains actual data values.

    This is a heuristic guard only — not a guarantee. The scanner should
    never receive SELECT query results, but this catches obvious accidents
    (e.g. a developer accidentally passing row data instead of DDL).

    Patterns checked:
    - Multiple standalone integers on the same line (tabular row pattern)
    - Pipe-delimited or tab-delimited columnar data blocks
    - CSV-like lines with 5+ comma-separated numeric tokens
    """
    if not content:
        return

    # Pattern 1: line with 4+ standalone numbers (e.g. exported table rows)
    number_row = _re.compile(r"^\s*(?:\d[\d.,]*\s+){4,}\d[\d.,]*\s*$", _re.MULTILINE)
    if number_row.search(content):
        logger.warning(
            "landscape_store: possible transactional data detected in %s "
            "(multiple numeric columns on a single line); only structural "
            "metadata should be stored here",
            object_name,
        )
        return

    # Pattern 2: pipe-delimited rows that look like table dumps
    pipe_row = _re.compile(r"^\s*\|(?:[^|]+\|){4,}\s*$", _re.MULTILINE)
    if pipe_row.search(content):
        logger.warning(
            "landscape_store: possible tabular data detected in %s "
            "(pipe-delimited columns); verify this is structural content, not row data",
            object_name,
        )
        return

    # Pattern 3: CSV lines with 5+ numeric tokens
    csv_num_line = _re.compile(r"^(?:\"?[\d.,]+\"?\s*,\s*){5,}\"?[\d.,]+\"?\s*$", _re.MULTILINE)
    if csv_num_line.search(content):
        logger.warning(
            "landscape_store: possible CSV row data detected in %s "
            "(5+ comma-separated numeric values); only DDL / ABAP structure should be stored",
            object_name,
        )


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

    Uses SHA-256 content hashing to skip rows whose content has not changed.

    Creates a scan_run record at the start and completes it at the end.
    Snapshots objects before they are updated (version history).
    Extracts structured fields after each upsert.

    Returns {"stored": int, "updated": int, "unchanged": int, "scan_run_id": str}.
    """
    # Lazy imports to avoid circular dependency at module load time.
    from spec2sphere.core.scanner.field_extractor import extract_fields  # noqa: PLC0415
    from spec2sphere.core.scanner.version_tracker import (  # noqa: PLC0415
        complete_scan_run,
        create_scan_run,
        fail_scan_run,
        snapshot_object,
    )

    if not scan_result.objects:
        return {"stored": 0, "updated": 0, "unchanged": 0, "scan_run_id": None}

    # Create the scan run record
    run_id = await create_scan_run(
        customer_id=ctx.customer_id,
        project_id=ctx.project_id,
        scanner_type=platform,
        scan_config={"platform": platform, "object_count": len(scan_result.objects)},
    )

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
    unchanged = 0
    fields_extracted = 0
    now = datetime.now(timezone.utc)

    try:
        async with conn.transaction():
            for obj in scan_result.objects:
                tech_name = obj.technical_name or obj.object_id
                obj_name = obj.name or tech_name
                deps_json = json.dumps(dep_map.get(obj.object_id, []))
                content_hash = obj.compute_hash()

                # Heuristic guard: warn if content looks like transactional data
                _validate_no_transactional_data(obj.description or obj.source_code or "", tech_name)

                # Check if row already exists for this scope + identity
                existing = await conn.fetchrow(
                    """
                    SELECT id, content_hash FROM landscape_objects
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
                    # Skip the upsert entirely if content has not changed
                    if existing["content_hash"] == content_hash:
                        unchanged += 1
                        continue

                    # Snapshot current state before overwriting
                    try:
                        await snapshot_object(
                            conn,
                            existing["id"],
                            run_id,
                            change_type="updated",
                        )
                    except Exception as snap_exc:  # noqa: BLE001
                        logger.warning(
                            "landscape_store: snapshot failed for %s: %s",
                            existing["id"],
                            snap_exc,
                        )

                    await conn.execute(
                        """
                        UPDATE landscape_objects SET
                            object_type    = $1,
                            object_name    = $2,
                            technical_name = $3,
                            layer          = $4,
                            metadata       = $5::jsonb,
                            documentation  = $6,
                            dependencies   = $7::jsonb,
                            last_scanned   = $8,
                            content_hash   = $9,
                            version_number = COALESCE(version_number, 1) + 1,
                            last_scan_run_id = $11
                        WHERE id = $10
                        """,
                        obj.object_type.value,
                        obj_name,
                        tech_name,
                        obj.layer or None,
                        json.dumps(obj.metadata),
                        obj.description or obj.source_code or None,
                        deps_json,
                        now,
                        content_hash,
                        existing["id"],
                        run_id,
                    )
                    landscape_object_id = existing["id"]
                    updated += 1
                else:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO landscape_objects
                            (customer_id, project_id, platform, object_type,
                             object_name, technical_name, layer, metadata,
                             documentation, dependencies, last_scanned,
                             content_hash, first_seen_at, last_scan_run_id,
                             version_number)
                        VALUES
                            ($1, $2, $3, $4, $5, $6, $7, $8::jsonb,
                             $9, $10::jsonb, $11, $12, $11, $13, 1)
                        RETURNING id
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
                        content_hash,
                        run_id,
                    )
                    landscape_object_id = row["id"]
                    stored += 1

                # Extract and store structured fields for this object
                try:
                    obj_dict = {
                        "platform": platform,
                        "object_type": obj.object_type.value,
                        "metadata": obj.metadata,
                        "documentation": obj.description or obj.source_code or "",
                    }
                    fields, rules = extract_fields(obj_dict)
                    if fields:
                        await store_object_fields(landscape_object_id, fields, run_id, conn)
                        fields_extracted += len(fields)
                    if rules:
                        await store_transformation_rules(landscape_object_id, rules, run_id, conn)
                except Exception as fe_exc:  # noqa: BLE001
                    logger.warning(
                        "landscape_store: field extraction failed for %s: %s",
                        landscape_object_id,
                        fe_exc,
                    )

    except Exception as exc:
        try:
            await fail_scan_run(run_id, str(exc))
        except Exception as fail_exc:  # noqa: BLE001
            logger.warning("landscape_store: failed to mark scan_run %s as failed: %s", run_id, fail_exc)
        raise
    finally:
        await conn.close()

    stats = {
        "stored": stored,
        "updated": updated,
        "unchanged": unchanged,
        "fields_extracted": fields_extracted,
    }
    try:
        await complete_scan_run(
            run_id,
            stats=stats,
            change_summary={"stored": stored, "updated": updated, "unchanged": unchanged},
        )
    except Exception as complete_exc:  # noqa: BLE001
        # Non-fatal: scan data is already committed. Log and continue.
        logger.warning("landscape_store: failed to mark scan_run %s as completed: %s", run_id, complete_exc)

    logger.info(
        "landscape_store: stored=%d updated=%d unchanged=%d fields=%d platform=%s customer=%s project=%s run=%s",
        stored,
        updated,
        unchanged,
        fields_extracted,
        platform,
        ctx.customer_id,
        ctx.project_id,
        run_id,
    )
    return {
        "stored": stored,
        "updated": updated,
        "unchanged": unchanged,
        "fields_extracted": fields_extracted,
        "scan_run_id": str(run_id),
    }


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


# ---------------------------------------------------------------------------
# Field storage
# ---------------------------------------------------------------------------


async def store_object_fields(
    landscape_object_id: UUID,
    fields: list[dict],
    scan_run_id: Optional[UUID],
    conn: asyncpg.Connection,
) -> None:
    """Upsert fields for a landscape object into the object_fields table.

    object_fields schema expected:
        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid()
        landscape_object_id  UUID NOT NULL REFERENCES landscape_objects(id)
        scan_run_id          UUID REFERENCES scan_runs(id)
        field_name           TEXT NOT NULL
        field_ordinal        INT
        data_type            TEXT
        expression           TEXT
        source_object        TEXT
        source_field         TEXT
        is_key               BOOLEAN NOT NULL DEFAULT false
        is_calculated        BOOLEAN NOT NULL DEFAULT false
        is_aggregated        BOOLEAN NOT NULL DEFAULT false
        aggregation_type     TEXT
        field_role           TEXT
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()

    Upserts on (landscape_object_id, field_name).
    Uses the provided connection so this can participate in an outer transaction.
    """
    for field in fields:
        await conn.execute(
            """
            INSERT INTO object_fields
                (landscape_object_id, scan_run_id, field_name, field_ordinal,
                 data_type, expression, source_object, source_field,
                 is_key, is_calculated, is_aggregated, aggregation_type,
                 field_role)
            VALUES
                ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (landscape_object_id, field_name)
            DO UPDATE SET
                scan_run_id      = EXCLUDED.scan_run_id,
                field_ordinal    = EXCLUDED.field_ordinal,
                data_type        = EXCLUDED.data_type,
                expression       = EXCLUDED.expression,
                source_object    = EXCLUDED.source_object,
                source_field     = EXCLUDED.source_field,
                is_key           = EXCLUDED.is_key,
                is_calculated    = EXCLUDED.is_calculated,
                is_aggregated    = EXCLUDED.is_aggregated,
                aggregation_type = EXCLUDED.aggregation_type,
                field_role       = EXCLUDED.field_role
            """,
            landscape_object_id,
            scan_run_id,
            field.get("field_name"),
            field.get("field_ordinal"),
            field.get("data_type"),
            field.get("expression"),
            field.get("source_object"),
            field.get("source_field"),
            bool(field.get("is_key", False)),
            bool(field.get("is_calculated", False)),
            bool(field.get("is_aggregated", False)),
            field.get("aggregation_type"),
            field.get("field_role"),
        )


async def store_transformation_rules(
    landscape_object_id: UUID,
    rules: list[dict],
    scan_run_id: Optional[UUID],
    conn: asyncpg.Connection,
) -> None:
    """Insert transformation rules for a landscape object.

    Matches the actual migration 009 schema:
        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid()
        landscape_object_id  UUID NOT NULL REFERENCES landscape_objects(id)
        scan_run_id          UUID REFERENCES scan_runs(id)
        source_object        TEXT NOT NULL
        target_object        TEXT NOT NULL
        source_field         TEXT
        target_field         TEXT NOT NULL
        rule_type            TEXT
        rule_expression      TEXT
        routine_name         TEXT
        routine_code         TEXT
        metadata             JSONB DEFAULT '{}'

    There is no unique constraint on this table in migration 009, so we do a
    plain INSERT rather than an upsert.  Callers should clear old rules before
    calling this function if idempotency is required.

    Rule dict keys accepted (from extract_bw_fields / field_extractor):
        source_field, target_field, rule_type, formula (→ rule_expression),
        description (→ metadata.description), source_object, target_object.
    """
    # Delete existing rules for this object before re-inserting so we don't
    # accumulate duplicate rows on every rescan (no unique index on this table).
    await conn.execute(
        "DELETE FROM transformation_rules WHERE landscape_object_id = $1",
        landscape_object_id,
    )

    for rule in rules:
        source_field = rule.get("source_field") or ""
        target_field = rule.get("target_field") or ""
        source_object = rule.get("source_object") or ""
        target_object = rule.get("target_object") or ""

        # target_field and source/target objects are NOT NULL — skip invalid rows
        if not target_field or not source_object or not target_object:
            logger.debug("landscape_store: skipping transformation rule with missing required fields: %s", rule)
            continue

        # Map legacy field names to migration schema columns
        rule_expression = rule.get("formula") or rule.get("rule_expression") or None
        routine_name = rule.get("routine_name") or None
        routine_code = rule.get("routine_code") or None

        # Pack remaining metadata (e.g. description) into the metadata JSONB
        extra: dict = {}
        if rule.get("description"):
            extra["description"] = rule["description"]
        if rule.get("rule_sequence") is not None:
            extra["rule_sequence"] = rule["rule_sequence"]

        await conn.execute(
            """
            INSERT INTO transformation_rules
                (landscape_object_id, scan_run_id,
                 source_object, target_object,
                 source_field, target_field,
                 rule_type, rule_expression,
                 routine_name, routine_code, metadata)
            VALUES
                ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
            """,
            landscape_object_id,
            scan_run_id,
            source_object,
            target_object,
            source_field or None,
            target_field,
            rule.get("rule_type") or "direct",
            rule_expression,
            routine_name,
            routine_code,
            json.dumps(extra) if extra else "{}",
        )


async def get_object_fields(landscape_object_id: str) -> list[dict]:
    """Get all fields for a landscape object, ordered by field_ordinal."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, landscape_object_id, scan_run_id, field_name,
                   field_ordinal, data_type, expression, source_object,
                   source_field, is_key, is_calculated, is_aggregated,
                   aggregation_type, field_role, updated_at
            FROM object_fields
            WHERE landscape_object_id = $1
            ORDER BY field_ordinal NULLS LAST, field_name
            """,
            UUID(landscape_object_id),
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


async def search_fields(
    ctx: ContextEnvelope,
    field_name: Optional[str] = None,
    data_type: Optional[str] = None,
    source_object: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Search fields across all objects in a customer/project scope.

    Joins object_fields -> landscape_objects for tenant scoping.
    All filter parameters are case-insensitive partial matches.
    """
    conn = await _get_conn()
    try:
        conditions: list[str] = ["lo.customer_id = $1"]
        params: list[Any] = [ctx.customer_id]
        idx = 2

        if ctx.project_id is not None:
            conditions.append(f"lo.project_id = ${idx}")
            params.append(ctx.project_id)
            idx += 1

        if field_name is not None:
            conditions.append(f"of.field_name ILIKE '%' || ${idx} || '%'")
            params.append(field_name)
            idx += 1

        if data_type is not None:
            conditions.append(f"of.data_type ILIKE '%' || ${idx} || '%'")
            params.append(data_type)
            idx += 1

        if source_object is not None:
            conditions.append(f"of.source_object ILIKE '%' || ${idx} || '%'")
            params.append(source_object)
            idx += 1

        where = " AND ".join(conditions)
        params.append(limit)

        rows = await conn.fetch(
            f"""
            SELECT of.id, of.landscape_object_id, of.field_name,
                   of.field_ordinal, of.data_type, of.expression,
                   of.source_object, of.source_field, of.is_key,
                   of.is_calculated, of.is_aggregated, of.aggregation_type,
                   of.field_role, of.updated_at,
                   lo.object_name, lo.technical_name, lo.platform, lo.object_type
            FROM object_fields of
            JOIN landscape_objects lo ON lo.id = of.landscape_object_id
            WHERE {where}
            ORDER BY lo.platform, lo.object_name, of.field_ordinal NULLS LAST
            LIMIT ${idx}
            """,
            *params,
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()
