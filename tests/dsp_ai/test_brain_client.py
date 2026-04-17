"""Integration tests for the Neo4j Brain client + schema.

Skipped when NEO4J_URL is unset (unit-only CI). Start the bundled
neo4j service to enable: `NEO4J_PASSWORD=test docker compose up -d neo4j`.
"""

from __future__ import annotations

import os

import pytest

from spec2sphere.dsp_ai.brain import client, schema

pytestmark = pytest.mark.skipif(
    not (os.environ.get("NEO4J_URL") and os.environ.get("NEO4J_PASSWORD")),
    reason="NEO4J_URL / NEO4J_PASSWORD not set — integration test",
)


@pytest.fixture(autouse=True)
async def _close_driver_between_tests():
    """Reset the module-level driver so each test owns its own event loop."""
    yield
    await client.close()


@pytest.mark.asyncio
async def test_bootstrap_creates_constraints() -> None:
    await schema.bootstrap()
    rows = await client.run("SHOW CONSTRAINTS")
    names = {r["name"] for r in rows}
    assert "dsp_object_id" in names
    assert "generation_id" in names


@pytest.mark.asyncio
async def test_write_and_read_dsp_object() -> None:
    await client.run("MATCH (n:DspObject {id: 'test.foo'}) DETACH DELETE n")
    await client.run(
        "CREATE (n:DspObject {id: $id, kind: 'Table', customer: 'horvath'})",
        id="test.foo",
    )
    rows = await client.run("MATCH (n:DspObject {id: $id}) RETURN n.customer AS c", id="test.foo")
    assert rows[0]["c"] == "horvath"


@pytest.mark.asyncio
async def test_run_returns_dict_rows() -> None:
    rows = await client.run("RETURN 1 AS one, 'two' AS two")
    assert rows == [{"one": 1, "two": "two"}]
