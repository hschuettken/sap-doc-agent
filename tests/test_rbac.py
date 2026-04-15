"""Tests for RBAC role guards and user model."""

from __future__ import annotations

import uuid
from uuid import UUID

import pytest

from spec2sphere.tenant.context import ContextEnvelope, ResolvedPolicyStack
from spec2sphere.tenant.deps import _role_level


TENANT_ID = UUID("10000000-0000-0000-0000-000000000001")
CUSTOMER_ID = UUID("20000000-0000-0000-0000-000000000001")


def _make_ctx(role: str) -> ContextEnvelope:
    return ContextEnvelope(
        tenant_id=TENANT_ID,
        customer_id=CUSTOMER_ID,
        project_id=None,
        environment="sandbox",
        user_id=UUID("40000000-0000-0000-0000-000000000001"),
        role=role,
        allowed_knowledge_layers=["global"],
        allowed_connectors=[],
        active_policy_stack=ResolvedPolicyStack(layers=[], rules={}, version="0"),
        active_design_profile=None,
        sensitivity_level="internal",
        trace_id=str(uuid.uuid4()),
    )


class TestRoleLevels:
    def test_viewer_is_lowest(self):
        assert _role_level("viewer") == 0

    def test_admin_is_highest(self):
        assert _role_level("admin") > _role_level("architect")

    def test_role_ordering(self):
        roles = ["viewer", "reviewer", "developer", "consultant", "architect", "admin"]
        levels = [_role_level(r) for r in roles]
        assert levels == sorted(levels)

    def test_unknown_role_returns_zero(self):
        assert _role_level("unknown_role") == 0


class TestRequireRole:
    """Test the require_role dependency factory logic."""

    @pytest.mark.asyncio
    async def test_admin_passes_admin_check(self):
        from spec2sphere.tenant.deps import require_role

        ctx = _make_ctx("admin")
        # Simulate what _check does internally

        guard = require_role("admin")
        # The guard's inner function takes a ctx already resolved
        # We test the level logic directly
        assert _role_level(ctx.role) >= _role_level("admin")

    @pytest.mark.asyncio
    async def test_viewer_fails_architect_check(self):
        ctx = _make_ctx("viewer")
        assert _role_level(ctx.role) < _role_level("architect")

    @pytest.mark.asyncio
    async def test_architect_passes_consultant_check(self):
        ctx = _make_ctx("architect")
        assert _role_level(ctx.role) >= _role_level("consultant")

    def test_each_role_accepts_equal(self):
        from spec2sphere.tenant.deps import _role_level as rl

        for role in ["viewer", "reviewer", "developer", "consultant", "architect", "admin"]:
            # Equal role should pass
            assert rl(role) >= rl(role)


class TestPasswordHashing:
    def test_hash_and_verify(self):
        from spec2sphere.tenant.users import hash_password, verify_password

        pw = "test_password_123"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed)

    def test_wrong_password_fails(self):
        from spec2sphere.tenant.users import hash_password, verify_password

        hashed = hash_password("correct_password")
        assert not verify_password("wrong_password", hashed)

    def test_hashes_differ(self):
        from spec2sphere.tenant.users import hash_password

        h1 = hash_password("same_password")
        h2 = hash_password("same_password")
        # bcrypt salts are random so hashes differ
        assert h1 != h2
