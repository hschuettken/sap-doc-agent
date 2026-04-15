"""Async PostgreSQL CRUD for scanner base tables."""

from __future__ import annotations

import json
import os
from typing import Optional

import asyncpg


async def _get_conn():
    db_url = os.environ.get("DATABASE_URL", "")
    url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


async def ensure_tables() -> None:
    """Create scanner tables if they don't exist (idempotent)."""
    conn = await _get_conn()
    try:
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS scanned_objects_v1 (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            scan_id VARCHAR(255) NOT NULL,
            object_id VARCHAR(255) NOT NULL,
            object_type VARCHAR(50) NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT DEFAULT '',
            package VARCHAR(255) DEFAULT '',
            owner VARCHAR(255) DEFAULT '',
            source_system VARCHAR(255) DEFAULT '',
            technical_name VARCHAR(255) DEFAULT '',
            layer VARCHAR(100) DEFAULT '',
            source_code TEXT DEFAULT '',
            metadata JSONB DEFAULT '{}',
            content_hash VARCHAR(64),
            scanned_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(scan_id, object_id)
        )
        """)
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS dependencies_v1 (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            scan_id VARCHAR(255) NOT NULL,
            source_id VARCHAR(255) NOT NULL,
            target_id VARCHAR(255) NOT NULL,
            dependency_type VARCHAR(50) NOT NULL,
            metadata JSONB DEFAULT '{}'
        )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_scanned_objects_scan_id ON scanned_objects_v1(scan_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_scanned_objects_type ON scanned_objects_v1(object_type)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_scan_id ON dependencies_v1(scan_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_source ON dependencies_v1(source_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_dependencies_target ON dependencies_v1(target_id)")
    finally:
        await conn.close()


async def upsert_scanned_object(scan_id: str, obj: dict) -> None:
    """Upsert a scanned object. obj keys match ScannedObject fields."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """INSERT INTO scanned_objects_v1
               (scan_id, object_id, object_type, name, description, package, owner,
                source_system, technical_name, layer, source_code, metadata, content_hash, scanned_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13,
                       COALESCE($14::timestamptz, NOW()))
               ON CONFLICT (scan_id, object_id) DO UPDATE SET
                   object_type = EXCLUDED.object_type,
                   name = EXCLUDED.name,
                   description = EXCLUDED.description,
                   package = EXCLUDED.package,
                   owner = EXCLUDED.owner,
                   source_system = EXCLUDED.source_system,
                   technical_name = EXCLUDED.technical_name,
                   layer = EXCLUDED.layer,
                   source_code = EXCLUDED.source_code,
                   metadata = EXCLUDED.metadata,
                   content_hash = EXCLUDED.content_hash,
                   scanned_at = EXCLUDED.scanned_at""",
            scan_id,
            obj["object_id"],
            obj["object_type"],
            obj["name"],
            obj.get("description", ""),
            obj.get("package", ""),
            obj.get("owner", ""),
            obj.get("source_system", ""),
            obj.get("technical_name", ""),
            obj.get("layer", ""),
            obj.get("source_code", ""),
            json.dumps(obj.get("metadata", {})),
            obj.get("content_hash"),
            obj.get("scanned_at"),
        )
    finally:
        await conn.close()


async def upsert_dependency(scan_id: str, dep: dict) -> None:
    """Insert a dependency."""
    conn = await _get_conn()
    try:
        await conn.execute(
            """INSERT INTO dependencies_v1
               (scan_id, source_id, target_id, dependency_type, metadata)
               VALUES ($1, $2, $3, $4, $5::jsonb)""",
            scan_id,
            dep["source_id"],
            dep["target_id"],
            dep["dependency_type"],
            json.dumps(dep.get("metadata", {})),
        )
    finally:
        await conn.close()


async def save_scan_result(scan_id: str, objects: list[dict], dependencies: list[dict]) -> None:
    """Bulk save: delete old data for scan_id, insert new. Uses a transaction."""
    conn = await _get_conn()
    try:
        async with conn.transaction():
            await conn.execute("DELETE FROM dependencies_v1 WHERE scan_id = $1", scan_id)
            await conn.execute("DELETE FROM scanned_objects_v1 WHERE scan_id = $1", scan_id)
            for obj in objects:
                await conn.execute(
                    """INSERT INTO scanned_objects_v1
                       (scan_id, object_id, object_type, name, description, package, owner,
                        source_system, technical_name, layer, source_code, metadata, content_hash, scanned_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13,
                               COALESCE($14::timestamptz, NOW()))""",
                    scan_id,
                    obj["object_id"],
                    obj["object_type"],
                    obj["name"],
                    obj.get("description", ""),
                    obj.get("package", ""),
                    obj.get("owner", ""),
                    obj.get("source_system", ""),
                    obj.get("technical_name", ""),
                    obj.get("layer", ""),
                    obj.get("source_code", ""),
                    json.dumps(obj.get("metadata", {})),
                    obj.get("content_hash"),
                    obj.get("scanned_at"),
                )
            for dep in dependencies:
                await conn.execute(
                    """INSERT INTO dependencies_v1
                       (scan_id, source_id, target_id, dependency_type, metadata)
                       VALUES ($1, $2, $3, $4, $5::jsonb)""",
                    scan_id,
                    dep["source_id"],
                    dep["target_id"],
                    dep["dependency_type"],
                    json.dumps(dep.get("metadata", {})),
                )
    finally:
        await conn.close()


async def get_latest_scan_id() -> Optional[str]:
    """Get the most recent scan_id."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT scan_id FROM scanned_objects_v1 ORDER BY scanned_at DESC LIMIT 1")
        return row["scan_id"] if row else None
    finally:
        await conn.close()


async def list_objects(
    scan_id: Optional[str] = None,
    object_type: Optional[str] = None,
    layer: Optional[str] = None,
    q: Optional[str] = None,
) -> list[dict]:
    """List objects with optional filters. If no scan_id, uses the latest scan."""
    conn = await _get_conn()
    try:
        if scan_id is None:
            scan_id = await _get_latest_scan_id_conn(conn)
        if scan_id is None:
            return []

        conditions = ["scan_id = $1"]
        params: list = [scan_id]
        idx = 2

        if object_type:
            conditions.append(f"object_type = ${idx}")
            params.append(object_type)
            idx += 1
        if layer:
            conditions.append(f"layer = ${idx}")
            params.append(layer)
            idx += 1
        if q:
            conditions.append(f"(name ILIKE '%' || ${idx} || '%' OR object_id ILIKE '%' || ${idx} || '%')")
            params.append(q)
            idx += 1

        where = " AND ".join(conditions)
        rows = await conn.fetch(
            f"SELECT * FROM scanned_objects_v1 WHERE {where} ORDER BY name",
            *params,
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


async def get_object(object_id: str) -> Optional[dict]:
    """Get single object by object_id (from latest scan)."""
    conn = await _get_conn()
    try:
        scan_id = await _get_latest_scan_id_conn(conn)
        if scan_id is None:
            row = await conn.fetchrow(
                "SELECT * FROM scanned_objects_v1 WHERE object_id = $1 ORDER BY scanned_at DESC LIMIT 1",
                object_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM scanned_objects_v1 WHERE scan_id = $1 AND object_id = $2",
                scan_id,
                object_id,
            )
        return _row_to_dict(row) if row else None
    finally:
        await conn.close()


async def get_graph_data(scan_id: Optional[str] = None) -> dict:
    """Return {nodes: [...], edges: [...]} from DB. If no scan_id, uses latest."""
    conn = await _get_conn()
    try:
        if scan_id is None:
            scan_id = await _get_latest_scan_id_conn(conn)
        if scan_id is None:
            return {"nodes": [], "edges": []}

        obj_rows = await conn.fetch(
            "SELECT object_id, name, object_type, source_system, layer, package "
            "FROM scanned_objects_v1 WHERE scan_id = $1",
            scan_id,
        )
        dep_rows = await conn.fetch(
            "SELECT source_id, target_id, dependency_type FROM dependencies_v1 WHERE scan_id = $1",
            scan_id,
        )
        return {
            "nodes": [
                {
                    "id": r["object_id"],
                    "name": r["name"],
                    "type": r["object_type"],
                    "source_system": r["source_system"],
                    "layer": r["layer"],
                    "package": r["package"],
                }
                for r in obj_rows
            ],
            "edges": [
                {
                    "source": r["source_id"],
                    "target": r["target_id"],
                    "type": r["dependency_type"],
                }
                for r in dep_rows
            ],
        }
    finally:
        await conn.close()


async def get_object_count() -> int:
    """Count total objects in the latest scan."""
    conn = await _get_conn()
    try:
        scan_id = await _get_latest_scan_id_conn(conn)
        if scan_id is None:
            return 0
        row = await conn.fetchrow("SELECT COUNT(*) AS cnt FROM scanned_objects_v1 WHERE scan_id = $1", scan_id)
        return int(row["cnt"])
    finally:
        await conn.close()


# --- Internal helpers ---


async def _get_latest_scan_id_conn(conn) -> Optional[str]:
    """Get the most recent scan_id using an existing connection."""
    row = await conn.fetchrow("SELECT scan_id FROM scanned_objects_v1 ORDER BY scanned_at DESC LIMIT 1")
    return row["scan_id"] if row else None


def _row_to_dict(row) -> dict:
    """Convert asyncpg Record to plain dict, serializing special types."""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif hasattr(v, "hex") and not isinstance(v, (str, bytes)):
            d[k] = str(v)
    return d
