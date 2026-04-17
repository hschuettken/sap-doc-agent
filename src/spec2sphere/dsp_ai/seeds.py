"""Enhancement seed library — loads JSON templates into ``dsp_ai.enhancements``.

Used by:
- dsp-ai service startup — idempotent ensure_seeded() so fresh compose
  always has the Morning Brief draft available for the Studio.
- Setup wizard ai-seed endpoint — same helper, explicit trigger.
- `spec2sphere dsp-ai seed` CLI (Session B) — not wired yet.

Idempotent via the (name, version) UNIQUE constraint on the table.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import asyncpg

from .settings import postgres_dsn

logger = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).resolve().parents[3] / "templates" / "seeds"


async def load_seed_file(path: Path) -> dict:
    """Parse a seed JSON file from disk."""
    return json.loads(Path(path).read_text())


async def upsert_enhancement(config: dict, *, author: str = "system") -> str | None:
    """Insert ``config`` as a draft Enhancement. Returns the new id, or
    None if a row with that (name, version) already exists.
    """
    name = config["name"]
    kind = config["kind"]
    conn = await asyncpg.connect(postgres_dsn())
    try:
        existing = await conn.fetchval(
            "SELECT id::text FROM dsp_ai.enhancements WHERE name = $1 AND version = $2",
            name,
            1,
        )
        if existing:
            return None
        new_id = await conn.fetchval(
            "INSERT INTO dsp_ai.enhancements (name, kind, config, author) "
            "VALUES ($1, $2, $3::jsonb, $4) RETURNING id::text",
            name,
            kind,
            json.dumps(config),
            author,
        )
        return new_id
    finally:
        await conn.close()


async def ensure_morning_brief_seeded() -> str | None:
    """Idempotently seed the Morning Brief template. Returns id if newly
    created, None if it was already present."""
    path = SEEDS_DIR / "morning_brief_revenue.json"
    if not path.exists():
        logger.warning("Morning Brief seed not found at %s", path)
        return None
    config = await load_seed_file(path)
    new_id = await upsert_enhancement(config, author="setup_wizard")
    if new_id:
        logger.info("Seeded Morning Brief enhancement id=%s", new_id)
    return new_id
