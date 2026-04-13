"""
OAuth 2.0 client credentials authentication for SAP Datasphere.
"""

from __future__ import annotations

import base64
import time

import httpx


class DSPAuth:
    """OAuth 2.0 client credentials flow for SAP Datasphere."""

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

    async def get_token(self) -> str:
        """Return a valid access token, refreshing if expired or close to expiry."""
        buffer = 300.0  # 5 minutes
        if self._access_token is None or time.time() >= (self._expires_at - buffer):
            await self._refresh_token()
        return self._access_token  # type: ignore[return-value]

    async def get_headers(self) -> dict:
        """Return Authorization header dict with a valid Bearer token."""
        token = await self.get_token()
        return {"Authorization": f"Bearer {token}"}

    async def _refresh_token(self) -> None:
        """Perform the OAuth client credentials POST and cache the result."""
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
