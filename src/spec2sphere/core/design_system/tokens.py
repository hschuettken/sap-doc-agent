"""Design Token CRUD + Horvath brand defaults.

Tokens are stored in the `design_tokens` table.  NULL customer_id means a
Horvath-platform default.  Per-customer rows override defaults when a design
profile is resolved.

Token types: color | typography | spacing | density | emphasis
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
# Connection helper — identical pattern to spec2sphere.db
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


async def create_token(
    customer_id: Optional[UUID],
    token_type: str,
    token_name: str,
    token_value: dict,
) -> str:
    """Insert a design token.  Returns the new UUID as a string."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO design_tokens (customer_id, token_type, token_name, token_value)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id
            """,
            customer_id,
            token_type,
            token_name,
            json.dumps(token_value),
        )
        return str(row["id"])
    finally:
        await conn.close()


async def get_token(token_id: str) -> Optional[dict]:
    """Fetch a single token by UUID string. Returns None if not found."""
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM design_tokens WHERE id = $1::uuid",
            token_id,
        )
        return _row_to_dict(row) if row else None
    finally:
        await conn.close()


async def update_token(token_id: str, token_value: dict) -> bool:
    """Update the value of an existing token. Returns True if a row was updated."""
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "UPDATE design_tokens SET token_value = $1::jsonb WHERE id = $2::uuid",
            json.dumps(token_value),
            token_id,
        )
        return result == "UPDATE 1"
    finally:
        await conn.close()


async def delete_token(token_id: str) -> bool:
    """Delete a token by UUID string. Returns True if a row was deleted."""
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "DELETE FROM design_tokens WHERE id = $1::uuid",
            token_id,
        )
        return result == "DELETE 1"
    finally:
        await conn.close()


# Sentinel object so we can distinguish "caller passed None (Horvath defaults)"
# from "caller did not supply the argument (all tokens)".
class _UnsetType:
    pass


_UNSET = _UnsetType()


async def list_tokens(
    customer_id=_UNSET,
    token_type: Optional[str] = None,
) -> list[dict]:
    """List tokens, optionally filtered by customer_id and/or token_type.

    customer_id=None  → only Horvath defaults (customer_id IS NULL)
    customer_id=<UUID> → only that customer's overrides
    customer_id omitted → all tokens regardless of customer
    """
    conn = await _get_conn()
    try:
        conditions: list[str] = []
        params: list = []
        idx = 1

        if isinstance(customer_id, _UnsetType):
            pass  # no filter on customer_id
        elif customer_id is None:
            conditions.append("customer_id IS NULL")
        else:
            conditions.append(f"customer_id = ${idx}::uuid")
            params.append(str(customer_id))
            idx += 1

        if token_type is not None:
            conditions.append(f"token_type = ${idx}")
            params.append(token_type)
            idx += 1

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = await conn.fetch(
            f"SELECT * FROM design_tokens {where} ORDER BY token_type, token_name",
            *params,
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Design profile resolution
# ---------------------------------------------------------------------------


async def resolve_design_profile(ctx) -> dict:
    """Merge Horvath defaults with customer overrides.

    Accepts a ContextEnvelope or a raw UUID (backward compat).

    Returns a nested dict:
      { token_type: { token_name: token_value, ... }, ... }

    Customer rows override Horvath defaults when the same (type, name) key
    appears in both.
    """
    from spec2sphere.tenant.context import ContextEnvelope

    if isinstance(ctx, ContextEnvelope):
        customer_id = ctx.customer_id
    else:
        customer_id = ctx  # backward compat: raw UUID

    conn = await _get_conn()
    try:
        # Fetch Horvath defaults (customer_id IS NULL)
        default_rows = await conn.fetch(
            "SELECT token_type, token_name, token_value FROM design_tokens WHERE customer_id IS NULL"
        )
        # Fetch customer overrides
        override_rows = await conn.fetch(
            "SELECT token_type, token_name, token_value FROM design_tokens WHERE customer_id = $1::uuid",
            str(customer_id),
        )
    finally:
        await conn.close()

    profile: dict[str, dict] = {}

    for row in default_rows:
        t_type = row["token_type"]
        if t_type not in profile:
            profile[t_type] = {}
        value = row["token_value"]
        if isinstance(value, str):
            value = json.loads(value)
        profile[t_type][row["token_name"]] = value

    for row in override_rows:
        t_type = row["token_type"]
        if t_type not in profile:
            profile[t_type] = {}
        value = row["token_value"]
        if isinstance(value, str):
            value = json.loads(value)
        profile[t_type][row["token_name"]] = value

    return profile


# ---------------------------------------------------------------------------
# Seed Horvath defaults
# ---------------------------------------------------------------------------

_HORVATH_DEFAULTS: list[tuple[str, str, dict]] = [
    # --- Colors ---
    ("color", "primary", {"hex": "#05415A", "label": "Horvath petrol"}),
    ("color", "secondary", {"hex": "#0a6b8f"}),
    ("color", "accent", {"hex": "#C8963E", "label": "Horvath gold"}),
    ("color", "success", {"hex": "#2E7D32"}),
    ("color", "warning", {"hex": "#F57F17"}),
    ("color", "danger", {"hex": "#C62828"}),
    ("color", "neutral", {"hex": "#757575"}),
    ("color", "background", {"hex": "#F5F5F5"}),
    ("color", "surface", {"hex": "#FFFFFF"}),
    ("color", "text", {"hex": "#353434"}),
    # --- Typography ---
    ("typography", "heading", {"family": "Georgia", "weight": 700}),
    ("typography", "subheading", {"family": "Georgia", "weight": 600}),
    ("typography", "body", {"family": "Inter", "weight": 400}),
    ("typography", "caption", {"family": "Inter", "weight": 400, "size": "0.75rem"}),
    ("typography", "kpi_value", {"family": "Inter", "weight": 700, "size": "2rem"}),
    ("typography", "kpi_label", {"family": "Inter", "weight": 400, "size": "0.875rem"}),
    # --- Spacing ---
    ("spacing", "compact", {"base": "4px"}),
    ("spacing", "standard", {"base": "8px"}),
    ("spacing", "spacious", {"base": "16px"}),
    # --- Density ---
    (
        "density",
        "dense",
        {
            "audience": "analyst",
            "kpi_limit": 12,
            "widgets_per_row": 4,
        },
    ),
    (
        "density",
        "medium",
        {
            "audience": "management",
            "kpi_limit": 8,
            "widgets_per_row": 3,
        },
    ),
    (
        "density",
        "sparse",
        {
            "audience": "executive",
            "kpi_limit": 4,
            "widgets_per_row": 2,
        },
    ),
    # --- Emphasis ---
    ("emphasis", "highlight", {"color": "#C8963E", "weight": "bold"}),
    ("emphasis", "variance_positive", {"color": "#2E7D32"}),
    ("emphasis", "variance_negative", {"color": "#C62828"}),
    ("emphasis", "target_line", {"style": "dashed", "color": "#757575"}),
]


async def seed_horvath_defaults() -> int:
    """Seed Horvath brand tokens.

    Only inserts rows that do not already exist (ON CONFLICT DO NOTHING).
    Returns the number of rows actually inserted.
    """
    conn = await _get_conn()
    inserted = 0
    try:
        for token_type, token_name, token_value in _HORVATH_DEFAULTS:
            # NULL customer_id: unique constraint may not fire (NULLs are distinct in PG < 15).
            # Use explicit SELECT guard instead of ON CONFLICT.
            exists = await conn.fetchrow(
                "SELECT 1 FROM design_tokens WHERE customer_id IS NULL AND token_type = $1 AND token_name = $2",
                token_type,
                token_name,
            )
            if exists:
                continue
            await conn.execute(
                "INSERT INTO design_tokens (customer_id, token_type, token_name, token_value) VALUES (NULL, $1, $2, $3::jsonb)",
                token_type,
                token_name,
                json.dumps(token_value),
            )
            inserted += 1
    finally:
        await conn.close()

    logger.info("Seeded %d Horvath default tokens", inserted)
    return inserted
