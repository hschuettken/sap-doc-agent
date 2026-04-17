"""Library export / import round-trip."""

from __future__ import annotations

import os
import uuid

import pytest

from spec2sphere.dsp_ai.library import (
    LIBRARY_VERSION,
    export_library,
    import_library,
)


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="requires live Postgres via DATABASE_URL",
)

# Valid config dict matching the actual EnhancementConfig schema:
#   bindings.data.dsp_query is required; prompt_template + render_hint required.
_VALID_CONFIG = {
    "name": "x",
    "kind": "narrative",
    "mode": "live",
    "bindings": {"data": {"dsp_query": "SELECT 1"}},
    "prompt_template": "Hi",
    "render_hint": "narrative_text",
}


@pytest.fixture
async def seeded_two():
    """Seed two draft enhancements in 'lib_test_alpha' customer."""
    import asyncpg
    import json  # noqa: PLC0415

    from spec2sphere.dsp_ai.settings import postgres_dsn  # noqa: PLC0415

    dsn = postgres_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("SELECT set_config('dspai.customer', 'lib_test_alpha', false)")
        names = [f"lib_test_{uuid.uuid4().hex[:8]}_{i}" for i in range(2)]
        for n in names:
            cfg = dict(_VALID_CONFIG, name=n)
            await conn.execute(
                "INSERT INTO dsp_ai.enhancements (name, kind, config, author, customer) "
                "VALUES ($1, 'narrative', $2::jsonb, 'test', 'lib_test_alpha')",
                n,
                json.dumps(cfg),
            )
    finally:
        await conn.close()
    yield names
    conn = await asyncpg.connect(dsn)
    try:
        for cust in ("lib_test_alpha", "lib_test_beta"):
            await conn.execute("SELECT set_config('dspai.customer', $1, false)", cust)
            for n in names:
                await conn.execute("DELETE FROM dsp_ai.enhancements WHERE name = $1", n)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_export_blob_has_required_shape(seeded_two):
    blob = await export_library("lib_test_alpha")
    assert blob["version"] == LIBRARY_VERSION
    assert blob["customer"] == "lib_test_alpha"
    assert "exported_at" in blob and blob["exported_at"].endswith("Z")
    assert len(blob["enhancements"]) >= 2
    names_in_blob = {e["name"] for e in blob["enhancements"]}
    assert set(seeded_two).issubset(names_in_blob)


@pytest.mark.asyncio
async def test_round_trip_preserves_names(seeded_two):
    blob = await export_library("lib_test_alpha")
    result = await import_library(blob, customer="lib_test_beta", mode="merge")
    assert result["customer"] == "lib_test_beta"
    assert result["imported"] >= 2

    blob2 = await export_library("lib_test_beta")
    assert {e["name"] for e in blob["enhancements"]} == {e["name"] for e in blob2["enhancements"]}


@pytest.mark.asyncio
async def test_import_rejects_bad_config():
    bad = {
        "version": LIBRARY_VERSION,
        "enhancements": [
            {
                "name": "x",
                "kind": "narrative",
                "version": 1,
                "status": "draft",
                "config": {"name": "x"},  # missing required fields
            }
        ],
    }
    with pytest.raises(Exception):
        await import_library(bad, customer="lib_test_alpha", mode="merge")


@pytest.mark.asyncio
async def test_import_rejects_wrong_version():
    blob = {"version": "0.9", "enhancements": []}
    with pytest.raises(ValueError, match="unsupported library version"):
        await import_library(blob, customer="lib_test_alpha")
