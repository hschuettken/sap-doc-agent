"""FastAPI dependencies for context envelope resolution and RBAC."""

from __future__ import annotations

import logging
from typing import Annotated, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status

from spec2sphere.tenant.context import ContextEnvelope, get_default_context, _is_multi_tenant
from spec2sphere.tenant.policy import get_policy_stack

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Role hierarchy — higher index = more privileged
# ---------------------------------------------------------------------------
_ROLE_LEVELS = {
    "viewer": 0,
    "reviewer": 1,
    "developer": 2,
    "consultant": 3,
    "architect": 4,
    "admin": 5,
}


def _role_level(role: str) -> int:
    return _ROLE_LEVELS.get(role, 0)


# ---------------------------------------------------------------------------
# Database connection helper (reuses asyncpg from spec2sphere.db)
# ---------------------------------------------------------------------------


async def _get_db_conn():
    """Get a raw asyncpg connection. Yields and closes."""
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        yield conn
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Context envelope resolution
# ---------------------------------------------------------------------------


async def get_context(request: Request) -> ContextEnvelope:
    """Resolve ContextEnvelope from session + URL.

    In single-tenant mode (MULTI_TENANT != true): returns the default context.
    In multi-tenant mode: reads tenant/customer/project from session.

    This dependency is optional on all existing endpoints — they all continue
    to work in single-tenant mode without any changes.
    """
    if not _is_multi_tenant():
        # Single-tenant: use the default context (no DB call needed if already bootstrapped)
        return await get_default_context()

    # Multi-tenant: resolve from session
    session = getattr(request.state, "session", {})
    if not session:
        # Try cookie-based session via starlette
        try:
            session = request.session
        except Exception:
            session = {}

    user_id_str = session.get("user_id")
    customer_id_str = session.get("active_customer_id")
    project_id_str = session.get("active_project_id")
    tenant_id_str = session.get("tenant_id")
    role = session.get("role", "viewer")

    if not user_id_str or not customer_id_str or not tenant_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No active workspace session. Please log in and select a workspace.",
        )

    try:
        tenant_id = UUID(tenant_id_str)
        customer_id = UUID(customer_id_str)
        user_id = UUID(user_id_str)
        project_id = UUID(project_id_str) if project_id_str else None
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid session IDs: {exc}",
        )

    # Fetch policy stack (customer overrides + project config from DB or cache)
    customer_overrides: Optional[dict] = None
    project_config: Optional[dict] = None

    try:
        from spec2sphere.db import _get_conn

        conn = await _get_conn()
        try:
            row = await conn.fetchrow("SELECT policy_overrides FROM customers WHERE id = $1", customer_id)
            if row:
                customer_overrides = row["policy_overrides"] or {}

            if project_id:
                prow = await conn.fetchrow("SELECT config, environment FROM projects WHERE id = $1", project_id)
                if prow:
                    project_config = prow["config"] or {}
                    environment = prow.get("environment", "sandbox")
                else:
                    environment = "sandbox"
            else:
                environment = session.get("environment", "sandbox")
        finally:
            await conn.close()
    except Exception as exc:
        logger.warning("Could not load customer/project config for policy: %s", exc)
        environment = "sandbox"

    policy_stack = await get_policy_stack(
        customer_id=customer_id,
        project_id=project_id,
        customer_overrides=customer_overrides,
        project_config=project_config,
    )

    return ContextEnvelope(
        tenant_id=tenant_id,
        customer_id=customer_id,
        project_id=project_id,
        environment=environment,
        user_id=user_id,
        role=role,
        allowed_knowledge_layers=["global", "customer", "project"] if project_id else ["global", "customer"],
        allowed_connectors=["dsp", "sac", "bw"],
        active_policy_stack=policy_stack,
        active_design_profile=session.get("design_profile"),
        sensitivity_level=policy_stack.get("default_sensitivity", "internal"),
        trace_id=str(__import__("uuid").uuid4()),
    )


# ---------------------------------------------------------------------------
# RBAC guards
# ---------------------------------------------------------------------------


def require_role(minimum_role: str):
    """FastAPI dependency factory: raise 403 if user role is below minimum_role.

    Usage:
        @app.get("/admin/...")
        async def admin_route(ctx: Annotated[ContextEnvelope, Depends(require_role("admin"))]):
            ...
    """

    async def _check(ctx: Annotated[ContextEnvelope, Depends(get_context)]) -> ContextEnvelope:
        if _role_level(ctx.role) < _role_level(minimum_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{ctx.role}' is insufficient. Required: '{minimum_role}'.",
            )
        return ctx

    return _check


def require_admin():
    """Shortcut for require_role('admin')."""
    return require_role("admin")


def require_architect():
    """Shortcut for require_role('architect')."""
    return require_role("architect")


# Type aliases for injection
ContextDep = Annotated[ContextEnvelope, Depends(get_context)]
AdminDep = Annotated[ContextEnvelope, Depends(require_role("admin"))]
ArchitectDep = Annotated[ContextEnvelope, Depends(require_role("architect"))]
