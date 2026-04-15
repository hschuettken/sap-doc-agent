"""Browser Pool for Spec2Sphere.

Manages Chrome CDP sessions for DSP and SAC browser automation.
Supports two modes:
  - "container" — connects to the co-located chrome container (port 9222)
  - "remote"    — connects to a remote Chrome instance (Win11 VM fallback)

Each tenant gets an isolated browser context (separate cookies, storage).
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)


class BrowserSession:
    """A CDP session for a single tenant/environment pair."""

    def __init__(
        self,
        tenant_id: UUID,
        environment: str,
        cdp_url: str,
        ws_url: str,
    ):
        self.tenant_id = tenant_id
        self.environment = environment
        self.cdp_url = cdp_url
        self.ws_url = ws_url
        self._healthy: bool = True

    @property
    def healthy(self) -> bool:
        return self._healthy

    def mark_unhealthy(self, reason: str = "") -> None:
        logger.warning(
            "Browser session marked unhealthy: tenant=%s env=%s reason=%s",
            self.tenant_id,
            self.environment,
            reason,
        )
        self._healthy = False

    def __repr__(self) -> str:
        return (
            f"BrowserSession(tenant={self.tenant_id}, env={self.environment}, "
            f"healthy={self._healthy}, ws={self.ws_url})"
        )


class BrowserPool:
    """Pool of CDP browser sessions, one per (tenant_id, environment) pair.

    Thread-safe via asyncio.Lock. Sessions are created on first access and
    reused until they become unhealthy.

    Config (from env vars):
        BROWSER_MODE: "container" | "remote"  (default: "container")
        BROWSER_CDP_URL: base URL for CDP endpoint  (default: http://chrome:9222)
        BROWSER_REMOTE_URL: fallback remote URL  (default: http://192.168.0.70:9222)
    """

    def __init__(self):
        self._sessions: dict[tuple[UUID, str], BrowserSession] = {}
        self._lock = asyncio.Lock()
        self._mode = os.environ.get("BROWSER_MODE", "container")
        self._cdp_base = os.environ.get("BROWSER_CDP_URL", "http://chrome:9222")
        self._remote_url = os.environ.get("BROWSER_REMOTE_URL", "http://192.168.0.70:9222")

    @property
    def cdp_url(self) -> str:
        if self._mode == "remote":
            return self._remote_url
        return self._cdp_base

    async def get_session(
        self,
        tenant_id: UUID,
        environment: str = "sandbox",
    ) -> Optional[BrowserSession]:
        """Get or create a CDP session for the given tenant/environment.

        Returns None if Chrome is not available.
        """
        key = (tenant_id, environment)

        async with self._lock:
            session = self._sessions.get(key)
            if session and session.healthy:
                return session

            # Create new session
            session = await self._create_session(tenant_id, environment)
            if session:
                self._sessions[key] = session
            return session

    async def _create_session(
        self,
        tenant_id: UUID,
        environment: str,
    ) -> Optional[BrowserSession]:
        """Create a new CDP session by opening a new target in Chrome."""
        cdp_base = self.cdp_url

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Open a new tab/target for this tenant
                resp = await client.put(f"{cdp_base}/json/new")
                if resp.status_code != 200:
                    logger.warning("Chrome CDP returned %d when creating new target", resp.status_code)
                    return None

                target = resp.json()
                ws_url = target.get("webSocketDebuggerUrl", "")
                if not ws_url:
                    logger.warning("No WebSocket URL in CDP new target response: %s", target)
                    return None

                session = BrowserSession(
                    tenant_id=tenant_id,
                    environment=environment,
                    cdp_url=cdp_base,
                    ws_url=ws_url,
                )
                logger.info(
                    "Created browser session: tenant=%s env=%s ws=%s",
                    tenant_id,
                    environment,
                    ws_url,
                )
                return session

        except httpx.ConnectError:
            logger.info(
                "Chrome CDP not available at %s (mode=%s) — browser features disabled",
                cdp_base,
                self._mode,
            )
            return None
        except Exception as exc:
            logger.warning("Failed to create browser session: %s", exc)
            return None

    async def health_check(self) -> dict:
        """Check Chrome CDP availability and return status dict."""
        cdp_base = self.cdp_url
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{cdp_base}/json/version")
                if resp.status_code == 200:
                    info = resp.json()
                    return {
                        "available": True,
                        "mode": self._mode,
                        "cdp_url": cdp_base,
                        "browser": info.get("Browser", "unknown"),
                        "protocol_version": info.get("Protocol-Version", "unknown"),
                        "active_sessions": len(self._sessions),
                    }
        except Exception:
            pass

        return {
            "available": False,
            "mode": self._mode,
            "cdp_url": cdp_base,
            "active_sessions": 0,
        }

    async def close_session(self, tenant_id: UUID, environment: str = "sandbox") -> None:
        """Close and remove the session for a tenant/environment."""
        key = (tenant_id, environment)
        async with self._lock:
            session = self._sessions.pop(key, None)
            if session:
                # Close the Chrome target
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        # Extract target ID from WS URL
                        ws_url = session.ws_url
                        target_id = ws_url.rstrip("/").split("/")[-1]
                        await client.get(f"{session.cdp_url}/json/close/{target_id}")
                except Exception as exc:
                    logger.debug("Could not close Chrome target: %s", exc)

    async def shutdown(self) -> None:
        """Gracefully close all sessions."""
        for tenant_id, environment in list(self._sessions.keys()):
            await self.close_session(tenant_id, environment)
        logger.info("Browser pool shut down")


# Module-level singleton
_pool: Optional[BrowserPool] = None


def get_pool() -> BrowserPool:
    """Get the global BrowserPool singleton."""
    global _pool
    if _pool is None:
        _pool = BrowserPool()
    return _pool
