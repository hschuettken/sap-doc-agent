"""Stage 1: load enhancement config from Postgres."""

from __future__ import annotations

import json

from ..config import Enhancement, EnhancementConfig
from ..db import get_conn


async def resolve(enhancement_id: str) -> Enhancement:
    async with get_conn() as conn:
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
