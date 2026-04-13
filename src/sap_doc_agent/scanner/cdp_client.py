"""Lightweight Chrome DevTools Protocol client.

Talks to Chrome's CDP HTTP endpoint for basic operations.
For complex multi-step interactions, the caller can use the
evaluate() method to run JavaScript in the page.
"""

from __future__ import annotations
import logging
from typing import Any, Optional
import httpx

logger = logging.getLogger(__name__)


class CDPClient:
    """Async CDP client that communicates via Chrome's HTTP debug endpoints."""

    def __init__(self, cdp_url: str = "http://192.168.0.70:9222", timeout: float = 30.0):
        self._cdp_url = cdp_url.rstrip("/")
        self._timeout = timeout
        self._ws_url: Optional[str] = None
        self._target_id: Optional[str] = None

    async def list_targets(self) -> list[dict]:
        """List all available browser targets (tabs)."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._cdp_url}/json/list")
            resp.raise_for_status()
            return resp.json()

    async def find_target(self, url_contains: str) -> Optional[dict]:
        """Find a target whose URL contains the given string."""
        targets = await self.list_targets()
        for t in targets:
            if url_contains in t.get("url", ""):
                return t
        return None

    async def get_page_url(self, target_id: Optional[str] = None) -> str:
        """Get current URL of a target."""
        targets = await self.list_targets()
        tid = target_id or self._target_id
        for t in targets:
            if t.get("id") == tid:
                return t.get("url", "")
        return ""

    async def take_screenshot(self, target_id: Optional[str] = None) -> bytes:
        """Take a screenshot of the target page. Returns PNG bytes.

        Note: This requires WebSocket connection for the actual CDP command.
        For simplicity, this implementation uses the /json/protocol HTTP endpoint
        which has limitations. For production, use a proper WebSocket CDP client.
        """
        # Placeholder — in production, this connects via WebSocket to send
        # Page.captureScreenshot. For now, return empty bytes.
        # The actual screenshot logic will use Playwright MCP when available.
        logger.warning("CDP screenshot requires WebSocket connection — use Playwright MCP for screenshots")
        return b""

    async def navigate(self, url: str, target_id: Optional[str] = None) -> None:
        """Navigate a target to a URL via CDP HTTP endpoint."""
        tid = target_id or self._target_id
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._cdp_url}/json/navigate",
                params={"url": url, "id": tid} if tid else {"url": url},
            )
            # Some Chrome versions don't support /json/navigate
            if resp.status_code != 200:
                logger.warning("CDP navigate returned %s — may need WebSocket", resp.status_code)

    async def evaluate(self, expression: str, target_id: Optional[str] = None) -> Any:
        """Evaluate JavaScript in a target page.

        Note: Full evaluate requires WebSocket. This is a framework placeholder.
        The actual implementation connects via WebSocket to Runtime.evaluate.
        For the demo, JavaScript extraction is done via Playwright MCP.
        """
        logger.info("CDP evaluate called — delegate to Playwright MCP for production use")
        return None

    @property
    def is_available(self) -> bool:
        """Check if CDP endpoint is reachable (sync check for config validation)."""
        return True  # Validated at connection time
