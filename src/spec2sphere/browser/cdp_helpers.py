"""CDP WebSocket helpers — real browser automation commands.

Wraps Chrome DevTools Protocol commands over WebSocket for:
- Navigation and page lifecycle
- DOM queries via CSS selectors
- Clicking, typing, key presses
- JavaScript evaluation
- Screenshot capture
- Waiting for elements / conditions

Uses stable SAP UI5 selectors from knowledge/shared/ui_mapping.md:
  Save button:    [data-sap-ui-type="sap.m.Button"][title="Save"]
  Deploy button:  [data-sap-ui-type="sap.m.Button"][title="Deploy"]
  Busy overlay:   .sapUiLocalBusyIndicator
  Toast/message:  .sapMMsgStrip
  SQL editor:     .ace_editor
  Space switcher: [id$="spaceSelector"]

Golden rules from knowledge/shared/cdp_playbook.md:
  1. Never navigate on unsaved tab — always Ctrl+S first
  2. Use CSS selectors, not XPath (dynamic IDs)
  3. Wait for busy indicator to clear after save/deploy
  4. Tab identity is URL-hash based
  5. Save vs Deploy are separate actions
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Optional

import websockets

logger = logging.getLogger(__name__)

# SAP UI5 stable selectors (from knowledge/shared/ui_mapping.md)
SAP_SELECTORS = {
    "save_button": '[data-sap-ui-type="sap.m.Button"][title="Save"]',
    "deploy_button": '[data-sap-ui-type="sap.m.Button"][title="Deploy"]',
    "busy_indicator": ".sapUiLocalBusyIndicator",
    "toast_message": ".sapMMsgStrip",
    "sql_editor": ".ace_editor",
    "space_switcher": '[id$="spaceSelector"]',
    "dialog_confirm": ".sapMDialogScrollCont .sapMBtn:last-child",
    "shell_header": "#shell-header",
    "validation_messages": ".sapMMessageView .sapMListItems",
    "column_mapping": "[data-column-name]",
}


class CDPSession:
    """WebSocket-based CDP session for a single Chrome target."""

    def __init__(self, ws_url: str, timeout: float = 30.0):
        self._ws_url = ws_url
        self._timeout = timeout
        self._ws = None
        self._msg_id = 0
        self._connected = False

    async def connect(self) -> None:
        """Open WebSocket connection to Chrome target."""
        self._ws = await websockets.connect(self._ws_url, max_size=50 * 1024 * 1024)
        self._connected = True
        # Enable required domains
        await self._send("Page.enable")
        await self._send("DOM.enable")
        await self._send("Runtime.enable")
        logger.info("CDP WebSocket connected: %s", self._ws_url)

    async def close(self) -> None:
        """Close WebSocket connection."""
        if self._ws:
            await self._ws.close()
            self._connected = False

    async def _send(self, method: str, params: dict | None = None) -> dict:
        """Send a CDP command and wait for response."""
        if not self._ws or not self._connected:
            raise RuntimeError("CDP session not connected")
        self._msg_id += 1
        msg = {"id": self._msg_id, "method": method, "params": params or {}}
        await self._ws.send(json.dumps(msg))

        # Read messages until we get our response
        while True:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=self._timeout)
            resp = json.loads(raw)
            if resp.get("id") == self._msg_id:
                if "error" in resp:
                    raise RuntimeError(f"CDP error: {resp['error']}")
                return resp.get("result", {})
            # else: event message, skip

    # -- Navigation --

    async def navigate(self, url: str) -> None:
        """Navigate to URL and wait for load."""
        await self._send("Page.navigate", {"url": url})
        # Wait for page load
        await self._wait_for_load()

    async def _wait_for_load(self, timeout: float = 30.0) -> None:
        """Wait for Page.loadEventFired or frameStoppedLoading."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=2.0)
                resp = json.loads(raw)
                method = resp.get("method", "")
                if method in ("Page.loadEventFired", "Page.frameStoppedLoading"):
                    return
            except asyncio.TimeoutError:
                # Check if page is already loaded
                result = await self._send("Runtime.evaluate", {"expression": "document.readyState"})
                if result.get("result", {}).get("value") == "complete":
                    return

    async def get_url(self) -> str:
        """Get current page URL."""
        result = await self._send("Runtime.evaluate", {"expression": "window.location.href"})
        return result.get("result", {}).get("value", "")

    # -- DOM Queries --

    async def query_selector(self, selector: str) -> Optional[int]:
        """Find element by CSS selector. Returns node ID or None."""
        doc = await self._send("DOM.getDocument")
        root_id = doc["root"]["nodeId"]
        try:
            result = await self._send(
                "DOM.querySelector",
                {
                    "nodeId": root_id,
                    "selector": selector,
                },
            )
            node_id = result.get("nodeId", 0)
            return node_id if node_id > 0 else None
        except RuntimeError:
            return None

    async def query_selector_all(self, selector: str) -> list[int]:
        """Find all elements matching CSS selector. Returns list of node IDs."""
        doc = await self._send("DOM.getDocument")
        root_id = doc["root"]["nodeId"]
        try:
            result = await self._send(
                "DOM.querySelectorAll",
                {
                    "nodeId": root_id,
                    "selector": selector,
                },
            )
            return [nid for nid in result.get("nodeIds", []) if nid > 0]
        except RuntimeError:
            return []

    async def element_exists(self, selector: str) -> bool:
        """Check if an element exists on the page."""
        return await self.query_selector(selector) is not None

    async def get_text(self, selector: str) -> str:
        """Get innerText of an element."""
        result = await self.evaluate(f'document.querySelector({json.dumps(selector)})?.innerText || ""')
        return result or ""

    # -- Actions --

    async def click(self, selector: str) -> None:
        """Click an element by CSS selector using JS click()."""
        await self.evaluate(f"document.querySelector({json.dumps(selector)})?.click()")
        await asyncio.sleep(0.3)  # Brief settle time

    async def type_text(self, selector: str, text: str) -> None:
        """Type text into an input element."""
        # Focus the element first
        await self.evaluate(f"document.querySelector({json.dumps(selector)})?.focus()")
        await asyncio.sleep(0.1)
        # Use Input.insertText for reliable text entry
        await self._send("Input.insertText", {"text": text})

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> None:
        """Press a keyboard key with optional modifiers.

        Args:
            key: Key name (e.g. "s", "Enter", "Tab")
            modifiers: List of modifier keys (e.g. ["Control", "Shift"])
        """
        modifier_flags = 0
        if modifiers:
            for mod in modifiers:
                if mod.lower() in ("ctrl", "control"):
                    modifier_flags |= 2
                elif mod.lower() == "shift":
                    modifier_flags |= 8
                elif mod.lower() == "alt":
                    modifier_flags |= 1
                elif mod.lower() == "meta":
                    modifier_flags |= 4

        # keyDown + keyUp
        await self._send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyDown",
                "key": key,
                "modifiers": modifier_flags,
                "text": key if len(key) == 1 else "",
            },
        )
        await self._send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "key": key,
                "modifiers": modifier_flags,
            },
        )

    async def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript in the page and return the result value."""
        result = await self._send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
            },
        )
        return result.get("result", {}).get("value")

    # -- Screenshot --

    async def screenshot(self) -> bytes:
        """Capture a PNG screenshot of the current viewport."""
        result = await self._send("Page.captureScreenshot", {"format": "png"})
        data = result.get("data", "")
        return base64.b64decode(data) if data else b""

    async def screenshot_element(self, selector: str) -> bytes:
        """Capture a screenshot clipped to a specific element."""
        # Get element bounding box via JS
        box = await self.evaluate(f"""
            (() => {{
                const el = document.querySelector({json.dumps(selector)});
                if (!el) return null;
                const r = el.getBoundingClientRect();
                return {{x: r.x, y: r.y, width: r.width, height: r.height}};
            }})()
        """)
        if not box:
            return await self.screenshot()  # Fallback to full page

        result = await self._send(
            "Page.captureScreenshot",
            {
                "format": "png",
                "clip": {
                    "x": box["x"],
                    "y": box["y"],
                    "width": box["width"],
                    "height": box["height"],
                    "scale": 1,
                },
            },
        )
        data = result.get("data", "")
        return base64.b64decode(data) if data else b""

    # -- SAP-specific helpers --

    async def wait_for_element(self, selector: str, timeout: float = 15.0, poll_interval: float = 0.5) -> bool:
        """Poll until an element appears on the page."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if await self.element_exists(selector):
                return True
            await asyncio.sleep(poll_interval)
        return False

    async def wait_for_element_gone(self, selector: str, timeout: float = 30.0, poll_interval: float = 0.5) -> bool:
        """Poll until an element disappears from the page."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            if not await self.element_exists(selector):
                return True
            await asyncio.sleep(poll_interval)
        return False

    async def wait_for_busy_clear(self, timeout: float = 30.0) -> bool:
        """Wait for SAP UI5 busy indicator to clear (cdp_playbook rule #3)."""
        return await self.wait_for_element_gone(SAP_SELECTORS["busy_indicator"], timeout=timeout)

    async def sap_save(self) -> bool:
        """Save in SAP UI5 — Ctrl+S then wait for busy clear (cdp_playbook rule #1).

        Per dsp_quirks.md: Ace editor doesn't fire change events, so
        Ctrl+S is required to flush the buffer.
        """
        await self.press_key("s", modifiers=["Control"])
        await asyncio.sleep(0.5)
        return await self.wait_for_busy_clear()

    async def sap_deploy(self) -> bool:
        """Click the Deploy button and wait for completion."""
        deploy_btn = SAP_SELECTORS["deploy_button"]
        if not await self.wait_for_element(deploy_btn, timeout=5.0):
            logger.warning("Deploy button not found")
            return False
        await self.click(deploy_btn)
        # Handle confirmation dialog if it appears
        await asyncio.sleep(1.0)
        confirm = SAP_SELECTORS["dialog_confirm"]
        if await self.element_exists(confirm):
            await self.click(confirm)
        return await self.wait_for_busy_clear(timeout=60.0)

    async def check_for_errors(self) -> list[str]:
        """Check for SAP UI5 toast/error messages."""
        errors = []
        messages = await self.evaluate("""
            (() => {
                const strips = document.querySelectorAll('.sapMMsgStrip');
                return Array.from(strips).map(s => ({
                    text: s.innerText || '',
                    type: s.className || ''
                }));
            })()
        """)
        if messages:
            for msg in messages:
                errors.append(msg.get("text", "").strip())
        return errors

    async def is_session_expired(self) -> bool:
        """Detect SAP session expiry (cdp_playbook.md: redirect to login)."""
        url = await self.get_url()
        return "/login" in url.lower() or "session_expired" in url.lower()


async def create_cdp_session(ws_url: str, timeout: float = 30.0) -> CDPSession:
    """Create and connect a CDPSession from a WebSocket URL."""
    session = CDPSession(ws_url, timeout)
    await session.connect()
    return session


async def get_cdp_session_for_tenant(tenant_id: Any, environment: str = "sandbox") -> Optional[CDPSession]:
    """Get a connected CDPSession for a tenant via the BrowserPool.

    Returns None if Chrome is not available.
    """
    from spec2sphere.browser.pool import get_pool

    pool = get_pool()
    browser_session = await pool.get_session(tenant_id, environment)
    if not browser_session or not browser_session.ws_url:
        return None

    try:
        return await create_cdp_session(browser_session.ws_url)
    except Exception as exc:
        logger.warning("Failed to create CDP session for tenant %s: %s", tenant_id, exc)
        return None
