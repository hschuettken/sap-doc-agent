"""Async connection helper that sets the RLS customer scope on every
connection. Use ``async with get_conn() as conn:`` everywhere that
touches ``dsp_ai.*`` tables.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

from .settings import postgres_dsn


def current_customer(override: str | None = None) -> str:
    """Resolve the active customer: explicit override, else CUSTOMER env, else 'default'."""
    if override:
        return override
    return os.environ.get("CUSTOMER", "default")


@asynccontextmanager
async def get_conn(customer: str | None = None) -> AsyncIterator[asyncpg.Connection]:
    """Open an asyncpg connection and bind the dspai.customer GUC for RLS.

    The GUC uses ``false`` for is_local so the setting persists across
    statements on this connection (not rolled back at transaction end).
    """
    conn = await asyncpg.connect(postgres_dsn())
    try:
        await conn.execute(
            "SELECT set_config('dspai.customer', $1, false)",
            current_customer(customer),
        )
        yield conn
    finally:
        await conn.close()
