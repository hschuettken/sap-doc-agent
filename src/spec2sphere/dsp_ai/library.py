"""Enhancement library export/import — JSON round-trip, Pydantic-validated.

The exported blob is portable: each enhancement carries its full
EnhancementConfig (which validates on import) so a library JSON can be
carried from one customer tenant to another. On import, the current
CUSTOMER env var determines the target tenant; pre-existing (name,
version) rows are upserted by default, unless mode=replace (clears
first) or mode=draftify (imports all as draft regardless of source
status).
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Literal

from .config import EnhancementConfig
from .db import current_customer, get_conn

Mode = Literal["merge", "replace", "draftify"]

LIBRARY_VERSION = "1.0"


async def export_library(customer: str | None = None) -> dict:
    """Export all enhancements for ``customer`` (defaults to current CUSTOMER env)."""
    target = current_customer(customer)
    async with get_conn(customer=target) as conn:
        rows = await conn.fetch(
            "SELECT name, kind, version, status, config FROM dsp_ai.enhancements ORDER BY name, version"
        )
    enhancements = []
    for r in rows:
        cfg = r["config"]
        if isinstance(cfg, str):
            cfg = json.loads(cfg)
        enhancements.append(
            {
                "name": r["name"],
                "kind": r["kind"],
                "version": r["version"],
                "status": r["status"],
                "config": cfg,
            }
        )
    return {
        "version": LIBRARY_VERSION,
        "exported_at": dt.datetime.now(dt.UTC).isoformat().replace("+00:00", "Z"),
        "customer": target,
        "enhancements": enhancements,
    }


async def import_library(
    blob: dict, *, customer: str | None = None, mode: Mode = "merge", author: str = "import"
) -> dict:
    """Import a library blob into ``customer`` tenant (defaults to current)."""
    if blob.get("version") != LIBRARY_VERSION:
        raise ValueError(f"unsupported library version: {blob.get('version')!r} (expected {LIBRARY_VERSION})")

    entries = blob.get("enhancements", [])
    if not isinstance(entries, list):
        raise ValueError("library blob 'enhancements' must be a list")

    # Validate everything BEFORE touching the DB
    for e in entries:
        EnhancementConfig.model_validate(e["config"])

    target = current_customer(customer)
    imported = 0
    updated = 0
    async with get_conn(customer=target) as conn:
        async with conn.transaction():
            if mode == "replace":
                await conn.execute("DELETE FROM dsp_ai.enhancements WHERE customer = $1", target)
            for e in entries:
                status = "draft" if mode == "draftify" else (e.get("status") or "draft")
                existed = await conn.fetchval(
                    "SELECT id FROM dsp_ai.enhancements WHERE name = $1 AND version = $2 AND customer = $3",
                    e["name"],
                    int(e["version"]),
                    target,
                )
                if existed:
                    await conn.execute(
                        """
                        UPDATE dsp_ai.enhancements
                           SET kind = $2, status = $3, config = $4::jsonb, updated_at = NOW()
                         WHERE id = $1::uuid
                        """,
                        existed,
                        e["kind"],
                        status,
                        json.dumps(e["config"]),
                    )
                    updated += 1
                else:
                    await conn.execute(
                        """
                        INSERT INTO dsp_ai.enhancements
                            (id, name, kind, version, status, config, author, customer)
                        VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7, $8)
                        """,
                        str(uuid.uuid4()),
                        e["name"],
                        e["kind"],
                        int(e["version"]),
                        status,
                        json.dumps(e["config"]),
                        author,
                        target,
                    )
                    imported += 1
    return {"imported": imported, "updated": updated, "mode": mode, "customer": target, "total": len(entries)}
