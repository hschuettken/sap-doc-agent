"""
OAuth 2.0 client credentials authentication for SAP Datasphere,
plus a basic-auth fallback and a factory that picks the right one from config.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
from typing import Union

import httpx


class DSPOAuthClient:
    """
    OAuth 2.0 client credentials flow for SAP Datasphere.

    Thread-safe via asyncio.Lock — safe for concurrent coroutines.
    Token is cached until (expires_in - 60 s) to avoid using a token
    that expires mid-request.
    """

    _EXPIRY_BUFFER = 60.0  # seconds before expiry to force a refresh

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        token_url: str,
        timeout: float = 30.0,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._timeout = timeout
        self._access_token: str | None = None
        self._expires_at: float = 0.0  # unix timestamp
        self._lock: asyncio.Lock = asyncio.Lock()

    async def get_token(self) -> str:
        """Return a valid access token, refreshing if expired or close to expiry."""
        async with self._lock:
            if self._access_token is None or time.time() >= (self._expires_at - self._EXPIRY_BUFFER):
                await self._refresh_token()
        return self._access_token  # type: ignore[return-value]

    async def get_headers(self) -> dict:
        """Return Authorization header dict with a valid Bearer token."""
        token = await self.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def _refresh_token(self) -> None:
        """Perform the OAuth client credentials POST and cache the result.

        Must be called while holding self._lock.
        """
        credentials = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        data = {"grant_type": "client_credentials"}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._token_url, headers=headers, data=data)

        if response.status_code != 200:
            raise RuntimeError(f"OAuth token request failed with status {response.status_code}: {response.text}")

        payload = response.json()
        self._access_token = payload["access_token"]
        expires_in = payload.get("expires_in", 3600)
        self._expires_at = time.time() + float(expires_in)

    async def invalidate(self) -> None:
        """Force a token refresh on the next get_token() call (e.g. after 401)."""
        async with self._lock:
            self._access_token = None
            self._expires_at = 0.0


# Backward-compatible alias — existing code that imports DSPAuth keeps working.
DSPAuth = DSPOAuthClient


class DSPBasicAuth:
    """
    Basic-auth wrapper that exposes the same get_headers() / invalidate()
    interface as DSPOAuthClient so DSPScanner can accept either without branching.
    """

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        # Pre-build the httpx.BasicAuth for callers that want it directly
        self._httpx_auth = httpx.BasicAuth(username=username, password=password)

    @property
    def httpx_auth(self) -> httpx.BasicAuth:
        """Return the underlying httpx.BasicAuth object (for direct use in httpx calls)."""
        return self._httpx_auth

    async def get_headers(self) -> dict:
        """Return Authorization header for Basic auth."""
        encoded = base64.b64encode(f"{self._username}:{self._password}".encode()).decode()
        return {"Authorization": f"Basic {encoded}"}

    async def invalidate(self) -> None:
        """No-op — basic auth credentials don't expire."""


# Union type accepted by DSPScanner
DSPAuthType = Union[DSPOAuthClient, DSPBasicAuth]


class DSPAuthFactory:
    """
    Builds the right auth object from a SAP system config dict.

    Config shape (mirrors YAML):

        auth:
          type: basic          # or omit — defaults to basic if no oauth section
          username: alice      # resolved value or set via username_env
          password: secret
          username_env: DSP_USER    # alternative: env var name
          password_env: DSP_PASS

        # OR:

        auth:
          type: oauth
          oauth:
            token_url: https://...
            client_id: ...        # or client_id_env
            client_secret: ...    # or client_secret_env
            token_url_env: ...

        # Presence of auth.oauth (or top-level oauth) with token_url / token_url_env
        # also implies oauth regardless of auth.type.

    The factory also accepts the existing SAPSystem-level ``oauth`` block
    (with *_env fields) for backward compatibility.
    """

    @classmethod
    def from_config(cls, config: dict) -> DSPAuthType:
        """
        Build a DSPAuthType from a plain dict (typically parsed from YAML).

        Precedence:
        1. ``auth.type == 'oauth'`` or ``auth.oauth`` sub-block present → OAuth
        2. Top-level ``oauth`` block (old style) → OAuth
        3. ``auth.type == 'basic'`` or ``auth.username*`` present → Basic
        4. No auth section → raise ValueError
        """
        auth_block: dict = config.get("auth") or {}
        top_oauth: dict = config.get("oauth") or {}

        auth_type: str = auth_block.get("type", "")
        oauth_sub: dict = auth_block.get("oauth") or {}

        # --- Determine OAuth ---
        use_oauth = auth_type == "oauth" or bool(oauth_sub) or bool(top_oauth)

        if use_oauth:
            # Merge: auth.oauth overrides top-level oauth
            merged_oauth = {**top_oauth, **oauth_sub}
            return cls._build_oauth(merged_oauth)

        # --- Basic auth ---
        if auth_type in ("basic", "") and (auth_block.get("username") or auth_block.get("username_env")):
            return cls._build_basic(auth_block)

        raise ValueError(
            "Cannot determine DSP auth method from config. "
            "Provide auth.type='oauth' with oauth credentials, "
            "or auth.type='basic' with username/password."
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @classmethod
    def _resolve(cls, block: dict, key: str, env_key: str) -> str:
        """Return block[key] if present, else resolve block[env_key] from env."""
        if value := block.get(key):
            return str(value)
        env_var = block.get(env_key)
        if env_var:
            resolved = os.environ.get(str(env_var), "")
            if resolved:
                return resolved
        return ""

    @classmethod
    def _build_oauth(cls, oauth: dict) -> DSPOAuthClient:
        client_id = cls._resolve(oauth, "client_id", "client_id_env")
        client_secret = cls._resolve(oauth, "client_secret", "client_secret_env")
        token_url = cls._resolve(oauth, "token_url", "token_url_env")

        if not client_id:
            raise ValueError("OAuth config missing client_id / client_id_env")
        if not client_secret:
            raise ValueError("OAuth config missing client_secret / client_secret_env")
        if not token_url:
            raise ValueError("OAuth config missing token_url / token_url_env")

        return DSPOAuthClient(
            client_id=client_id,
            client_secret=client_secret,
            token_url=token_url,
        )

    @classmethod
    def _build_basic(cls, auth: dict) -> DSPBasicAuth:
        username = cls._resolve(auth, "username", "username_env")
        password = cls._resolve(auth, "password", "password_env")

        if not username:
            raise ValueError("Basic auth config missing username / username_env")
        if not password:
            raise ValueError("Basic auth config missing password / password_env")

        return DSPBasicAuth(username=username, password=password)
