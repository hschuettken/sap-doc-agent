"""Bearer-token RBAC for the dsp-ai microservice.

Issues short-lived JWTs scoped to (user_id, customer, role).
Roles: "author" (read + write), "viewer" (read-only), "widget" (scoped to one enhancement).

Usage in FastAPI endpoints:
    from .auth import require, require_author, Principal

    @router.post("/v1/enhance/{eid}")
    async def enhance(eid: str, p: Principal = Depends(require)):
        ...

    @router.post("/v1/actions/{eid}/regen")
    async def regen(eid: str, p: Principal = Depends(require_author)):
        ...
"""

from __future__ import annotations

import os
import time
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

_JWT_SECRET = os.environ.get("DSPAI_JWT_SECRET", "change-me-in-production")
_JWT_ALGO = "HS256"


class Principal(BaseModel):
    user_id: str
    customer: str
    role: str  # "author" | "viewer" | "widget"
    exp: int


def issue_token(
    user_id: str,
    customer: str,
    role: str,
    ttl_s: int = 3600,
) -> str:
    """Mint a signed JWT for the given principal."""
    if role not in ("author", "viewer", "widget"):
        raise ValueError(f"unknown role: {role!r}")
    payload = {
        "user_id": user_id,
        "customer": customer,
        "role": role,
        "exp": int(time.time()) + ttl_s,
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def _decode(token: str) -> dict:
    try:
        return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "invalid token")


def require(authorization: Annotated[str, Header()] = "") -> Principal:
    """Dependency: any valid bearer token (author, viewer, or widget)."""
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Bearer token required")
    data = _decode(authorization.split(" ", 1)[1])
    return Principal(**data)


def require_author(p: Principal = Depends(require)) -> Principal:
    """Dependency: bearer token with role=author."""
    if p.role != "author":
        raise HTTPException(403, "author role required")
    return p
