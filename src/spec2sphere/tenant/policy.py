"""Policy Stack Engine for Spec2Sphere.

Five-layer resolution:
  1. platform_base  — hardcoded defaults in this module
  2. horvath_defaults — Horvath standard rules (stored in DB or config)
  3. accelerator_rules — per-module accelerator rules
  4. customer_overrides — customers.policy_overrides (JSONB in DB)
  5. project_exceptions — projects.config (JSONB in DB)

Later layers override earlier ones. Conflicts are logged.
Resolved stack cached in Redis with key pattern: policy:{customer_id}:{project_id}
TTL: 5 minutes.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# ---- Layer 1: Platform base (immutable defaults) ----
_PLATFORM_BASE: dict[str, Any] = {
    "max_objects_per_scan": 5000,
    "require_approval_for_production": True,
    "allowed_implementation_routes": ["click_guide", "api", "cdp", "csn_import", "manifest"],
    "default_sensitivity": "internal",
    "audit_all_requests": True,
    "enable_reconciliation": True,
    "max_llm_calls_per_hour": 500,
    "default_environment": "sandbox",
    "enable_visual_qa": True,
    "confidence_threshold_deploy": 0.80,
}

# ---- Layer 2: Horvath defaults ----
_HORVATH_DEFAULTS: dict[str, Any] = {
    "naming_convention": "HOR_{DOMAIN}_{OBJECT}",
    "documentation_standard": "horvath_v2",
    "required_approval_roles": ["architect"],
    "default_layer_mapping": {"raw": "L0", "harmonized": "L1", "mart": "L2", "consumption": "L3"},
    "bw_migration_default_mode": "semantic",
    "sac_default_performance_class": "standard",
}

# ---- Layer 3: Accelerator rules (loaded from module config) ----
_ACCELERATOR_RULES: dict[str, Any] = {
    "pipeline_stages_enabled": ["intake", "hla", "tech_spec", "test_spec", "build", "deploy", "verify", "docs"],
    "auto_generate_test_spec": True,
    "reconciliation_tolerance_pct": 0.05,
    "route_fitness_min_samples": 3,
}

_POLICY_TTL_SECONDS = 300  # 5 minutes


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursively for nested dicts. Later wins."""
    result = base.copy()
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            if key in result and result[key] != val:
                logger.debug("Policy conflict on key=%s: %r -> %r", key, result[key], val)
            result[key] = val
    return result


def resolve_policy(
    customer_overrides: Optional[dict] = None,
    project_config: Optional[dict] = None,
) -> "ResolvedPolicyStack":
    """Merge all 5 layers into a single resolved policy stack.

    Args:
        customer_overrides: dict from customers.policy_overrides
        project_config: dict from projects.config (project-level exceptions)

    Returns:
        ResolvedPolicyStack with merged rules and layer provenance.
    """
    from spec2sphere.tenant.context import ResolvedPolicyStack

    layers_applied: list[str] = []
    merged: dict[str, Any] = {}

    # Layer 1
    merged = _deep_merge(merged, _PLATFORM_BASE)
    layers_applied.append("platform_base")

    # Layer 2
    merged = _deep_merge(merged, _HORVATH_DEFAULTS)
    layers_applied.append("horvath_defaults")

    # Layer 3
    merged = _deep_merge(merged, _ACCELERATOR_RULES)
    layers_applied.append("accelerator_rules")

    # Layer 4: customer overrides
    if customer_overrides:
        merged = _deep_merge(merged, customer_overrides)
        layers_applied.append("customer_overrides")

    # Layer 5: project exceptions
    if project_config:
        # Only the "policy" key within projects.config is treated as policy
        project_policy = project_config.get("policy", {})
        if project_policy:
            merged = _deep_merge(merged, project_policy)
            layers_applied.append("project_exceptions")

    import hashlib

    version = hashlib.md5(json.dumps(merged, sort_keys=True, default=str).encode()).hexdigest()[:8]

    return ResolvedPolicyStack(layers=layers_applied, rules=merged, version=version)


def _cache_key(customer_id: UUID, project_id: Optional[UUID]) -> str:
    pid = str(project_id) if project_id else "none"
    return f"policy:{customer_id}:{pid}"


async def get_policy_stack(
    customer_id: UUID,
    project_id: Optional[UUID],
    customer_overrides: Optional[dict] = None,
    project_config: Optional[dict] = None,
) -> "ResolvedPolicyStack":
    """Get resolved policy stack, using Redis cache when available.

    Falls back to direct resolution if Redis is unavailable.
    """
    redis_url = os.environ.get("REDIS_URL", "")
    cache_key = _cache_key(customer_id, project_id)

    # Try Redis cache first
    if redis_url:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(redis_url, decode_responses=True)
            cached = await r.get(cache_key)
            await r.aclose()
            if cached:
                data = json.loads(cached)
                from spec2sphere.tenant.context import ResolvedPolicyStack

                return ResolvedPolicyStack(
                    layers=data["layers"],
                    rules=data["rules"],
                    version=data["version"],
                )
        except Exception as exc:
            logger.debug("Redis cache miss for policy (will recompute): %s", exc)

    # Resolve from layers
    stack = resolve_policy(
        customer_overrides=customer_overrides,
        project_config=project_config,
    )

    # Write to cache
    if redis_url:
        try:
            import redis.asyncio as aioredis

            r = aioredis.from_url(redis_url, decode_responses=True)
            payload = json.dumps(
                {"layers": stack.layers, "rules": stack.rules, "version": stack.version},
                default=str,
            )
            await r.setex(cache_key, _POLICY_TTL_SECONDS, payload)
            await r.aclose()
        except Exception as exc:
            logger.debug("Could not cache policy in Redis: %s", exc)

    return stack


async def invalidate_policy_cache(customer_id: UUID, project_id: Optional[UUID] = None) -> None:
    """Invalidate Redis cache for a customer (and optionally a specific project)."""
    redis_url = os.environ.get("REDIS_URL", "")
    if not redis_url:
        return
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(redis_url, decode_responses=True)
        key = _cache_key(customer_id, project_id)
        await r.delete(key)
        await r.aclose()
    except Exception as exc:
        logger.debug("Could not invalidate policy cache: %s", exc)
