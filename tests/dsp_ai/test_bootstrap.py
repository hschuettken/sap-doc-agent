"""Integration tests for Morning Brief bootstrap seed + wizard hook.

Hits a real compose postgres. Skipped when DATABASE_URL is unset.
"""

from __future__ import annotations

import os

import asyncpg
import pytest

from spec2sphere.dsp_ai.seeds import ensure_morning_brief_seeded
from spec2sphere.dsp_ai.settings import postgres_dsn

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — integration test",
)


@pytest.fixture(autouse=True)
async def _clean():
    conn = await asyncpg.connect(postgres_dsn())
    try:
        await conn.execute(
            "DELETE FROM dsp_ai.briefings; "
            "DELETE FROM dsp_ai.generations; "
            "DELETE FROM dsp_ai.studio_audit; "
            "DELETE FROM dsp_ai.enhancements"
        )
    finally:
        await conn.close()
    yield


@pytest.mark.asyncio
async def test_ensure_morning_brief_seeded_creates_enhancement() -> None:
    new_id = await ensure_morning_brief_seeded()
    assert new_id is not None

    conn = await asyncpg.connect(postgres_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT name, kind, status, author FROM dsp_ai.enhancements WHERE id = $1::uuid",
            new_id,
        )
    finally:
        await conn.close()
    assert row["name"] == "Morning Brief — Revenue"
    assert row["kind"] == "briefing"
    assert row["status"] == "draft"
    assert row["author"] == "setup_wizard"


@pytest.mark.asyncio
async def test_ensure_morning_brief_seeded_is_idempotent() -> None:
    first = await ensure_morning_brief_seeded()
    second = await ensure_morning_brief_seeded()
    assert first is not None
    assert second is None  # already present — no-op

    conn = await asyncpg.connect(postgres_dsn())
    try:
        count = await conn.fetchval("SELECT count(*) FROM dsp_ai.enhancements WHERE name = 'Morning Brief — Revenue'")
    finally:
        await conn.close()
    assert count == 1


@pytest.mark.asyncio
async def test_seed_config_validates_against_pydantic_shape() -> None:
    """The seed JSON must round-trip through EnhancementConfig."""
    from spec2sphere.dsp_ai.config import EnhancementConfig
    from spec2sphere.dsp_ai.seeds import SEEDS_DIR, load_seed_file

    raw = await load_seed_file(SEEDS_DIR / "morning_brief_revenue.json")
    cfg = EnhancementConfig.model_validate(raw)
    assert cfg.name == "Morning Brief — Revenue"
    assert cfg.output_schema is not None
    assert cfg.adaptive_rules.per_user is True
    assert cfg.bindings.external is not None
