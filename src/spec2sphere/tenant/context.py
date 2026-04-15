"""Context envelope for Spec2Sphere multi-tenant request scoping.

Every request resolves a ContextEnvelope before any business logic runs.
Single-tenant mode (multi_tenant=false) auto-uses the default tenant and
skips workspace switching — all existing endpoints work transparently.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# Sentinel: no project selected
NO_PROJECT: Optional[UUID] = None

_DEFAULT_TENANT_ID: Optional[UUID] = None
_DEFAULT_CUSTOMER_ID: Optional[UUID] = None


@dataclass
class ResolvedPolicyStack:
    """Five-layer merged policy. Later layers override earlier ones."""

    layers: list[str] = field(default_factory=list)  # names of layers that contributed
    rules: dict[str, Any] = field(default_factory=dict)
    version: str = "0"

    def get(self, key: str, default: Any = None) -> Any:
        return self.rules.get(key, default)


@dataclass
class ContextEnvelope:
    """Resolved per-request context. Injected into all DB queries, LLM calls, and tools."""

    tenant_id: UUID
    customer_id: UUID
    project_id: Optional[UUID]
    environment: str  # sandbox | test | production
    user_id: UUID
    role: str  # admin | architect | consultant | developer | reviewer | viewer
    allowed_knowledge_layers: list[str]  # ["global", "customer", "project"]
    allowed_connectors: list[str]
    active_policy_stack: ResolvedPolicyStack
    active_design_profile: Optional[str]
    sensitivity_level: str  # public | internal | confidential | restricted
    trace_id: str

    @classmethod
    def single_tenant(
        cls,
        tenant_id: UUID,
        customer_id: UUID,
        project_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        role: str = "admin",
    ) -> "ContextEnvelope":
        """Build a minimal context for single-tenant mode."""
        return cls(
            tenant_id=tenant_id,
            customer_id=customer_id,
            project_id=project_id,
            environment="sandbox",
            user_id=user_id or UUID("00000000-0000-0000-0000-000000000001"),
            role=role,
            allowed_knowledge_layers=["global", "customer", "project"],
            allowed_connectors=["dsp", "sac", "bw"],
            active_policy_stack=ResolvedPolicyStack(
                layers=["platform_base"],
                rules=_PLATFORM_BASE_RULES.copy(),
                version="1",
            ),
            active_design_profile=None,
            sensitivity_level="internal",
            trace_id=str(uuid.uuid4()),
        )


# Default platform-base policy rules
_PLATFORM_BASE_RULES: dict[str, Any] = {
    "max_objects_per_scan": 5000,
    "require_approval_for_production": True,
    "allowed_implementation_routes": ["click_guide", "api", "cdp", "csn_import", "manifest"],
    "default_sensitivity": "internal",
    "audit_all_requests": True,
    "enable_reconciliation": True,
}


class ScopedQuery:
    """Builds WHERE clauses scoped to the current context envelope.

    Usage:
        sq = ScopedQuery(ctx)
        conditions, params = sq.tenant_customer_project()
        # appends tenant_id, customer_id, project_id conditions
    """

    def __init__(self, ctx: ContextEnvelope):
        self.ctx = ctx

    def tenant(self, param_start: int = 1) -> tuple[list[str], list[Any]]:
        """Returns (conditions, params) for tenant-only scoping."""
        return [f"tenant_id = ${param_start}"], [self.ctx.tenant_id]

    def tenant_customer(self, param_start: int = 1) -> tuple[list[str], list[Any]]:
        """Returns (conditions, params) for tenant + customer scoping."""
        return (
            [f"tenant_id = ${param_start}", f"customer_id = ${param_start + 1}"],
            [self.ctx.tenant_id, self.ctx.customer_id],
        )

    def tenant_customer_project(
        self, param_start: int = 1, require_project: bool = False
    ) -> tuple[list[str], list[Any]]:
        """Returns (conditions, params) for full scoping.

        When project_id is None and require_project is False, omits project condition.
        """
        conditions = [
            f"tenant_id = ${param_start}",
            f"customer_id = ${param_start + 1}",
        ]
        params: list[Any] = [self.ctx.tenant_id, self.ctx.customer_id]
        if self.ctx.project_id is not None:
            conditions.append(f"project_id = ${param_start + 2}")
            params.append(self.ctx.project_id)
        elif require_project:
            raise ValueError("project_id is required but not set in context")
        return conditions, params

    def project_only(self, param_start: int = 1) -> tuple[list[str], list[Any]]:
        """Returns (conditions, params) for project-only scoping (no tenant column on table)."""
        if self.ctx.project_id is None:
            raise ValueError("project_id is required but not set in context")
        return [f"project_id = ${param_start}"], [self.ctx.project_id]

    def customer_only(self, param_start: int = 1) -> tuple[list[str], list[Any]]:
        """Returns (conditions, params) for customer-only scoping."""
        return [f"customer_id = ${param_start}"], [self.ctx.customer_id]

    def build_where(self, extra_conditions: list[str], conditions: list[str]) -> str:
        """Combine scope conditions with extra filter conditions into a WHERE clause."""
        all_conditions = conditions + extra_conditions
        if not all_conditions:
            return ""
        return "WHERE " + " AND ".join(all_conditions)


# ---------------------------------------------------------------------------
# Default tenant/customer bootstrapping for single-tenant mode
# ---------------------------------------------------------------------------

_bootstrap_lock = asyncio.Lock()
_bootstrap_done = False


async def _ensure_default_tenant(conn) -> tuple[UUID, UUID]:
    """Create the default tenant and customer if they don't exist yet.

    Called once at startup in single-tenant mode. Safe to call multiple times.
    Returns (tenant_id, customer_id).
    """
    global _DEFAULT_TENANT_ID, _DEFAULT_CUSTOMER_ID, _bootstrap_done

    async with _bootstrap_lock:
        if _bootstrap_done and _DEFAULT_TENANT_ID and _DEFAULT_CUSTOMER_ID:
            return _DEFAULT_TENANT_ID, _DEFAULT_CUSTOMER_ID

        try:
            row = await conn.fetchrow("SELECT id FROM tenants WHERE slug = $1", "default")
            if row:
                tenant_id = row["id"]
            else:
                row = await conn.fetchrow(
                    "INSERT INTO tenants (name, slug) VALUES ($1, $2) RETURNING id",
                    "Default",
                    "default",
                )
                tenant_id = row["id"]

            row = await conn.fetchrow(
                "SELECT id FROM customers WHERE slug = $1 AND tenant_id = $2", "default", tenant_id
            )
            if row:
                customer_id = row["id"]
            else:
                row = await conn.fetchrow(
                    "INSERT INTO customers (tenant_id, name, slug) VALUES ($1, $2, $3) RETURNING id",
                    tenant_id,
                    "Default Customer",
                    "default",
                )
                customer_id = row["id"]

            _DEFAULT_TENANT_ID = tenant_id
            _DEFAULT_CUSTOMER_ID = customer_id
            _bootstrap_done = True
            logger.info("Single-tenant mode: using tenant=%s customer=%s", tenant_id, customer_id)
            return tenant_id, customer_id

        except Exception as exc:
            logger.warning("Could not ensure default tenant (DB may be unavailable): %s", exc)
            # Return synthetic IDs so the app can still start without a DB
            fallback_tenant = UUID("10000000-0000-0000-0000-000000000001")
            fallback_customer = UUID("20000000-0000-0000-0000-000000000001")
            _DEFAULT_TENANT_ID = fallback_tenant
            _DEFAULT_CUSTOMER_ID = fallback_customer
            _bootstrap_done = True
            return fallback_tenant, fallback_customer


async def get_default_context(conn=None) -> ContextEnvelope:
    """Return a single-tenant context. Used when multi_tenant=false or no session."""
    global _DEFAULT_TENANT_ID, _DEFAULT_CUSTOMER_ID

    if _DEFAULT_TENANT_ID and _DEFAULT_CUSTOMER_ID:
        return ContextEnvelope.single_tenant(
            tenant_id=_DEFAULT_TENANT_ID,
            customer_id=_DEFAULT_CUSTOMER_ID,
        )

    if conn is not None:
        tenant_id, customer_id = await _ensure_default_tenant(conn)
        return ContextEnvelope.single_tenant(tenant_id=tenant_id, customer_id=customer_id)

    # No conn and not yet bootstrapped — use fallback IDs
    fallback_tenant = UUID("10000000-0000-0000-0000-000000000001")
    fallback_customer = UUID("20000000-0000-0000-0000-000000000001")
    return ContextEnvelope.single_tenant(
        tenant_id=fallback_tenant,
        customer_id=fallback_customer,
    )


def _is_multi_tenant() -> bool:
    """Read multi_tenant flag from environment. Defaults to false."""
    val = os.environ.get("MULTI_TENANT", "false").lower()
    return val in ("1", "true", "yes")
