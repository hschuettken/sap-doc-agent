"""Stage 1: load enhancement config from Postgres."""

from __future__ import annotations

import json

import asyncpg

from ..config import Enhancement, EnhancementConfig
from ..settings import postgres_dsn


async def resolve(enhancement_id: str) -> Enhancement:
    conn = await asyncpg.connect(postgres_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT id::text AS id, version, status, author, config FROM dsp_ai.enhancements WHERE id = $1",
            enhancement_id,
        )
        if row is None:
            raise LookupError(f"enhancement {enhancement_id} not found")
        raw_config = row["config"]
        return Enhancement(
            id=row["id"],
            version=row["version"],
            status=row["status"],
            author=row["author"],
            config=EnhancementConfig.model_validate(
                json.loads(raw_config) if isinstance(raw_config, str) else raw_config
            ),
        )
    finally:
        await conn.close()
