"""Tests for Session 5 Task 4: DSP Factory — artifact generator, deployer, readback.

All database and route calls are mocked — no real DB or browser required.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from spec2sphere.dsp_factory.artifact_generator import (
    generate_csn_definition,
    generate_deployment_manifest,
    generate_dev_copy_sql,
)
from spec2sphere.dsp_factory.readback import structural_diff
from spec2sphere.factory.route_router import RouteDecision
from spec2sphere.tenant.context import ContextEnvelope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_ctx() -> ContextEnvelope:
    return ContextEnvelope.single_tenant(
        tenant_id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
    )


def make_mock_conn():
    conn = AsyncMock()
    conn.close = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="UPDATE 1")
    return conn


# ---------------------------------------------------------------------------
# 1. generate_dev_copy_sql
# ---------------------------------------------------------------------------


def test_generate_dev_copy_sql():
    result = generate_dev_copy_sql("SALES_VIEW", "SELECT id, amount FROM orders")

    assert result["dev_view_name"] == "SALES_VIEW_DEV"
    # SQL must be preserved and contain SELECT
    assert "SELECT" in result["dev_sql"]
    # Header comment references original view name
    assert "SALES_VIEW" in result["dev_sql"]


# ---------------------------------------------------------------------------
# 2. generate_deployment_manifest
# ---------------------------------------------------------------------------


def test_generate_deployment_manifest():
    """Objects with dependencies must come after their dependencies in deploy_order.

    Hierarchy:
        Raw               — no deps
        Orders            — depends on Raw
        Sales             — depends on Orders
        Revenue           — depends on Sales
    """
    objects = [
        {"name": "Revenue", "layer": "gold", "dependencies": ["Sales"]},
        {"name": "Sales", "layer": "silver", "dependencies": ["Orders"]},
        {"name": "Orders", "layer": "bronze", "dependencies": ["Raw"]},
        {"name": "Raw", "layer": "bronze", "dependencies": []},
    ]

    manifest = generate_deployment_manifest(objects)

    assert len(manifest) == 4

    order_by_name = {item["name"]: item["deploy_order"] for item in manifest}

    # Dependency ordering invariants
    assert order_by_name["Raw"] < order_by_name["Orders"]
    assert order_by_name["Orders"] < order_by_name["Sales"]
    assert order_by_name["Sales"] < order_by_name["Revenue"]

    # Every item must have create_or_update set
    for item in manifest:
        assert item["create_or_update"] == "create"


# ---------------------------------------------------------------------------
# 3. generate_csn_definition
# ---------------------------------------------------------------------------


def test_generate_csn_definition():
    obj = {
        "name": "FactSales",
        "object_type": "fact_view",
        "columns": [
            {"name": "id", "type": "INT"},
            {"name": "amount", "type": "DECIMAL"},
            {"name": "sale_date", "type": "DATE"},
            {"name": "label", "type": "VARCHAR"},
            {"name": "active", "type": "BOOL"},
        ],
    }

    csn = generate_csn_definition(obj)

    assert "definitions" in csn
    assert "FactSales" in csn["definitions"]

    entity = csn["definitions"]["FactSales"]
    assert entity["kind"] == "entity"
    elements = entity["elements"]

    assert elements["id"]["type"] == "cds.Integer"
    assert elements["amount"]["type"] == "cds.Decimal"
    assert elements["sale_date"]["type"] == "cds.Date"
    assert elements["label"]["type"] == "cds.String"
    assert elements["active"]["type"] == "cds.Boolean"


# ---------------------------------------------------------------------------
# 4. deploy_object — mocked route + DB
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deploy_object_creates_step_record():
    """deploy_object must INSERT a step, try routes, and return status deployed or failed."""
    from spec2sphere.dsp_factory.deployer import deploy_object

    ctx = make_ctx()
    conn = make_mock_conn()

    mock_decision = RouteDecision(
        primary_route="csn_import",
        fallback_chain=["api"],
        scores={"csn_import": 0.5, "api": 0.6},
        reason="test",
    )

    with (
        patch("spec2sphere.dsp_factory.deployer._get_conn", return_value=conn),
        patch("spec2sphere.dsp_factory.deployer.select_route", return_value=mock_decision),
        patch("spec2sphere.dsp_factory.deployer.update_route_fitness", new_callable=AsyncMock),
        patch("spec2sphere.dsp_factory.deployer._execute_route", new_callable=AsyncMock) as mock_exec,
    ):
        # First call succeeds
        mock_exec.return_value = None

        obj = {
            "name": "TestView",
            "object_type": "relational_view",
            "columns": [{"name": "id", "type": "INT"}],
        }
        result = await deploy_object(ctx, str(uuid.uuid4()), obj, "sandbox")

    assert "step_id" in result
    assert "route_chosen" in result
    assert result["status"] in ("deployed", "failed")
    assert result["duration"] >= 0


# ---------------------------------------------------------------------------
# 5. structural_diff — identical objects
# ---------------------------------------------------------------------------


def test_structural_diff_identical():
    spec = {
        "columns": [
            {"name": "id", "type": "INT"},
            {"name": "name", "type": "VARCHAR"},
        ],
        "joins": [{"table": "customers"}],
    }

    result = structural_diff(spec, spec)

    assert result["match"] is True
    assert result["differences"] == []


# ---------------------------------------------------------------------------
# 6. structural_diff — missing column
# ---------------------------------------------------------------------------


def test_structural_diff_missing_column():
    expected = {
        "columns": [
            {"name": "id", "type": "INT"},
            {"name": "name", "type": "VARCHAR"},
            {"name": "missing_col", "type": "VARCHAR"},
        ],
        "joins": [],
    }
    actual = {
        "columns": [
            {"name": "id", "type": "INT"},
            {"name": "name", "type": "VARCHAR"},
        ],
        "joins": [],
    }

    result = structural_diff(expected, actual)

    assert result["match"] is False
    types = [d["type"] for d in result["differences"]]
    assert "missing_column" in types

    missing = [d for d in result["differences"] if d["type"] == "missing_column"]
    assert any(d["expected"] == "missing_col" for d in missing)


# ---------------------------------------------------------------------------
# 7. structural_diff — type mismatch
# ---------------------------------------------------------------------------


def test_structural_diff_type_mismatch():
    expected = {
        "columns": [
            {"name": "id", "type": "INT"},
            {"name": "amount", "type": "DECIMAL"},
        ],
        "joins": [],
    }
    actual = {
        "columns": [
            {"name": "id", "type": "INT"},
            {"name": "amount", "type": "VARCHAR"},  # wrong type
        ],
        "joins": [],
    }

    result = structural_diff(expected, actual)

    assert result["match"] is False
    types = [d["type"] for d in result["differences"]]
    assert "type_mismatch" in types

    mismatch = [d for d in result["differences"] if d["type"] == "type_mismatch"]
    assert any(d["expected"] == "DECIMAL" and d["actual"] == "VARCHAR" for d in mismatch)
