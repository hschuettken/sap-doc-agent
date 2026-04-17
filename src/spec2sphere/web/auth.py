"""Simple password authentication middleware for the web UI."""

from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response


SESSION_MAX_AGE = 86400  # 24 hours

_LOGIN_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Inter', sans-serif; background: #F5F5F5; color: #353434; display: flex; align-items: center; justify-content: center; min-height: 100vh; }
.login-card { background: #fff; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); padding: 2.5rem; width: 360px; }
.login-card h1 { font-family: Georgia, serif; color: #05415A; font-size: 1.5rem; margin-bottom: 0.25rem; }
.login-card p { color: #6b7280; font-size: 0.875rem; margin-bottom: 1.5rem; }
.login-card label { display: block; font-size: 0.75rem; font-weight: 600; color: #6b7280; margin-bottom: 0.25rem; }
.login-card input { width: 100%; padding: 0.625rem 0.75rem; border: 1px solid #E5E5E5; border-radius: 4px; font-size: 0.875rem; margin-bottom: 1rem; }
.login-card input:focus { outline: none; border-color: #05415A; box-shadow: 0 0 0 2px rgba(5,65,90,0.15); }
.login-card button { width: 100%; padding: 0.625rem; background: #05415A; color: #fff; border: none; border-radius: 4px; font-size: 0.875rem; font-weight: 500; cursor: pointer; }
.login-card button:hover { background: #032d3e; }
.error { color: #DC2626; font-size: 0.8125rem; margin-bottom: 0.75rem; }
"""

_LOGIN_HEAD = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Login \u2014 Spec2Sphere</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>{css}</style></head><body>"""


def _build_login_html(error: str = "", multi_tenant: bool = False) -> str:
    """Return the full login page HTML, switching form based on mode."""
    head = _LOGIN_HEAD.format(css=_LOGIN_CSS)
    if multi_tenant:
        form_body = f"""<form class="login-card" method="post" action="/ui/login">
<h1>Spec2Sphere</h1>
<p>Sign in with your account</p>
{error}
<label for="email">Email</label>
<input type="email" id="email" name="email" placeholder="you@example.com" autofocus required>
<label for="password">Password</label>
<input type="password" id="password" name="password" placeholder="Password" required>
<button type="submit">Sign In</button>
</form>"""
    else:
        form_body = f"""<form class="login-card" method="post" action="/ui/login">
<h1>Spec2Sphere</h1>
<p>Enter password to continue</p>
{error}
<input type="password" name="password" placeholder="Password" autofocus required>
<button type="submit">Sign In</button>
</form>"""
    return head + form_body + "</body></html>"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def _is_multi_tenant() -> bool:
    return os.environ.get("MULTI_TENANT", "").lower() == "true"


class AuthMiddleware(BaseHTTPMiddleware):
    """Protects /ui/* routes with a session cookie. Bypasses /api/*, /static/*, /health, /sitemap.xml.

    Supports two modes:
    - Single-tenant (MULTI_TENANT != true): single-password form.
    - Multi-tenant (MULTI_TENANT == true): email+password form backed by users table.
    """

    def __init__(self, app, password_hash: str, secret_key: str = "change-me"):
        super().__init__(app)
        self.password_hash = password_hash
        self.serializer = URLSafeTimedSerializer(secret_key)

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Bypass: non-UI routes
        if not path.startswith("/ui"):
            return await call_next(request)

        multi_tenant = _is_multi_tenant()

        # Allow login page and POST
        if path == "/ui/login":
            if request.method == "POST":
                if multi_tenant:
                    return await self._handle_mt_login(request)
                return await self._handle_login(request)
            return HTMLResponse(_build_login_html(multi_tenant=multi_tenant))

        # Check session cookie
        session_cookie = request.cookies.get("session")
        if not session_cookie:
            return RedirectResponse("/ui/login", status_code=307)

        try:
            data = self.serializer.loads(session_cookie, max_age=SESSION_MAX_AGE)
            request.state.user_role = data.get("role", "admin")
            # Expose full session dict so deps.py get_context() can read it
            request.state.session = data
        except (BadSignature, SignatureExpired):
            return RedirectResponse("/ui/login", status_code=307)

        return await call_next(request)

    async def _handle_login(self, request: Request) -> Response:
        """Single-tenant: password-only login."""
        form = await request.form()
        password = form.get("password", "")
        if verify_password(password, self.password_hash):
            token = self.serializer.dumps({"role": "admin", "t": int(time.time())})
            response = RedirectResponse("/ui/dashboard", status_code=303)
            response.set_cookie("session", token, httponly=True, max_age=SESSION_MAX_AGE, samesite="lax")
            return response
        return HTMLResponse(
            _build_login_html(
                error='<p class="error">Invalid password</p>',
                multi_tenant=False,
            )
        )

    async def _handle_mt_login(self, request: Request) -> Response:
        """Multi-tenant: email+password login via users table."""
        form = await request.form()
        email = str(form.get("email", "")).strip()
        password = str(form.get("password", ""))

        def _bad(msg: str) -> Response:
            return HTMLResponse(
                _build_login_html(
                    error=f'<p class="error">{msg}</p>',
                    multi_tenant=True,
                )
            )

        if not email or not password:
            return _bad("Email and password are required")

        try:
            from spec2sphere.tenant.users import authenticate_user, ensure_admin_user, get_user_customers

            # Bootstrap admin on first login attempt
            try:
                await ensure_admin_user()
            except Exception as exc:  # noqa: BLE001
                logger.warning("ensure_admin_user failed (continuing anyway): %s", exc)

            user = await authenticate_user(email, password)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Login flow failed for %s: %s", email, exc)
            return _bad("Login service unavailable")

        if not user:
            return _bad("Invalid email or password")

        # Fetch first accessible customer to set as active
        active_customer_id = ""
        tenant_id = ""
        try:
            customers = await get_user_customers(user["id"])
            if customers:
                first = customers[0]
                active_customer_id = str(first["id"])
                # Resolve tenant from customer
                from spec2sphere.db import _get_conn

                conn = await _get_conn()
                try:
                    row = await conn.fetchrow("SELECT tenant_id FROM customers WHERE id = $1", first["id"])
                    if row:
                        tenant_id = str(row["tenant_id"])
                finally:
                    await conn.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to resolve active customer/tenant for %s: %s", email, exc)

        # Fall back to default tenant if none found
        if not tenant_id:
            try:
                from spec2sphere.tenant.context import _DEFAULT_TENANT_ID

                if _DEFAULT_TENANT_ID:
                    tenant_id = str(_DEFAULT_TENANT_ID)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not resolve default tenant id: %s", exc)

        session_data = {
            "user_id": str(user["id"]),
            "role": user.get("role", "consultant"),
            "tenant_id": tenant_id,
            "active_customer_id": active_customer_id,
            "t": int(time.time()),
        }
        token = self.serializer.dumps(session_data)
        response = RedirectResponse("/ui/dashboard", status_code=303)
        response.set_cookie("session", token, httponly=True, max_age=SESSION_MAX_AGE, samesite="lax")
        return response
