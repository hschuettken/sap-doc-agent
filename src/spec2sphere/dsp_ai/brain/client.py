"""Neo4j async driver singleton + query helpers.

Per-process singleton — dsp-ai is a single-replica service so a shared
driver is safe. The Brain is scoped to the bundled Neo4j container
(neo4j:7687 inside the docker network); auth comes from env.
"""

from __future__ import annotations

import os
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase

_driver: AsyncDriver | None = None


def _url() -> str:
    return os.environ.get("NEO4J_URL", "bolt://neo4j:7687")


def _auth() -> tuple[str, str]:
    return ("neo4j", os.environ["NEO4J_PASSWORD"])


async def driver() -> AsyncDriver:
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(_url(), auth=_auth())
    return _driver


async def run(cypher: str, **params: Any) -> list[dict[str, Any]]:
    """Run a Cypher statement and return rows as plain dicts."""
    d = await driver()
    async with d.session() as session:
        result = await session.run(cypher, **params)
        return [dict(record) async for record in result]


async def run_scoped(cypher: str, customer: str, **params: Any) -> list[dict[str, Any]]:
    """Run Cypher with the customer param merged in so queries can MATCH (:Node {customer: $customer})."""
    return await run(cypher, customer=customer, **params)


async def close() -> None:
    """Close the shared driver (for tests / clean shutdown)."""
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None
