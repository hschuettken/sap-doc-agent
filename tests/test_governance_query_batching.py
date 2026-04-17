"""Tests for governance query batching (N+1 consolidation).

Verifies _fetch_project_data runs its per-project queries concurrently via
asyncio.gather rather than sequentially.
"""

from __future__ import annotations


import pytest

from spec2sphere.web.governance_routes import _fetch_project_data


class FakeConn:
    """Tracks the order queries were awaited to confirm gather() is used."""

    def __init__(self):
        self.call_log: list[str] = []

    async def fetchrow(self, sql: str, *args):
        if "projects" in sql.lower() and "project_id" not in sql.lower():
            self.call_log.append("projects")
            return {"id": args[0], "customer_id": args[0], "name": "Test"}
        if "customers" in sql.lower():
            self.call_log.append("customers")
            return {"id": args[0], "name": "TestCo"}
        self.call_log.append(f"fetchrow:{sql[:30]}")
        return None

    async def fetch(self, sql: str, *args):
        key = sql.split("FROM ")[1].split(" ")[0].strip().lower() if "FROM" in sql else sql[:20]
        self.call_log.append(key)
        return []


@pytest.mark.asyncio
async def test_fetch_project_data_batches_per_project_queries():
    import uuid

    conn = FakeConn()
    pid = str(uuid.uuid4())

    data = await _fetch_project_data(conn, pid)

    # All 9 tables must be queried (1 project fetchrow + 8 gathered)
    assert "projects" in conn.call_log
    # The 8 gathered queries (customer + 7 project-scoped fetches)
    assert "customers" in conn.call_log
    assert "requirements" in conn.call_log
    assert "hla_documents" in conn.call_log
    assert "tech_specs" in conn.call_log
    assert "architecture_decisions" in conn.call_log
    assert "technical_objects" in conn.call_log
    assert "reconciliation_results" in conn.call_log
    assert "approvals" in conn.call_log

    # Result shape preserved
    assert data["project"]["name"] == "Test"
    assert data["customer"]["name"] == "TestCo"
    assert data["requirements"] == []
    assert data["approvals"] == []


@pytest.mark.asyncio
async def test_fetch_project_data_missing_project_returns_empty():
    class MissingConn:
        async def fetchrow(self, *_a, **_k):
            return None

        async def fetch(self, *_a, **_k):
            return []

    result = await _fetch_project_data(MissingConn(), "00000000-0000-0000-0000-000000000000")
    assert result == {}
