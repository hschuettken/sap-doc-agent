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


async def upsert_enhancement(config: dict, *, author: str = "system", publish: bool = False) -> str | None:
    """Insert ``config`` as a draft (or published) Enhancement. Returns the new id, or
    None if a row with that (name, version) already exists.
    """
    name = config["name"]
    kind = config["kind"]
    status = "published" if publish else "draft"
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
            "INSERT INTO dsp_ai.enhancements (name, kind, status, config, author) "
            "VALUES ($1, $2, $3, $4::jsonb, $5) RETURNING id::text",
            name,
            kind,
            status,
            json.dumps(config),
            author,
        )
        if new_id and publish:
            try:
                await conn.execute(
                    "NOTIFY enhancement_published, $1",
                    new_id,
                )
            except Exception:
                pass  # best-effort NOTIFY
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


async def ensure_all_seeds_loaded() -> dict[str, int]:
    """Load every seed JSON under templates/seeds/ — idempotent per (name,version).

    Session B ships 5 seeds covering all enhancement kinds (narrative,
    ranking, item_enrich, action, briefing). Running this at dsp-ai
    startup guarantees the Studio's template library + ship criterion
    "all 5 kinds seeded" are satisfied on fresh compose.

    Set DSPAI_AUTO_PUBLISH_SEEDS=true to publish all seeds on insert (demo
    tenants). Defaults to false (draft) for safety.
    """
    import os

    publish = os.environ.get("DSPAI_AUTO_PUBLISH_SEEDS", "false").lower() == "true"
    if not SEEDS_DIR.exists():
        return {"seeded": 0, "skipped": 0, "errors": 0}
    seeded = skipped = errors = 0
    for path in sorted(SEEDS_DIR.glob("*.json")):
        try:
            config = await load_seed_file(path)
            new_id = await upsert_enhancement(config, author="setup_wizard", publish=publish)
            if new_id:
                seeded += 1
                logger.info("Seeded %s id=%s (published=%s)", config.get("name", path.stem), new_id, publish)
            else:
                skipped += 1
        except Exception:
            errors += 1
            logger.exception("Failed to seed %s", path)
    return {"seeded": seeded, "skipped": skipped, "errors": errors}
