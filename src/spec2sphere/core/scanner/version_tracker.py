"""Version tracker — manage scan_runs and object_history for landscape objects.

Uses the same asyncpg + _get_conn() pattern as landscape_store.py.
All public functions are async and manage their own connections unless
a connection is explicitly passed (for in-transaction operations).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional
from uuid import UUID

import asyncpg

# Re-use the connection helper from the sibling module to keep things DRY.
from spec2sphere.core.scanner.landscape_store import _get_conn, _row_to_dict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Scan run lifecycle
# ---------------------------------------------------------------------------


async def create_scan_run(
    customer_id: UUID,
    project_id: Optional[UUID],
    scanner_type: str,
    scan_config: Optional[dict] = None,
) -> UUID:
    """Create a new scan_run record and return its UUID.

    scan_runs schema expected:
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid()
        customer_id UUID NOT NULL
        project_id  UUID
        scanner_type TEXT NOT NULL
        scan_config  JSONB
        status      TEXT NOT NULL DEFAULT 'running'
        started_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        completed_at TIMESTAMPTZ
        stats       JSONB
        change_summary JSONB
    """
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO scan_runs
                (customer_id, project_id, scanner_type, scan_config, status, started_at)
            VALUES
                ($1, $2, $3, $4::jsonb, 'running', now())
            RETURNING id
            """,
            customer_id,
            project_id,
            scanner_type,
            json.dumps(scan_config or {}),
        )
        run_id: UUID = row["id"]
        logger.debug("version_tracker: created scan_run %s type=%s", run_id, scanner_type)
        return run_id
    finally:
        await conn.close()


async def complete_scan_run(
    run_id: UUID,
    stats: Optional[dict] = None,
    change_summary: Optional[dict] = None,
) -> None:
    """Mark a scan run as completed, recording stats and change summary."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            UPDATE scan_runs
            SET status         = 'completed',
                completed_at   = now(),
                stats          = $1::jsonb,
                change_summary = $2::jsonb
            WHERE id = $3
            """,
            json.dumps(stats or {}),
            json.dumps(change_summary or {}),
            run_id,
        )
        logger.debug("version_tracker: completed scan_run %s", run_id)
    finally:
        await conn.close()


async def fail_scan_run(run_id: UUID, error: str) -> None:
    """Mark a scan run as failed with an error message."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """
            UPDATE scan_runs
            SET status       = 'failed',
                completed_at = now(),
                stats        = jsonb_build_object('error', $1)
            WHERE id = $2
            """,
            error,
            run_id,
        )
        logger.debug("version_tracker: failed scan_run %s: %s", run_id, error)
    finally:
        await conn.close()


async def get_scan_runs(
    customer_id: UUID,
    project_id: Optional[UUID] = None,
    limit: int = 20,
) -> list[dict]:
    """List scan runs for a customer/project, newest first.

    Returns list of dicts with all scan_runs columns.
    """
    conn = await _get_conn()
    try:
        conditions = ["customer_id = $1"]
        params: list[Any] = [customer_id]
        idx = 2

        if project_id is not None:
            conditions.append(f"project_id = ${idx}")
            params.append(project_id)
            idx += 1

        params.extend([limit])
        where = " AND ".join(conditions)

        rows = await conn.fetch(
            f"""
            SELECT id, customer_id, project_id, scanner_type, scan_config,
                   status, started_at, completed_at, stats, change_summary
            FROM scan_runs
            WHERE {where}
            ORDER BY started_at DESC
            LIMIT ${idx}
            """,
            *params,
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Object version snapshots
# ---------------------------------------------------------------------------


async def snapshot_object(
    conn: asyncpg.Connection,
    landscape_object_id: UUID,
    scan_run_id: UUID,
    change_type: str,
    changes: Optional[dict] = None,
) -> None:
    """Take a version snapshot of an object before it is modified.

    Copies the current state of the object (plus its fields as a JSONB blob)
    into object_history with an auto-incremented version_number.

    object_history schema expected:
        id                   UUID PRIMARY KEY DEFAULT gen_random_uuid()
        landscape_object_id  UUID NOT NULL REFERENCES landscape_objects(id)
        scan_run_id          UUID REFERENCES scan_runs(id)
        version_number       INT NOT NULL
        change_type          TEXT NOT NULL   -- 'created' | 'updated' | 'deleted'
        changes              JSONB           -- field-level diff summary
        snapshot             JSONB NOT NULL  -- full object state at this version
        snapshotted_at       TIMESTAMPTZ NOT NULL DEFAULT now()
    """
    # Fetch current object state
    obj_row = await conn.fetchrow(
        """
        SELECT id, customer_id, project_id, platform, object_type,
               object_name, technical_name, layer, metadata,
               documentation, dependencies, last_scanned, content_hash
        FROM landscape_objects
        WHERE id = $1
        """,
        landscape_object_id,
    )
    if not obj_row:
        logger.warning("version_tracker: snapshot requested for unknown object %s", landscape_object_id)
        return

    # Fetch current fields to include in snapshot
    field_rows = await conn.fetch(
        """
        SELECT field_name, field_ordinal, data_type, expression,
               source_object, source_field, is_key, is_calculated,
               is_aggregated, aggregation_type, field_role
        FROM object_fields
        WHERE landscape_object_id = $1
        ORDER BY field_ordinal
        """,
        landscape_object_id,
    )

    snapshot = dict(obj_row)
    # Convert non-JSON-serialisable types
    for k, v in snapshot.items():
        if hasattr(v, "isoformat"):
            snapshot[k] = v.isoformat()
        elif isinstance(v, UUID):
            snapshot[k] = str(v)
        elif isinstance(v, (bytes, memoryview)):
            snapshot[k] = str(v)

    snapshot["fields"] = [dict(r) for r in field_rows]

    # Determine next version number
    max_version = await conn.fetchval(
        """
        SELECT COALESCE(MAX(version_number), 0)
        FROM object_history
        WHERE landscape_object_id = $1
        """,
        landscape_object_id,
    )
    next_version = int(max_version) + 1

    await conn.execute(
        """
        INSERT INTO object_history
            (landscape_object_id, scan_run_id, version_number, change_type, changes, snapshot)
        VALUES
            ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
        """,
        landscape_object_id,
        scan_run_id,
        next_version,
        change_type,
        json.dumps(changes or {}),
        json.dumps(snapshot, default=str),
    )
    logger.debug(
        "version_tracker: snapshot v%d for object %s (%s)",
        next_version,
        landscape_object_id,
        change_type,
    )


# ---------------------------------------------------------------------------
# History retrieval
# ---------------------------------------------------------------------------


async def get_object_history(
    landscape_object_id: UUID | str,
    limit: int = 20,
) -> list[dict]:
    """Get version history for an object, newest version first."""
    oid = UUID(landscape_object_id) if isinstance(landscape_object_id, str) else landscape_object_id
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, landscape_object_id, scan_run_id, version_number,
                   change_type, changes, snapshotted_at
            FROM object_history
            WHERE landscape_object_id = $1
            ORDER BY version_number DESC
            LIMIT $2
            """,
            oid,
            limit,
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


async def get_object_at_version(
    landscape_object_id: UUID | str,
    version_number: int,
) -> Optional[dict]:
    """Get an object's full state snapshot at a specific version number.

    Returns the snapshot JSONB (which includes fields) or None if not found.
    """
    oid = UUID(landscape_object_id) if isinstance(landscape_object_id, str) else landscape_object_id
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            SELECT snapshot, version_number, change_type, snapshotted_at, scan_run_id
            FROM object_history
            WHERE landscape_object_id = $1
              AND version_number = $2
            LIMIT 1
            """,
            oid,
            version_number,
        )
        if not row:
            return None
        result = _row_to_dict(row)
        # snapshot is JSONB; asyncpg may return string
        snap = result.get("snapshot")
        if isinstance(snap, str):
            import json as _json

            try:
                result["snapshot"] = _json.loads(snap)
            except Exception:  # noqa: BLE001
                pass
        return result
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Version diff
# ---------------------------------------------------------------------------


async def diff_versions(
    landscape_object_id: UUID | str,
    version_a: int,
    version_b: int,
) -> dict:
    """Compare two object versions and return a structured diff.

    Returns:
        {
            "object_changes": {field: {"old": ..., "new": ...}},
            "fields_added":   [...field dicts...],
            "fields_removed": [...field dicts...],
            "fields_modified": [{field_name, changes: {...}}]
        }
    """
    snap_a_rec = await get_object_at_version(landscape_object_id, version_a)
    snap_b_rec = await get_object_at_version(landscape_object_id, version_b)

    if not snap_a_rec or not snap_b_rec:
        missing = []
        if not snap_a_rec:
            missing.append(str(version_a))
        if not snap_b_rec:
            missing.append(str(version_b))
        return {"error": f"Version(s) not found: {', '.join(missing)}"}

    snap_a: dict = snap_a_rec.get("snapshot") or {}
    snap_b: dict = snap_b_rec.get("snapshot") or {}

    _SKIP_KEYS = frozenset(["fields", "last_scanned", "content_hash"])

    # --- Object-level diff ---
    object_changes: dict[str, dict] = {}
    all_keys = set(snap_a.keys()) | set(snap_b.keys())
    for key in all_keys:
        if key in _SKIP_KEYS:
            continue
        val_a = snap_a.get(key)
        val_b = snap_b.get(key)
        if val_a != val_b:
            object_changes[key] = {"old": val_a, "new": val_b}

    # --- Fields diff ---
    fields_a: list[dict] = snap_a.get("fields") or []
    fields_b: list[dict] = snap_b.get("fields") or []

    fields_a_map = {f["field_name"]: f for f in fields_a}
    fields_b_map = {f["field_name"]: f for f in fields_b}

    names_a = set(fields_a_map.keys())
    names_b = set(fields_b_map.keys())

    fields_added = [fields_b_map[n] for n in sorted(names_b - names_a)]
    fields_removed = [fields_a_map[n] for n in sorted(names_a - names_b)]

    fields_modified: list[dict] = []
    for name in sorted(names_a & names_b):
        fa = fields_a_map[name]
        fb = fields_b_map[name]
        col_changes = {
            k: {"old": fa.get(k), "new": fb.get(k)} for k in (set(fa.keys()) | set(fb.keys())) if fa.get(k) != fb.get(k)
        }
        if col_changes:
            fields_modified.append({"field_name": name, "changes": col_changes})

    return {
        "landscape_object_id": str(landscape_object_id),
        "version_a": version_a,
        "version_b": version_b,
        "object_changes": object_changes,
        "fields_added": fields_added,
        "fields_removed": fields_removed,
        "fields_modified": fields_modified,
    }
