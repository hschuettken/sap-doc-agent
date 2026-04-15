"""Tests for ContextEnvelope, ScopedQuery, and single-tenant fallback."""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest

from spec2sphere.tenant.context import (
    ContextEnvelope,
    ResolvedPolicyStack,
    ScopedQuery,
    _is_multi_tenant,
)


TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
CUSTOMER_ID = UUID("20000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("30000000-0000-0000-0000-000000000001")
USER_ID = UUID("40000000-0000-0000-0000-000000000001")


def _make_policy() -> ResolvedPolicyStack:
    return ResolvedPolicyStack(
        layers=["platform_base", "horvath_defaults"],
        rules={"audit_all_requests": True, "default_sensitivity": "internal"},
        version="abc12345",
    )


def _make_ctx(project_id=None) -> ContextEnvelope:
    return ContextEnvelope(
        tenant_id=TENANT_ID,
        customer_id=CUSTOMER_ID,
        project_id=project_id,
        environment="sandbox",
        user_id=USER_ID,
        role="architect",
        allowed_knowledge_layers=["global", "customer", "project"],
        allowed_connectors=["dsp", "sac"],
        active_policy_stack=_make_policy(),
        active_design_profile=None,
        sensitivity_level="internal",
        trace_id=str(uuid.uuid4()),
    )


class TestContextEnvelope:
    def test_basic_fields(self):
        ctx = _make_ctx()
        assert ctx.tenant_id == TENANT_ID
        assert ctx.customer_id == CUSTOMER_ID
        assert ctx.environment == "sandbox"
        assert ctx.role == "architect"

    def test_single_tenant_factory(self):
        ctx = ContextEnvelope.single_tenant(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
        )
        assert ctx.tenant_id == TENANT_ID
        assert ctx.customer_id == CUSTOMER_ID
        assert ctx.project_id is None
        assert ctx.role == "admin"
        assert ctx.environment == "sandbox"
        assert "global" in ctx.allowed_knowledge_layers

    def test_single_tenant_policy_populated(self):
        ctx = ContextEnvelope.single_tenant(
            tenant_id=TENANT_ID,
            customer_id=CUSTOMER_ID,
        )
        assert ctx.active_policy_stack is not None
        assert ctx.active_policy_stack.version != "0"
        assert ctx.active_policy_stack.get("audit_all_requests") is True

    def test_trace_id_unique(self):
        ctx1 = ContextEnvelope.single_tenant(TENANT_ID, CUSTOMER_ID)
        ctx2 = ContextEnvelope.single_tenant(TENANT_ID, CUSTOMER_ID)
        assert ctx1.trace_id != ctx2.trace_id


class TestScopedQuery:
    def test_tenant_scope(self):
        ctx = _make_ctx()
        sq = ScopedQuery(ctx)
        conditions, params = sq.tenant()
        assert len(conditions) == 1
        assert "tenant_id" in conditions[0]
        assert params == [TENANT_ID]

    def test_tenant_customer_scope(self):
        ctx = _make_ctx()
        sq = ScopedQuery(ctx)
        conditions, params = sq.tenant_customer()
        assert len(conditions) == 2
        assert "tenant_id" in conditions[0]
        assert "customer_id" in conditions[1]
        assert params == [TENANT_ID, CUSTOMER_ID]

    def test_full_scope_with_project(self):
        ctx = _make_ctx(project_id=PROJECT_ID)
        sq = ScopedQuery(ctx)
        conditions, params = sq.tenant_customer_project()
        assert len(conditions) == 3
        assert PROJECT_ID in params

    def test_full_scope_without_project(self):
        ctx = _make_ctx()
        sq = ScopedQuery(ctx)
        conditions, params = sq.tenant_customer_project()
        # project_id is None so only 2 conditions
        assert len(conditions) == 2

    def test_require_project_raises_without_it(self):
        ctx = _make_ctx()
        sq = ScopedQuery(ctx)
        with pytest.raises(ValueError, match="project_id is required"):
            sq.tenant_customer_project(require_project=True)

    def test_project_only(self):
        ctx = _make_ctx(project_id=PROJECT_ID)
        sq = ScopedQuery(ctx)
        conditions, params = sq.project_only()
        assert "project_id" in conditions[0]
        assert params == [PROJECT_ID]

    def test_project_only_raises_without_project(self):
        ctx = _make_ctx()
        sq = ScopedQuery(ctx)
        with pytest.raises(ValueError):
            sq.project_only()

    def test_customer_only(self):
        ctx = _make_ctx()
        sq = ScopedQuery(ctx)
        conditions, params = sq.customer_only()
        assert "customer_id" in conditions[0]
        assert params == [CUSTOMER_ID]

    def test_param_start_offset(self):
        ctx = _make_ctx()
        sq = ScopedQuery(ctx)
        conditions, params = sq.tenant_customer(param_start=3)
        assert "$3" in conditions[0]
        assert "$4" in conditions[1]

    def test_build_where(self):
        ctx = _make_ctx()
        sq = ScopedQuery(ctx)
        scope_conditions, _ = sq.tenant_customer()
        extra = ["status = $3"]
        where = sq.build_where(extra, scope_conditions)
        assert where.startswith("WHERE")
        assert "tenant_id" in where
        assert "status" in where


class TestIsMultiTenant:
    def test_default_false(self, monkeypatch):
        monkeypatch.delenv("MULTI_TENANT", raising=False)
        assert _is_multi_tenant() is False

    def test_true_when_set(self, monkeypatch):
        monkeypatch.setenv("MULTI_TENANT", "true")
        assert _is_multi_tenant() is True

    def test_false_values(self, monkeypatch):
        for val in ("0", "false", "no", ""):
            monkeypatch.setenv("MULTI_TENANT", val)
            assert _is_multi_tenant() is False


class TestResolvedPolicyStack:
    def test_get_existing_key(self):
        stack = _make_policy()
        assert stack.get("audit_all_requests") is True

    def test_get_missing_key_default(self):
        stack = _make_policy()
        assert stack.get("nonexistent", "fallback") == "fallback"

    def test_layers_provenance(self):
        stack = _make_policy()
        assert "platform_base" in stack.layers
        assert "horvath_defaults" in stack.layers
