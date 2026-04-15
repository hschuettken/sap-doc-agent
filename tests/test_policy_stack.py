"""Tests for the Policy Stack Engine."""

from __future__ import annotations

from uuid import UUID

import pytest

from spec2sphere.tenant.policy import (
    _PLATFORM_BASE,
    _HORVATH_DEFAULTS,
    _deep_merge,
    resolve_policy,
    _cache_key,
)


CUSTOMER_ID = UUID("20000000-0000-0000-0000-000000000001")
PROJECT_ID = UUID("30000000-0000-0000-0000-000000000001")


class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99, "c": 3}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_nested_merge(self):
        base = {"x": {"a": 1, "b": 2}}
        override = {"x": {"b": 99, "c": 3}}
        result = _deep_merge(base, override)
        assert result == {"x": {"a": 1, "b": 99, "c": 3}}

    def test_does_not_mutate_base(self):
        base = {"a": 1}
        override = {"a": 2}
        result = _deep_merge(base, override)
        assert base == {"a": 1}
        assert result == {"a": 2}


class TestResolvePolicy:
    def test_base_only(self):
        stack = resolve_policy()
        assert "platform_base" in stack.layers
        assert "horvath_defaults" in stack.layers
        assert "accelerator_rules" in stack.layers
        # No customer or project layers
        assert "customer_overrides" not in stack.layers
        assert "project_exceptions" not in stack.layers

    def test_all_platform_base_keys_present(self):
        stack = resolve_policy()
        for key in _PLATFORM_BASE:
            assert key in stack.rules, f"Missing key: {key}"

    def test_all_horvath_defaults_present(self):
        stack = resolve_policy()
        for key in _HORVATH_DEFAULTS:
            assert key in stack.rules

    def test_customer_overrides_applied(self):
        overrides = {"max_objects_per_scan": 100, "custom_key": "custom_val"}
        stack = resolve_policy(customer_overrides=overrides)
        assert stack.rules["max_objects_per_scan"] == 100
        assert stack.rules["custom_key"] == "custom_val"
        assert "customer_overrides" in stack.layers

    def test_project_policy_exceptions_applied(self):
        project_cfg = {"policy": {"confidence_threshold_deploy": 0.95}}
        stack = resolve_policy(project_config=project_cfg)
        assert stack.rules["confidence_threshold_deploy"] == 0.95
        assert "project_exceptions" in stack.layers

    def test_project_config_without_policy_key_ignored(self):
        project_cfg = {"some_other_key": "value"}
        stack = resolve_policy(project_config=project_cfg)
        assert "project_exceptions" not in stack.layers

    def test_later_layers_win(self):
        # customer overrides platform base
        overrides = {"audit_all_requests": False}
        stack = resolve_policy(customer_overrides=overrides)
        assert stack.rules["audit_all_requests"] is False

    def test_project_overrides_customer(self):
        customer_overrides = {"max_objects_per_scan": 100}
        project_cfg = {"policy": {"max_objects_per_scan": 50}}
        stack = resolve_policy(customer_overrides=customer_overrides, project_config=project_cfg)
        assert stack.rules["max_objects_per_scan"] == 50

    def test_version_is_deterministic(self):
        stack1 = resolve_policy()
        stack2 = resolve_policy()
        assert stack1.version == stack2.version

    def test_version_changes_with_overrides(self):
        stack_base = resolve_policy()
        stack_overridden = resolve_policy(customer_overrides={"new_key": True})
        assert stack_base.version != stack_overridden.version


class TestCacheKey:
    def test_with_project(self):
        key = _cache_key(CUSTOMER_ID, PROJECT_ID)
        assert str(CUSTOMER_ID) in key
        assert str(PROJECT_ID) in key

    def test_without_project(self):
        key = _cache_key(CUSTOMER_ID, None)
        assert "none" in key

    def test_format(self):
        key = _cache_key(CUSTOMER_ID, None)
        assert key.startswith("policy:")


class TestGetPolicyStack:
    @pytest.mark.asyncio
    async def test_returns_resolved_stack_without_redis(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        from spec2sphere.tenant.policy import get_policy_stack

        stack = await get_policy_stack(CUSTOMER_ID, None)
        assert stack.rules is not None
        assert "platform_base" in stack.layers

    @pytest.mark.asyncio
    async def test_customer_overrides_propagated(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        from spec2sphere.tenant.policy import get_policy_stack

        overrides = {"my_custom_rule": "enabled"}
        stack = await get_policy_stack(CUSTOMER_ID, None, customer_overrides=overrides)
        assert stack.rules["my_custom_rule"] == "enabled"
