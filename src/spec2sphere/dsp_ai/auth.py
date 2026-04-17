"""Lightweight bearer-token auth for dsp-ai.

Three roles — issued as signed JWTs so the widget (embedded in SAC)
and Studio UI can both carry scope claims. No OAuth server in v1;
tokens are minted server-side on behalf of the logged-in user or
SAC session and handed to the widget.

Env:
  DSPAI_JWT_SECRET — HS256 signing secret (DEFAULT: 'change-me';
                     production deploys MUST set this explicitly).
  DSPAI_AUTH_ENFORCED — 'true' to require tokens on all live-adapter
                        routes (default 'false' for backwards-compat).
"""

from __future__ import annotations

import os
import time
from typing import Literal

import jwt  # PyJWT
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

_JWT_ALGO = "HS256"

Role = Literal["author", "viewer", "widget"]


def _secret() -> str:
    return os.environ.get("DSPAI_JWT_SECRET", "change-me")


def _enforced() -> bool:
    return os.environ.get("DSPAI_AUTH_ENFORCED", "false").lower() == "true"


class Principal(BaseModel):
    user_id: str
    customer: str
    role: Role
    exp: int


def issue_token(user_id: str, customer: str, role: Role, ttl_s: int = 3600) -> str:
    payload = {
        "user_id": user_id,
        "customer": customer,
        "role": role,
        "exp": int(time.time()) + ttl_s,
    }
    return jwt.encode(payload, _secret(), algorithm=_JWT_ALGO)


def decode_token(token: str) -> Principal:
    try:
        data = jwt.decode(token, _secret(), algorithms=[_JWT_ALGO])
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail=f"invalid token: {exc}") from exc
    return Principal(**data)


def require(authorization: str = Header(default="")) -> Principal:
    """Any valid bearer token."""
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.split(" ", 1)[1]
    return decode_token(token)


def require_or_anon(authorization: str = Header(default="")) -> Principal:
    """Permissive mode: anonymous widget principal if no token AND enforcement is off."""
    if not authorization:
        if _enforced():
            raise HTTPException(status_code=401, detail="missing bearer token")
        return Principal(
            user_id="anonymous",
            customer=os.environ.get("CUSTOMER", "default"),
            role="widget",
            exp=int(time.time()) + 3600,
        )
    return require(authorization=authorization)


def require_author(p: Principal = Depends(require)) -> Principal:
    """Token with role='author'. Viewers and widgets → 403."""
    if p.role != "author":
        raise HTTPException(status_code=403, detail="author role required")
    return p


def require_not_widget(p: Principal = Depends(require)) -> Principal:
    """Token with role='author' or 'viewer'. Widget tokens (minimal scope) → 403."""
    if p.role == "widget":
        raise HTTPException(status_code=403, detail="human token required")
    return p
