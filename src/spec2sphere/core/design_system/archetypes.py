"""Layout Archetype CRUD + Horvath seed data.

Archetypes live in the `layout_archetypes` table.
NULL customer_id means a Horvath platform-level archetype.
Per-customer rows allow tenant-specific variants.

The nine standard archetypes are defined in Spec Section 8.2.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Connection helper
# ---------------------------------------------------------------------------


async def _get_conn():
    url = (
        os.environ.get("DATABASE_URL", "")
        .replace("postgresql+psycopg://", "postgresql://")
        .replace("postgresql+asyncpg://", "postgresql://")
    )
    return await asyncpg.connect(url)


def _row_to_dict(row) -> dict:
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, UUID):
            d[k] = str(v)
        elif hasattr(v, "hex") and not isinstance(v, (str, bytes)):
            d[k] = str(v)
    return d


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


async def create_archetype(
    customer_id: Optional[UUID],
    name: str,
    description: str,
    archetype_type: str,
    definition: dict,
) -> str:
    """Insert a layout archetype. Returns new UUID as string."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO layout_archetypes (customer_id, name, description, archetype_type, definition)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING id
            """,
            customer_id,
            name,
            description,
            archetype_type,
            json.dumps(definition),
        )
        return str(row["id"])
    finally:
        await conn.close()


async def get_archetype(archetype_id: str) -> Optional[dict]:
    """Fetch a single archetype by UUID string."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM layout_archetypes WHERE id = $1::uuid",
            archetype_id,
        )
        return _row_to_dict(row) if row else None
    finally:
        await conn.close()


async def update_archetype(archetype_id: str, definition: dict) -> bool:
    """Update the definition JSONB of an archetype. Returns True if updated."""
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "UPDATE layout_archetypes SET definition = $1::jsonb WHERE id = $2::uuid",
            json.dumps(definition),
            archetype_id,
        )
        return result == "UPDATE 1"
    finally:
        await conn.close()


async def delete_archetype(archetype_id: str) -> bool:
    """Delete an archetype by UUID. Returns True if deleted."""
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "DELETE FROM layout_archetypes WHERE id = $1::uuid",
            archetype_id,
        )
        return result == "DELETE 1"
    finally:
        await conn.close()


async def list_archetypes(
    customer_id=None,
    archetype_type: Optional[str] = None,
) -> list[dict]:
    """List archetypes with optional filters.

    customer_id=None returns only Horvath platform archetypes (IS NULL).
    customer_id=<UUID> returns that customer's archetypes.
    Omit customer_id entirely (use sentinel) to return all.
    """
    conn = await _get_conn()
    try:
        conditions: list[str] = []
        params: list = []
        idx = 1

        if isinstance(customer_id, _UnsetType):
            pass
        elif customer_id is None:
            conditions.append("customer_id IS NULL")
        else:
            conditions.append(f"customer_id = ${idx}::uuid")
            params.append(str(customer_id))
            idx += 1

        if archetype_type is not None:
            conditions.append(f"archetype_type = ${idx}")
            params.append(archetype_type)
            idx += 1

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await conn.fetch(
            f"SELECT * FROM layout_archetypes {where} ORDER BY name",
            *params,
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


class _UnsetType:
    pass


_UNSET = _UnsetType()

# Re-declare with sentinel default
_original_list_archetypes = list_archetypes


async def list_archetypes(  # noqa: F811
    customer_id=_UNSET,
    archetype_type: Optional[str] = None,
) -> list[dict]:
    """List archetypes with optional filters.

    customer_id=None   → only Horvath platform archetypes (customer_id IS NULL)
    customer_id=<UUID> → only that customer's archetypes
    customer_id omitted → all archetypes
    """
    conn = await _get_conn()
    try:
        conditions: list[str] = []
        params: list = []
        idx = 1

        if isinstance(customer_id, _UnsetType):
            pass
        elif customer_id is None:
            conditions.append("customer_id IS NULL")
        else:
            conditions.append(f"customer_id = ${idx}::uuid")
            params.append(str(customer_id))
            idx += 1

        if archetype_type is not None:
            conditions.append(f"archetype_type = ${idx}")
            params.append(archetype_type)
            idx += 1

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await conn.fetch(
            f"SELECT * FROM layout_archetypes {where} ORDER BY name",
            *params,
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Horvath seed archetypes (Spec Section 8.2)
# ---------------------------------------------------------------------------

_HORVATH_ARCHETYPES: list[dict] = [
    {
        "name": "exec_overview",
        "description": "High-level executive overview with KPI scorecard and trend sparklines.",
        "archetype_type": "layout",
        "definition": {
            "recommended_density": "sparse",
            "widget_slots": [
                {"slot": "header_kpis", "widget_types": ["kpi_tile"], "max_count": 4},
                {"slot": "trend_strip", "widget_types": ["sparkline"], "max_count": 4},
                {"slot": "highlight", "widget_types": ["bar_chart", "table"], "max_count": 1},
            ],
            "layout_grid": "1-col",
            "notes": "Audience: C-level. Max 4 KPIs. No drill-down.",
        },
    },
    {
        "name": "management_cockpit",
        "description": "Management cockpit with balanced view of plan vs. actual across departments.",
        "archetype_type": "layout",
        "definition": {
            "recommended_density": "medium",
            "widget_slots": [
                {"slot": "scorecard", "widget_types": ["kpi_tile"], "max_count": 6},
                {"slot": "variance_bar", "widget_types": ["waterfall", "bar_chart"], "max_count": 2},
                {"slot": "time_trend", "widget_types": ["line_chart"], "max_count": 1},
                {"slot": "detail_table", "widget_types": ["table"], "max_count": 1},
            ],
            "layout_grid": "2-col",
            "notes": "Audience: senior management. Plan/actual emphasis.",
        },
    },
    {
        "name": "variance_analysis",
        "description": "Deep variance breakdown with waterfall charts and driver decomposition.",
        "archetype_type": "layout",
        "definition": {
            "recommended_density": "medium",
            "widget_slots": [
                {"slot": "waterfall_main", "widget_types": ["waterfall"], "max_count": 1},
                {"slot": "driver_grid", "widget_types": ["bar_chart"], "max_count": 4},
                {"slot": "commentary", "widget_types": ["text_card"], "max_count": 1},
                {"slot": "detail_table", "widget_types": ["table"], "max_count": 1},
            ],
            "layout_grid": "2-col",
            "notes": "Must include absolute and relative variance columns.",
        },
    },
    {
        "name": "regional_performance",
        "description": "Geographic / regional performance comparison with map or matrix view.",
        "archetype_type": "layout",
        "definition": {
            "recommended_density": "medium",
            "widget_slots": [
                {"slot": "geo_visual", "widget_types": ["map", "heat_matrix"], "max_count": 1},
                {"slot": "ranking", "widget_types": ["bar_chart", "table"], "max_count": 1},
                {"slot": "kpi_strip", "widget_types": ["kpi_tile"], "max_count": 4},
                {"slot": "trend", "widget_types": ["line_chart"], "max_count": 1},
            ],
            "layout_grid": "2-col",
            "notes": "Region selector filter required.",
        },
    },
    {
        "name": "product_drill",
        "description": "Product / material hierarchy drill from portfolio down to SKU.",
        "archetype_type": "layout",
        "definition": {
            "recommended_density": "dense",
            "widget_slots": [
                {"slot": "hierarchy_nav", "widget_types": ["tree_filter"], "max_count": 1},
                {"slot": "kpi_strip", "widget_types": ["kpi_tile"], "max_count": 6},
                {"slot": "pareto", "widget_types": ["bar_chart"], "max_count": 1},
                {"slot": "detail_table", "widget_types": ["table"], "max_count": 1},
            ],
            "layout_grid": "sidebar+main",
            "notes": "Hierarchy filter drives all visuals.",
        },
    },
    {
        "name": "driver_analysis",
        "description": "Root-cause / driver decomposition showing contribution of cost or revenue factors.",
        "archetype_type": "layout",
        "definition": {
            "recommended_density": "medium",
            "widget_slots": [
                {"slot": "bridge_chart", "widget_types": ["waterfall"], "max_count": 1},
                {"slot": "scatter", "widget_types": ["scatter_plot"], "max_count": 1},
                {"slot": "driver_table", "widget_types": ["table"], "max_count": 1},
                {"slot": "commentary", "widget_types": ["text_card"], "max_count": 1},
            ],
            "layout_grid": "2-col",
            "notes": "Factor labels must use business terminology.",
        },
    },
    {
        "name": "exception_dashboard",
        "description": "Exception / alert-first layout highlighting out-of-tolerance items.",
        "archetype_type": "layout",
        "definition": {
            "recommended_density": "medium",
            "widget_slots": [
                {"slot": "alert_banner", "widget_types": ["alert_tile"], "max_count": 3},
                {"slot": "exception_list", "widget_types": ["table"], "max_count": 1},
                {"slot": "trend", "widget_types": ["line_chart"], "max_count": 1},
                {"slot": "threshold_bar", "widget_types": ["bullet_chart"], "max_count": 1},
            ],
            "layout_grid": "1-col",
            "notes": "Red/amber/green status indicators required.",
        },
    },
    {
        "name": "table_first",
        "description": "Data-dense tabular layout with optional mini-charts in cells.",
        "archetype_type": "layout",
        "definition": {
            "recommended_density": "dense",
            "widget_slots": [
                {"slot": "main_table", "widget_types": ["table"], "max_count": 1},
                {"slot": "summary_kpis", "widget_types": ["kpi_tile"], "max_count": 4},
                {"slot": "sparkline_col", "widget_types": ["sparkline"], "max_count": 8},
            ],
            "layout_grid": "1-col",
            "notes": "Audience: analysts. Frozen header row required. Export to Excel.",
        },
    },
    {
        "name": "guided_analysis",
        "description": "Narrative-led layout that guides users through a story with annotated visuals.",
        "archetype_type": "layout",
        "definition": {
            "recommended_density": "sparse",
            "widget_slots": [
                {"slot": "story_header", "widget_types": ["text_card"], "max_count": 1},
                {"slot": "chapter_1", "widget_types": ["bar_chart", "line_chart"], "max_count": 2},
                {"slot": "chapter_2", "widget_types": ["waterfall", "scatter_plot"], "max_count": 2},
                {"slot": "conclusion", "widget_types": ["text_card", "kpi_tile"], "max_count": 2},
            ],
            "layout_grid": "1-col",
            "notes": "Each section must have an explanatory title and annotation.",
        },
    },
]


async def seed_horvath_archetypes() -> int:
    """Seed the nine standard Horvath layout archetypes.

    Uses name + customer_id IS NULL as the uniqueness check so it is safe
    to call multiple times (idempotent via ON CONFLICT DO NOTHING would
    require a unique constraint; we do a SELECT first instead since the
    table has no unique constraint on name+customer_id).
    """
    conn = await _get_conn()
    inserted = 0
    try:
        # Fetch already-seeded names for Horvath defaults
        existing_rows = await conn.fetch("SELECT name FROM layout_archetypes WHERE customer_id IS NULL")
        existing_names = {r["name"] for r in existing_rows}

        for arch in _HORVATH_ARCHETYPES:
            if arch["name"] in existing_names:
                continue
            await conn.execute(
                """
                INSERT INTO layout_archetypes (customer_id, name, description, archetype_type, definition)
                VALUES (NULL, $1, $2, $3, $4::jsonb)
                """,
                arch["name"],
                arch["description"],
                arch["archetype_type"],
                json.dumps(arch["definition"]),
            )
            inserted += 1

    finally:
        await conn.close()

    logger.info("Seeded %d Horvath layout archetypes", inserted)
    return inserted
