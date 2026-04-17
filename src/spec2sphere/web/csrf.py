"""CSRF protection for HTMX mutating requests.

Double-submit cookie pattern:
- Every response sets `csrf_token` cookie (non-httponly so JS/HTMX can read it).
- Every POST/PUT/PATCH/DELETE request must send header `X-CSRF-Token` that
  matches the cookie (constant-time compare).
- Base template hooks into `htmx:configRequest` to attach the header
  automatically.

Skips:
- `/api/*` routes with `Authorization: Bearer` (agent/service calls authenticated
  via bearer token, not session cookie — CSRF doesn't apply to them).
- `/mcp/*` and `/copilot/*` (unauthenticated crawler/agent endpoints).
- Login POST (session doesn't exist yet; origin checked via samesite cookie).
- Safe methods (GET, HEAD, OPTIONS).
"""

from __future__ import annotations

import hmac
import logging
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

_SKIP_PATH_PREFIXES = (
    "/mcp/",
    "/copilot",
    "/static/",
    "/healthz",
    "/health",
    "/api/browser/health",
    "/api/copilot/agent/",
)


def _is_bearer_authenticated(request: Request) -> bool:
    auth = request.headers.get("authorization", "")
    return auth.lower().startswith("bearer ")


def _has_session_cookie(request: Request) -> bool:
    """CSRF only matters when there's a session cookie to steal. Without one,
    the request is unauthenticated and auth middleware handles rejection."""
    return bool(request.cookies.get("session"))


def _is_setup_wizard(request: Request) -> bool:
    return request.url.path.startswith("/ui/setup")


def _is_login(request: Request) -> bool:
    return request.url.path == "/ui/login"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Enforces double-submit CSRF on mutating requests."""

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path
        method = request.method.upper()

        needs_check = (
            method not in SAFE_METHODS
            and not any(path.startswith(p) for p in _SKIP_PATH_PREFIXES)
            and not _is_bearer_authenticated(request)
            and not _is_setup_wizard(request)
            and not _is_login(request)
            and _has_session_cookie(request)
        )

        if needs_check:
            cookie_tok = request.cookies.get(CSRF_COOKIE, "")
            header_tok = request.headers.get(CSRF_HEADER, "")
            if not cookie_tok or not header_tok or not hmac.compare_digest(cookie_tok, header_tok):
                logger.warning(
                    "CSRF reject: %s %s — cookie=%s header=%s",
                    method,
                    path,
                    bool(cookie_tok),
                    bool(header_tok),
                )
                return JSONResponse({"detail": "CSRF validation failed"}, status_code=403)

        response = await call_next(request)

        if not request.cookies.get(CSRF_COOKIE):
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                CSRF_COOKIE,
                token,
                httponly=False,
                samesite="strict",
                max_age=86400,
                path="/",
            )

        return response
