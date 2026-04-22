"""Enhancement library export/import — JSON round-trip, Pydantic-validated.

Export produces a ``{"version": "1.0", "enhancements": [...]}`` bundle.
Import supports three modes:
  - merge    : upsert by (name, version); existing rows updated
  - replace  : delete all rows for the customer, then insert fresh
  - draftify : import all as "draft" status regardless of source status
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import asyncpg
from pydantic import ValidationError

from .config import EnhancementConfig
from .settings import postgres_dsn

LIBRARY_VERSION = "1.0"


async def export_library(customer: str | None = None) -> dict:
    """Dump all enhancements for *customer* (or all, if None) as a portable bundle."""
    conn = await asyncpg.connect(postgres_dsn())
    try:
        if customer:
            rows = await conn.fetch(
                "SELECT name, kind, version, status, config "
                "FROM dsp_ai.enhancements WHERE customer = $1 ORDER BY name",
                customer,
            )
        else:
            rows = await conn.fetch(
                "SELECT name, kind, version, status, config "
                "FROM dsp_ai.enhancements ORDER BY name"
            )
    finally:
        await conn.close()

    return {
        "version": LIBRARY_VERSION,
        "exported_at": dt.datetime.utcnow().isoformat() + "Z",
        "enhancements": [
            {
                "name": r["name"],
                "kind": r["kind"],
                "version": r["version"],
                "status": r["status"],
                "config": r["config"] if isinstance(r["config"], dict) else json.loads(r["config"]),
            }
            for r in rows
        ],
    }


async def import_library(
    blob: dict,
    customer: str,
    mode: str = "merge",
    author: str = "import",
) -> dict:
    """Import an enhancement library bundle.

    Returns ``{"imported": int, "mode": str, "customer": str}``.
    Raises ``ValueError`` for schema/version errors.
    """
    if blob.get("version") != LIBRARY_VERSION:
        raise ValueError(f"unsupported library version: {blob.get('version')!r}")

    enhancements = blob.get("enhancements")
    if not isinstance(enhancements, list):
        raise ValueError("enhancements must be a list")

    for e in enhancements:
        try:
            EnhancementConfig.model_validate(e["config"])
        except (ValidationError, KeyError) as exc:
            raise ValueError(f"invalid config for {e.get('name')!r}: {exc}") from exc

    conn = await asyncpg.connect(postgres_dsn())
    try:
        await conn.execute("SELECT set_config('dspai.customer', $1, false)", customer)

        if mode == "replace":
            await conn.execute(
                "DELETE FROM dsp_ai.enhancements WHERE customer = $1", customer
            )

        imported = 0
        for e in enhancements:
            new_id = str(uuid.uuid4())
            status = "draft" if mode == "draftify" else e.get("status", "draft")
            await conn.execute(
                """
                INSERT INTO dsp_ai.enhancements
                    (id, name, kind, version, status, config, author, customer)
                VALUES ($1::uuid, $2, $3, $4, $5, $6::jsonb, $7, $8)
                ON CONFLICT (name, version)
                DO UPDATE SET
                    config = EXCLUDED.config,
                    status = EXCLUDED.status,
                    author = EXCLUDED.author,
                    updated_at = NOW()
                """,
                new_id,
                e["name"],
                e["kind"],
                e["version"],
                status,
                json.dumps(e["config"]),
                author,
                customer,
            )
            imported += 1
    finally:
        await conn.close()

    return {"imported": imported, "mode": mode, "customer": customer}
