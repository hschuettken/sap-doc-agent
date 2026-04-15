"""FastAPI routes for workspace switching and tenant/customer/project management.

Mounted only when multi_tenant module is enabled.
All admin CRUD routes are protected with require_role("admin").
"""

from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from spec2sphere.tenant.deps import ContextDep, AdminDep
from spec2sphere.tenant.policy import invalidate_policy_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])
admin_router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Workspace switch
# ---------------------------------------------------------------------------


class WorkspaceSwitchRequest(BaseModel):
    customer_id: str
    project_id: Optional[str] = None
    environment: Optional[str] = None


@router.post("/switch")
async def switch_workspace(
    body: WorkspaceSwitchRequest,
    request: Request,
    ctx: ContextDep,
) -> dict:
    """Switch active customer/project. Clears session-scoped state.

    Returns the new active workspace summary.
    """
    try:
        customer_id = UUID(body.customer_id)
        project_id = UUID(body.project_id) if body.project_id else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid UUID: {exc}")

    # Verify the user has access to this customer
    from spec2sphere.tenant.users import get_user_customers

    customers = await get_user_customers(ctx.user_id)
    accessible_ids = {c["id"] for c in customers}
    if customer_id not in accessible_ids:
        raise HTTPException(status_code=403, detail="No access to this customer")

    # Update session
    try:
        session = request.session
    except Exception:
        raise HTTPException(status_code=400, detail="Session middleware not configured")

    session["active_customer_id"] = str(customer_id)
    session["active_project_id"] = str(project_id) if project_id else None
    if body.environment:
        session["environment"] = body.environment

    # Invalidate policy cache for new workspace
    await invalidate_policy_cache(customer_id, project_id)

    return {
        "switched": True,
        "customer_id": str(customer_id),
        "project_id": str(project_id) if project_id else None,
        "environment": body.environment or "sandbox",
    }


@router.get("/current")
async def current_workspace(ctx: ContextDep) -> dict:
    """Return the active workspace context summary."""
    return {
        "tenant_id": str(ctx.tenant_id),
        "customer_id": str(ctx.customer_id),
        "project_id": str(ctx.project_id) if ctx.project_id else None,
        "environment": ctx.environment,
        "user_id": str(ctx.user_id),
        "role": ctx.role,
        "sensitivity_level": ctx.sensitivity_level,
        "policy_version": ctx.active_policy_stack.version,
        "allowed_knowledge_layers": ctx.allowed_knowledge_layers,
    }


# ---------------------------------------------------------------------------
# Admin: Tenant CRUD
# ---------------------------------------------------------------------------


class TenantCreate(BaseModel):
    name: str
    slug: str


@admin_router.post("/tenants")
async def create_tenant(body: TenantCreate, ctx: AdminDep) -> dict:
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "INSERT INTO tenants (name, slug) VALUES ($1, $2) RETURNING id, name, slug, created_at",
            body.name,
            body.slug,
        )
        return dict(row)
    finally:
        await conn.close()


@admin_router.get("/tenants")
async def list_tenants(ctx: AdminDep) -> list:
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        rows = await conn.fetch("SELECT id, name, slug, created_at FROM tenants ORDER BY name")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Admin: Customer CRUD
# ---------------------------------------------------------------------------


class CustomerCreate(BaseModel):
    tenant_id: str
    name: str
    slug: str
    branding: Optional[dict] = None
    policy_overrides: Optional[dict] = None


@admin_router.post("/customers")
async def create_customer(body: CustomerCreate, ctx: AdminDep) -> dict:
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """INSERT INTO customers (tenant_id, name, slug, branding, policy_overrides)
               VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
               RETURNING id, tenant_id, name, slug, created_at""",
            UUID(body.tenant_id),
            body.name,
            body.slug,
            json.dumps(body.branding or {}),
            json.dumps(body.policy_overrides or {}),
        )
        return dict(row)
    finally:
        await conn.close()


@admin_router.get("/customers")
async def list_customers(ctx: AdminDep) -> list:
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        rows = await conn.fetch("SELECT id, tenant_id, name, slug, created_at FROM customers ORDER BY name")
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Admin: Project CRUD
# ---------------------------------------------------------------------------


class ProjectCreate(BaseModel):
    customer_id: str
    name: str
    slug: str
    environment: str = "sandbox"
    config: Optional[dict] = None


@admin_router.post("/projects")
async def create_project(body: ProjectCreate, ctx: AdminDep) -> dict:
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """INSERT INTO projects (customer_id, name, slug, environment, config)
               VALUES ($1, $2, $3, $4, $5::jsonb)
               RETURNING id, customer_id, name, slug, environment, status, created_at""",
            UUID(body.customer_id),
            body.name,
            body.slug,
            body.environment,
            json.dumps(body.config or {}),
        )
        return dict(row)
    finally:
        await conn.close()


@admin_router.get("/projects")
async def list_projects(ctx: AdminDep, customer_id: Optional[str] = None) -> list:
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        if customer_id:
            rows = await conn.fetch(
                "SELECT id, customer_id, name, slug, environment, status, created_at FROM projects WHERE customer_id = $1 ORDER BY name",
                UUID(customer_id),
            )
        else:
            rows = await conn.fetch(
                "SELECT id, customer_id, name, slug, environment, status, created_at FROM projects ORDER BY name"
            )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Workspace switcher UI component (HTMX partial)
# ---------------------------------------------------------------------------

ui_router = APIRouter(prefix="/ui/workspace", tags=["workspace-ui"], include_in_schema=False)


@ui_router.get("/switcher", response_class=HTMLResponse)
async def workspace_switcher_component(ctx: ContextDep) -> str:
    """Return the workspace switcher HTML component (HTMX partial)."""
    from spec2sphere.tenant.users import get_user_customers
    from spec2sphere.db import _get_conn

    try:
        customers = await get_user_customers(ctx.user_id)
    except Exception:
        customers = []

    projects = []
    if ctx.customer_id and customers:
        try:
            conn = await _get_conn()
            try:
                rows = await conn.fetch(
                    "SELECT id, name, slug, environment FROM projects WHERE customer_id = $1 AND status = 'active' ORDER BY name",
                    ctx.customer_id,
                )
                projects = [dict(r) for r in rows]
            finally:
                await conn.close()
        except Exception:
            pass

    env_badge_colors = {
        "sandbox": "#6b7280",
        "test": "#d97706",
        "production": "#dc2626",
    }
    env_color = env_badge_colors.get(ctx.environment, "#6b7280")

    # Build customer options
    customer_options = (
        "".join(
            f'<option value="{c["id"]}" {"selected" if str(c["id"]) == str(ctx.customer_id) else ""}>{c["name"]}</option>'
            for c in customers
        )
        or f'<option value="{ctx.customer_id}" selected>Default Customer</option>'
    )

    project_options = '<option value="">— No project —</option>' + "".join(
        f'<option value="{p["id"]}" {"selected" if ctx.project_id and str(p["id"]) == str(ctx.project_id) else ""}>{p["name"]} ({p["environment"]})</option>'
        for p in projects
    )

    active_customer_name = next(
        (c["name"] for c in customers if str(c["id"]) == str(ctx.customer_id)),
        "Default",
    )
    active_project_name = next(
        (p["name"] for p in projects if ctx.project_id and str(p["id"]) == str(ctx.project_id)),
        None,
    )

    return f"""
<div class="workspace-switcher" style="display:flex;align-items:center;gap:0.75rem;font-family:Inter,sans-serif;font-size:0.8125rem;">
  <div class="ws-active" style="display:flex;align-items:center;gap:0.5rem;">
    <span style="font-weight:600;color:#05415A;">{active_customer_name}</span>
    {f'<span style="color:#6b7280;">/ {active_project_name}</span>' if active_project_name else ""}
    <span style="background:{env_color};color:#fff;font-size:0.6875rem;font-weight:600;padding:0.125rem 0.5rem;border-radius:9999px;text-transform:uppercase;">{ctx.environment}</span>
    <span style="background:#e0f2fe;color:#05415A;font-size:0.6875rem;padding:0.125rem 0.5rem;border-radius:9999px;">{ctx.role}</span>
  </div>
  <details style="position:relative;">
    <summary style="cursor:pointer;list-style:none;color:#05415A;font-weight:500;padding:0.25rem 0.5rem;border:1px solid #E5E5E5;border-radius:4px;background:#fff;">
      Switch ▾
    </summary>
    <div style="position:absolute;right:0;top:calc(100% + 4px);background:#fff;border:1px solid #E5E5E5;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,0.12);padding:1rem;min-width:280px;z-index:100;">
      <form
        hx-post="/api/workspace/switch"
        hx-target=".workspace-switcher"
        hx-swap="outerHTML"
        hx-on::after-request="if(event.detail.successful) window.location.reload()"
        style="display:flex;flex-direction:column;gap:0.75rem;"
      >
        <div>
          <label style="font-size:0.75rem;font-weight:600;color:#6b7280;display:block;margin-bottom:0.25rem;">CUSTOMER</label>
          <select name="customer_id" style="width:100%;padding:0.4rem 0.5rem;border:1px solid #E5E5E5;border-radius:4px;font-size:0.8125rem;">
            {customer_options}
          </select>
        </div>
        <div>
          <label style="font-size:0.75rem;font-weight:600;color:#6b7280;display:block;margin-bottom:0.25rem;">PROJECT</label>
          <select name="project_id" style="width:100%;padding:0.4rem 0.5rem;border:1px solid #E5E5E5;border-radius:4px;font-size:0.8125rem;">
            {project_options}
          </select>
        </div>
        <button type="submit" style="background:#05415A;color:#fff;border:none;padding:0.4rem 0.75rem;border-radius:4px;font-size:0.8125rem;font-weight:500;cursor:pointer;">
          Switch Workspace
        </button>
      </form>
    </div>
  </details>
</div>
"""


def create_workspace_router():
    """Return a combined router for workspace API + admin + UI."""
    combined = APIRouter()
    combined.include_router(router)
    combined.include_router(admin_router)
    combined.include_router(ui_router)
    return combined
