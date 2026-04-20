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


@ui_router.get("/switcher")
async def workspace_switcher_component(request: Request):
    """Return the workspace switcher HTML component (HTMX partial).

    Returns 204 No Content when the user has no active workspace session so
    the HTMX call on every page-load doesn't spam the browser console with 401s.
    """
    from fastapi.responses import Response  # noqa: PLC0415
    from spec2sphere.tenant.deps import get_context  # noqa: PLC0415
    from spec2sphere.tenant.users import get_user_customers  # noqa: PLC0415
    from spec2sphere.db import _get_conn  # noqa: PLC0415

    try:
        ctx = await get_context(request)
    except HTTPException:
        return Response(status_code=204)

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


# ---------------------------------------------------------------------------
# Admin HTMX table partials (no auth guard — protected by the auth middleware)
# ---------------------------------------------------------------------------

admin_ui_router = APIRouter(prefix="/ui/admin", tags=["admin-ui"], include_in_schema=False)


@admin_ui_router.get("/tenants-table", response_class=HTMLResponse)
async def tenants_table() -> str:
    """Return HTML table rows for the tenants admin section."""
    from spec2sphere.db import _get_conn

    try:
        conn = await _get_conn()
        try:
            rows = await conn.fetch("SELECT id, name, slug, created_at FROM tenants ORDER BY name")
            tenants = [dict(r) for r in rows]
        finally:
            await conn.close()
    except Exception as exc:
        return f'<tr><td colspan="3" class="px-4 py-3 text-sm text-red-500">Error loading tenants: {exc}</td></tr>'

    if not tenants:
        return '<tr><td colspan="3" class="px-4 py-3 text-sm text-gray-400 italic">No tenants yet.</td></tr>'

    html = ""
    for t in tenants:
        html += (
            f'<tr class="border-t border-[#E5E5E5] hover:bg-[#F5F5F5]">'
            f'<td class="px-4 py-2.5 text-sm font-medium text-[#1a2332]">{t["name"]}</td>'
            f'<td class="px-4 py-2.5 text-sm text-gray-500 font-mono">{t["slug"]}</td>'
            f'<td class="px-4 py-2.5 text-xs text-gray-400">{str(t["created_at"])[:10] if t.get("created_at") else ""}</td>'
            f"</tr>"
        )
    return html


@admin_ui_router.get("/customers-table", response_class=HTMLResponse)
async def customers_table() -> str:
    """Return HTML table rows for the customers admin section."""
    from spec2sphere.db import _get_conn

    try:
        conn = await _get_conn()
        try:
            rows = await conn.fetch(
                """SELECT c.id, c.name, c.slug, c.created_at, t.name AS tenant_name
                   FROM customers c LEFT JOIN tenants t ON t.id = c.tenant_id
                   ORDER BY c.name"""
            )
            customers = [dict(r) for r in rows]
        finally:
            await conn.close()
    except Exception as exc:
        return f'<tr><td colspan="4" class="px-4 py-3 text-sm text-red-500">Error loading customers: {exc}</td></tr>'

    if not customers:
        return '<tr><td colspan="4" class="px-4 py-3 text-sm text-gray-400 italic">No customers yet.</td></tr>'

    html = ""
    for c in customers:
        html += (
            f'<tr class="border-t border-[#E5E5E5] hover:bg-[#F5F5F5]">'
            f'<td class="px-4 py-2.5 text-xs text-gray-400">{c.get("tenant_name", "")}</td>'
            f'<td class="px-4 py-2.5 text-sm font-medium text-[#1a2332]">{c["name"]}</td>'
            f'<td class="px-4 py-2.5 text-sm text-gray-500 font-mono">{c["slug"]}</td>'
            f'<td class="px-4 py-2.5 text-xs text-gray-400">{str(c["created_at"])[:10] if c.get("created_at") else ""}</td>'
            f"</tr>"
        )
    return html


@admin_ui_router.get("/projects-table", response_class=HTMLResponse)
async def projects_table() -> str:
    """Return HTML table rows for the projects admin section."""
    from spec2sphere.db import _get_conn

    try:
        conn = await _get_conn()
        try:
            rows = await conn.fetch(
                """SELECT p.id, p.name, p.slug, p.environment, p.status, p.created_at,
                          c.name AS customer_name
                   FROM projects p LEFT JOIN customers c ON c.id = p.customer_id
                   ORDER BY p.name"""
            )
            projects = [dict(r) for r in rows]
        finally:
            await conn.close()
    except Exception as exc:
        return f'<tr><td colspan="5" class="px-4 py-3 text-sm text-red-500">Error loading projects: {exc}</td></tr>'

    if not projects:
        return '<tr><td colspan="5" class="px-4 py-3 text-sm text-gray-400 italic">No projects yet.</td></tr>'

    env_badge = {
        "sandbox": "bg-gray-100 text-gray-600",
        "test": "bg-amber-50 text-amber-700",
        "production": "bg-red-50 text-red-700",
    }
    status_badge = {
        "active": "bg-green-50 text-green-700",
        "archived": "bg-gray-100 text-gray-500",
        "draft": "bg-blue-50 text-blue-700",
    }

    html = ""
    for p in projects:
        env = p.get("environment", "sandbox")
        status = p.get("status", "draft")
        env_cls = env_badge.get(env, "bg-gray-100 text-gray-600")
        status_cls = status_badge.get(status, "bg-gray-100 text-gray-500")
        html += (
            f'<tr class="border-t border-[#E5E5E5] hover:bg-[#F5F5F5]">'
            f'<td class="px-4 py-2.5 text-xs text-gray-400">{p.get("customer_name", "")}</td>'
            f'<td class="px-4 py-2.5 text-sm font-medium text-[#1a2332]">{p["name"]}</td>'
            f'<td class="px-4 py-2.5 text-sm text-gray-500 font-mono">{p["slug"]}</td>'
            f'<td class="px-4 py-2.5"><span class="px-2 py-0.5 rounded-full text-xs font-medium {env_cls}">{env}</span></td>'
            f'<td class="px-4 py-2.5"><span class="px-2 py-0.5 rounded-full text-xs font-medium {status_cls}">{status}</span></td>'
            f"</tr>"
        )
    return html


def create_workspace_router():
    """Return a combined router for workspace API + admin + UI."""
    combined = APIRouter()
    combined.include_router(router)
    combined.include_router(admin_router)
    combined.include_router(ui_router)
    combined.include_router(admin_ui_router)
    return combined
