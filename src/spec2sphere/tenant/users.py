"""User model, RBAC, and user management for Spec2Sphere.

In single-tenant mode, user management is optional — the single-password
auth middleware from web/auth.py remains the default.

In multi-tenant mode, users log in with email + password and are associated
with one or more customers via user_customer_access.
"""

from __future__ import annotations

import logging
import os
from typing import Optional
from uuid import UUID

import bcrypt

logger = logging.getLogger(__name__)

VALID_ROLES = {"admin", "architect", "consultant", "developer", "reviewer", "viewer"}


def hash_password(password: str) -> str:
    """Hash a password using bcrypt."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its bcrypt hash."""
    return bcrypt.checkpw(password.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# DB operations (asyncpg)
# ---------------------------------------------------------------------------


async def create_user(
    email: str,
    password: str,
    display_name: Optional[str] = None,
    role: str = "consultant",
) -> dict:
    """Create a new user. Returns the created user dict."""
    from spec2sphere.db import _get_conn

    if role not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role}. Must be one of {VALID_ROLES}")

    password_hash = hash_password(password)
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """
            INSERT INTO users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, $4)
            RETURNING id, email, display_name, role, created_at
            """,
            email,
            password_hash,
            display_name or email.split("@")[0],
            role,
        )
        return dict(row)
    finally:
        await conn.close()


async def get_user_by_email(email: str) -> Optional[dict]:
    """Fetch a user by email. Returns None if not found."""
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", email)
        return dict(row) if row else None
    finally:
        await conn.close()


async def get_user_by_id(user_id: UUID) -> Optional[dict]:
    """Fetch a user by ID. Returns None if not found."""
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return dict(row) if row else None
    finally:
        await conn.close()


async def authenticate_user(email: str, password: str) -> Optional[dict]:
    """Authenticate user by email+password. Returns user dict on success, None on failure."""
    user = await get_user_by_email(email)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


async def grant_customer_access(
    user_id: UUID,
    customer_id: UUID,
    role_override: Optional[str] = None,
) -> None:
    """Grant a user access to a customer, optionally with a role override."""
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        await conn.execute(
            """
            INSERT INTO user_customer_access (user_id, customer_id, role_override)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, customer_id) DO UPDATE SET role_override = EXCLUDED.role_override
            """,
            user_id,
            customer_id,
            role_override,
        )
    finally:
        await conn.close()


async def get_user_customers(user_id: UUID) -> list[dict]:
    """Return all customers a user has access to, with their effective role."""
    from spec2sphere.db import _get_conn

    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT c.id, c.name, c.slug, c.branding,
                   COALESCE(uca.role_override, u.role) AS effective_role
            FROM user_customer_access uca
            JOIN customers c ON c.id = uca.customer_id
            JOIN users u ON u.id = uca.user_id
            WHERE uca.user_id = $1
            ORDER BY c.name
            """,
            user_id,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def ensure_admin_user() -> dict:
    """Ensure at least one admin user exists (for bootstrap).

    Uses ADMIN_EMAIL + ADMIN_PASSWORD env vars, or defaults.
    Returns the admin user dict.
    """
    email = os.environ.get("ADMIN_EMAIL", "admin@spec2sphere.local")
    password = os.environ.get("ADMIN_PASSWORD", "spec2sphere")

    user = await get_user_by_email(email)
    if user:
        return user

    logger.info("Creating bootstrap admin user: %s", email)
    return await create_user(email=email, password=password, display_name="Admin", role="admin")
