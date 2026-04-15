"""Integration test: tech spec → deploy → reconcile end-to-end."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spec2sphere.tenant.context import ContextEnvelope


def make_ctx():
    return ContextEnvelope.single_tenant(tenant_id=uuid.uuid4(), customer_id=uuid.uuid4(), project_id=uuid.uuid4())


def make_mock_conn():
    conn = AsyncMock()
    conn.close = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=None)
    conn.fetch = AsyncMock(return_value=[])
    conn.execute = AsyncMock(return_value="INSERT 0 1")
    conn.fetchval = AsyncMock(return_value=0)
    tx_ctx = AsyncMock()
    tx_ctx.__aenter__ = AsyncMock(return_value=None)
    tx_ctx.__aexit__ = AsyncMock(return_value=False)
    conn.transaction = MagicMock(return_value=tx_ctx)
    return conn


class _DictRecord(dict):
    pass


@pytest.mark.asyncio
@patch("spec2sphere.factory.reconciliation._get_conn")
@patch("spec2sphere.dsp_factory.deployer._get_conn")
@patch("spec2sphere.dsp_factory.deployer._execute_route", new_callable=AsyncMock)
@patch("spec2sphere.factory.route_router._get_conn")
async def test_end_to_end_deploy_and_reconcile(mock_router_conn, mock_execute, mock_deploy_conn, mock_recon_conn):
    from spec2sphere.dsp_factory.artifact_generator import generate_deployment_manifest
    from spec2sphere.dsp_factory.deployer import create_deployment_run, deploy_object
    from spec2sphere.factory.reconciliation import compute_aggregate_summary, run_reconciliation

    # Setup mocks
    for mock in [mock_router_conn, mock_deploy_conn, mock_recon_conn]:
        mock.return_value = make_mock_conn()

    # Mock route fitness (empty — use defaults)
    mock_router_conn.return_value.fetch.return_value = []

    ctx = make_ctx()

    # Step 1: Generate manifest from tech spec objects
    objects = [
        {
            "name": "01_LT_Raw",
            "layer": "raw",
            "dependencies": [],
            "object_type": "relational_view",
            "platform": "dsp",
            "id": uuid.uuid4(),
            "generated_artifact": "SELECT 1",
        },
        {
            "name": "03_FV_Sales",
            "layer": "mart",
            "dependencies": ["01_LT_Raw"],
            "object_type": "relational_view",
            "platform": "dsp",
            "id": uuid.uuid4(),
            "generated_artifact": "SELECT 2",
        },
    ]
    manifest = generate_deployment_manifest(objects)
    assert manifest[0]["name"] == "01_LT_Raw"  # Raw first
    assert manifest[1]["name"] == "03_FV_Sales"  # Mart second

    # Step 2: Create run and deploy each object
    run = await create_deployment_run(ctx, tech_spec_id=uuid.uuid4())
    assert "run_id" in run

    for obj in manifest:
        result = await deploy_object(ctx, run["run_id"], obj, environment="sandbox")
        assert result["status"] in ("deployed", "failed")

    # Step 3: Run reconciliation
    mock_recon_conn.return_value.fetchrow.side_effect = [
        _DictRecord({"total": 1000}),  # baseline
        _DictRecord({"total": 1000}),  # candidate
        _DictRecord({"total": 500}),  # baseline 2
        _DictRecord({"total": 510}),  # candidate 2
    ]
    test_cases = [
        {
            "key": "revenue_exact",
            "title": "Revenue Total",
            "baseline_query": "SELECT SUM(x) as total FROM old",
            "candidate_query": "SELECT SUM(x) as total FROM new",
            "tolerance_type": "exact",
            "tolerance_value": 0,
        },
        {
            "key": "count_tolerance",
            "title": "Row Count",
            "baseline_query": "SELECT COUNT(*) as total FROM old",
            "candidate_query": "SELECT COUNT(*) as total FROM new",
            "tolerance_type": "percentage",
            "tolerance_value": 5.0,
        },
    ]
    results = await run_reconciliation(ctx, uuid.uuid4(), test_cases)
    assert len(results) == 2
    assert results[0]["delta_status"] == "pass"
    assert results[1]["delta_status"] == "within_tolerance"

    # Step 4: Aggregate
    summary = compute_aggregate_summary(results)
    assert summary["total"] == 2
    assert summary["pass_pct"] == 50.0
    assert summary["tolerance_pct"] == 50.0
