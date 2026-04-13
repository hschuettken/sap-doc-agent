"""Simple password authentication middleware for the web UI."""

from __future__ import annotations

import time

import bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response


SESSION_MAX_AGE = 86400  # 24 hours

# Minimal login page HTML — styled to match Horvath brand
LOGIN_HTML = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Login \u2014 SAP Doc Agent</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: 'Inter', sans-serif; background: #F5F5F5; color: #353434; display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
.login-card {{ background: #fff; border-radius: 8px; box-shadow: 0 2px 12px rgba(0,0,0,0.1); padding: 2.5rem; width: 360px; }}
.login-card h1 {{ font-family: Georgia, serif; color: #05415A; font-size: 1.5rem; margin-bottom: 0.25rem; }}
.login-card p {{ color: #6b7280; font-size: 0.875rem; margin-bottom: 1.5rem; }}
.login-card input {{ width: 100%; padding: 0.625rem 0.75rem; border: 1px solid #E5E5E5; border-radius: 4px; font-size: 0.875rem; margin-bottom: 1rem; }}
.login-card input:focus {{ outline: none; border-color: #05415A; box-shadow: 0 0 0 2px rgba(5,65,90,0.15); }}
.login-card button {{ width: 100%; padding: 0.625rem; background: #05415A; color: #fff; border: none; border-radius: 4px; font-size: 0.875rem; font-weight: 500; cursor: pointer; }}
.login-card button:hover {{ background: #032d3e; }}
.error {{ color: #DC2626; font-size: 0.8125rem; margin-bottom: 0.75rem; }}
</style></head><body>
<form class="login-card" method="post" action="/ui/login">
<h1>SAP Doc Agent</h1>
<p>Enter password to continue</p>
{error}
<input type="password" name="password" placeholder="Password" autofocus required>
<button type="submit">Sign In</button>
</form></body></html>"""


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


class AuthMiddleware(BaseHTTPMiddleware):
    """Protects /ui/* routes with a session cookie. Bypasses /api/*, /static/*, /health, /sitemap.xml."""

    def __init__(self, app, password_hash: str, secret_key: str = "change-me"):
        super().__init__(app)
        self.password_hash = password_hash
        self.serializer = URLSafeTimedSerializer(secret_key)

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Bypass: non-UI routes
        if not path.startswith("/ui"):
            return await call_next(request)

        # Allow login page and POST
        if path == "/ui/login":
            if request.method == "POST":
                return await self._handle_login(request)
            return HTMLResponse(LOGIN_HTML.format(error=""))

        # Check session cookie
        session_cookie = request.cookies.get("session")
        if not session_cookie:
            return RedirectResponse("/ui/login", status_code=307)

        try:
            data = self.serializer.loads(session_cookie, max_age=SESSION_MAX_AGE)
            request.state.user_role = data.get("role", "admin")
        except (BadSignature, SignatureExpired):
            return RedirectResponse("/ui/login", status_code=307)

        return await call_next(request)

    async def _handle_login(self, request: Request) -> Response:
        form = await request.form()
        password = form.get("password", "")
        if verify_password(password, self.password_hash):
            token = self.serializer.dumps({"role": "admin", "t": int(time.time())})
            response = RedirectResponse("/ui/dashboard", status_code=307)
            response.set_cookie("session", token, httponly=True, max_age=SESSION_MAX_AGE, samesite="lax")
            return response
        return HTMLResponse(LOGIN_HTML.format(error='<p class="error">Invalid password</p>'))
