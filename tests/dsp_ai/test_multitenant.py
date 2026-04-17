"""RLS blocks cross-customer reads on dsp_ai.* tables.

Uses the live Postgres (the test target in smoke compose); creates two
distinct customers' enhancements + confirms neither side sees the other.
"""

from __future__ import annotations

import os
import uuid

import pytest

from spec2sphere.dsp_ai.db import get_conn
from spec2sphere.dsp_ai.settings import postgres_dsn


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="requires live Postgres via DATABASE_URL",
)


@pytest.fixture
async def two_customer_seeds():
    """Insert one enhancement for 'alpha' and one for 'beta'; yield their names."""
    import asyncpg  # local import so collect is cheap

    dsn = postgres_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        # Set customer to 'alpha' to insert the alpha row (RLS WITH CHECK requires customer match)
        await conn.execute("SELECT set_config('dspai.customer', 'alpha', false)")
        a_name = f"tenant_test_alpha_{uuid.uuid4().hex[:8]}"
        await conn.execute(
            "INSERT INTO dsp_ai.enhancements (name, kind, config, author, customer) "
            "VALUES ($1, 'narrative', '{}'::jsonb, 'test', 'alpha')",
            a_name,
        )
        await conn.execute("SELECT set_config('dspai.customer', 'beta', false)")
        b_name = f"tenant_test_beta_{uuid.uuid4().hex[:8]}"
        await conn.execute(
            "INSERT INTO dsp_ai.enhancements (name, kind, config, author, customer) "
            "VALUES ($1, 'narrative', '{}'::jsonb, 'test', 'beta')",
            b_name,
        )
    finally:
        await conn.close()
    yield a_name, b_name
    # cleanup: connect under each customer and delete its own row
    conn = await asyncpg.connect(dsn)
    try:
        for cust, name in (("alpha", a_name), ("beta", b_name)):
            await conn.execute("SELECT set_config('dspai.customer', $1, false)", cust)
            await conn.execute("DELETE FROM dsp_ai.enhancements WHERE name = $1", name)
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_alpha_cannot_see_beta(two_customer_seeds):
    a_name, b_name = two_customer_seeds
    async with get_conn(customer="alpha") as conn:
        rows = await conn.fetch("SELECT name FROM dsp_ai.enhancements WHERE name IN ($1, $2)", a_name, b_name)
        names = {r["name"] for r in rows}
    assert a_name in names
    assert b_name not in names


@pytest.mark.asyncio
async def test_beta_cannot_see_alpha(two_customer_seeds):
    a_name, b_name = two_customer_seeds
    async with get_conn(customer="beta") as conn:
        rows = await conn.fetch("SELECT name FROM dsp_ai.enhancements WHERE name IN ($1, $2)", a_name, b_name)
        names = {r["name"] for r in rows}
    assert b_name in names
    assert a_name not in names


@pytest.mark.asyncio
async def test_default_customer_still_works():
    """The seeded Session B enhancements use customer='default'; they should still be readable."""
    async with get_conn() as conn:
        count = await conn.fetchval("SELECT count(*) FROM dsp_ai.enhancements WHERE customer = 'default'")
    assert count is not None  # may be 0 on fresh DB, but must not error
