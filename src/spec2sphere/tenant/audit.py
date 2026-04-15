"""Audit log middleware for Spec2Sphere.

Logs every request to the audit_log table. Non-blocking — uses
asyncio.create_task for fire-and-forget inserts.

Fields logged: tenant_id, customer_id, project_id, user_id, action,
resource_type, resource_id, policy_stack_version, details.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Optional
from uuid import UUID

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Paths to skip — health checks, static files, etc.
_SKIP_PATHS = {"/health", "/favicon.ico"}
_SKIP_PREFIXES = ("/static/", "/ui/login")


class AuditMiddleware(BaseHTTPMiddleware):
    """FastAPI/Starlette middleware that logs every request to audit_log.

    Inserts are fire-and-forget (asyncio.create_task) and never block the response.
    If the DB is unavailable, the log is silently dropped (never raises).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip non-auditable paths
        if path in _SKIP_PATHS or any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        start = time.monotonic()
        response = await call_next(request)
        duration_ms = int((time.monotonic() - start) * 1000)

        # Extract context from request state (set by AuthMiddleware / session)
        ctx = getattr(request.state, "context", None)
        tenant_id: Optional[UUID] = getattr(ctx, "tenant_id", None) if ctx else None
        customer_id: Optional[UUID] = getattr(ctx, "customer_id", None) if ctx else None
        project_id: Optional[UUID] = getattr(ctx, "project_id", None) if ctx else None
        user_id: Optional[UUID] = getattr(ctx, "user_id", None) if ctx else None
        policy_version: Optional[str] = ctx.active_policy_stack.version if ctx and ctx.active_policy_stack else None

        action = f"{request.method} {path}"
        resource_type = _classify_path(path)

        details = {
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "query_params": str(request.query_params) if request.query_params else None,
        }

        import asyncio

        asyncio.create_task(
            _insert_audit_log(
                tenant_id=tenant_id,
                customer_id=customer_id,
                project_id=project_id,
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=None,
                policy_stack_version=policy_version,
                details=details,
            )
        )

        return response


async def _insert_audit_log(
    tenant_id: Optional[UUID],
    customer_id: Optional[UUID],
    project_id: Optional[UUID],
    user_id: Optional[UUID],
    action: str,
    resource_type: Optional[str],
    resource_id: Optional[str],
    policy_stack_version: Optional[str],
    details: Optional[dict] = None,
) -> None:
    """Insert one row into audit_log. Never raises — silently drops on error."""
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return

    try:
        import asyncpg

        url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
        conn = await asyncpg.connect(url)
        try:
            await conn.execute(
                """
                INSERT INTO audit_log
                    (tenant_id, customer_id, project_id, user_id, action,
                     resource_type, resource_id, policy_stack_version, details)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
                """,
                tenant_id,
                customer_id,
                project_id,
                user_id,
                action,
                resource_type,
                resource_id,
                policy_stack_version,
                json.dumps(details or {}),
            )
        finally:
            await conn.close()
    except Exception as exc:
        logger.debug("Audit log insert failed (non-blocking): %s", exc)


async def log_event(
    action: str,
    tenant_id: Optional[UUID] = None,
    customer_id: Optional[UUID] = None,
    project_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """Programmatic audit log entry — call from business logic for important events."""
    await _insert_audit_log(
        tenant_id=tenant_id,
        customer_id=customer_id,
        project_id=project_id,
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        policy_stack_version=None,
        details=details,
    )


def _classify_path(path: str) -> str:
    """Map URL path to a resource_type label."""
    if path.startswith("/api/"):
        parts = path.split("/")
        return parts[3] if len(parts) > 3 else "api"
    if path.startswith("/ui/"):
        return "ui"
    return "system"
