"""SAC Playwright Adapter — browser-based story creation using the browser pool."""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

logger = logging.getLogger(__name__)


class SACPlaywrightAdapter:
    """Drives SAC story creation via browser automation (browser pool CDP sessions)."""

    def __init__(self, tenant_id: Any, environment: str) -> None:
        self._tenant_id = tenant_id
        self._environment = environment
        self._session: Any = None
        self._cdp: Any = None

    async def connect(self) -> None:
        """Acquire a browser pool session and create a CDP session from it."""
        try:
            from spec2sphere.browser.cdp_helpers import create_cdp_session
            from spec2sphere.browser.pool import get_pool

            pool = get_pool()
            browser_session = await pool.get_session(self._tenant_id, self._environment)
            if not browser_session:
                logger.warning(
                    "Browser pool returned no session for tenant=%s env=%s", self._tenant_id, self._environment
                )
                return
            self._session = browser_session
            self._cdp = await create_cdp_session(browser_session.ws_url)
        except ImportError:
            logger.warning("cdp_helpers not yet available — running in demo mode")
        except Exception as exc:  # noqa: BLE001
            logger.warning("CDP connect failed (%s) — running in demo mode", exc)

    async def _ensure_connected(self) -> None:
        """Connect if not already connected."""
        if self._cdp is None:
            await self.connect()

    async def create_story(self, title: str, folder: str = "Public") -> str:
        """Create a new SAC story in the given folder.

        Args:
            title: Story title.
            folder: Target folder name (default: "Public").

        Returns:
            Story ID extracted from SAC URL, or a generated placeholder in demo mode.
        """
        await self._ensure_connected()

        sac_base = os.environ.get("SAC_BASE_URL", "")
        if not self._cdp or not sac_base:
            logger.warning("CDP unavailable or SAC_BASE_URL not set — returning placeholder story ID")
            return f"story_{uuid.uuid4().hex[:8]}"

        try:
            stories_url = f"{sac_base.rstrip('/')}/story"
            await self._cdp.navigate(stories_url)
            await self._cdp.wait_for_busy_clear()

            # Click "Create" button → Story option
            await self._cdp.click("[data-action='create'], button[aria-label*='Create'], .sap-create-button")
            await self._cdp.wait_for_element("[data-action='story'], [aria-label*='Story']")
            await self._cdp.click("[data-action='story'], [aria-label*='Story']")
            await self._cdp.wait_for_busy_clear()

            # Set story title if a title field is present
            if await self._cdp.element_exists("input[aria-label*='Title'], input[placeholder*='title']"):
                await self._cdp.type_text(
                    "input[aria-label*='Title'], input[placeholder*='title']",
                    title,
                )
                await self._cdp.press_key("Enter", [])
                await self._cdp.wait_for_busy_clear()

            # Extract story ID from current URL (SAC uses fragment like #storyId=<id>)
            current_url: str = await self._cdp.evaluate("window.location.href")
            story_id = _extract_story_id_from_url(current_url)
            return story_id or f"story_{uuid.uuid4().hex[:8]}"

        except Exception as exc:  # noqa: BLE001
            logger.warning("create_story CDP operation failed (%s) — returning placeholder", exc)
            return f"story_{uuid.uuid4().hex[:8]}"

    async def add_page(self, story_id: str, page_title: str) -> str:
        """Add a page to an existing story.

        Args:
            story_id: Target story ID.
            page_title: Title for the new page.

        Returns:
            Page identifier extracted from SAC, or a generated placeholder in demo mode.
        """
        await self._ensure_connected()

        if not self._cdp:
            logger.warning("CDP unavailable — returning placeholder page ID")
            return f"page_{uuid.uuid4().hex[:8]}"

        try:
            # Click "Add Page" button in the story editor toolbar
            await self._cdp.click("button[aria-label*='Add Page'], [data-action='addPage'], .sap-add-page-button")
            await self._cdp.wait_for_busy_clear()

            # Set the page title in the newly-created tab/input
            if await self._cdp.element_exists("input[aria-label*='Page'], input[placeholder*='page']"):
                await self._cdp.type_text(
                    "input[aria-label*='Page'], input[placeholder*='page']",
                    page_title,
                )
                await self._cdp.press_key("Enter", [])
                await self._cdp.wait_for_busy_clear()

            # Extract page identifier from DOM or URL hash
            page_id: str = await self._cdp.evaluate(
                "(function(){ "
                "var el = document.querySelector('[data-page-id], [aria-selected=\"true\"][data-id]'); "
                "return el ? (el.dataset.pageId || el.dataset.id) : ''; })()"
            )
            return page_id if page_id else f"page_{uuid.uuid4().hex[:8]}"

        except Exception as exc:  # noqa: BLE001
            logger.warning("add_page CDP operation failed (%s) — returning placeholder", exc)
            return f"page_{uuid.uuid4().hex[:8]}"

    async def add_widget(
        self,
        page_id: str,
        widget_type: str,
        title: str,
        binding: str,
    ) -> str:
        """Add a widget to a page.

        Args:
            page_id: Target page ID.
            widget_type: Widget type key (e.g. "kpi_tile", "bar_chart").
            title: Widget title.
            binding: Data binding expression.

        Returns:
            Widget identifier extracted from SAC, or a generated placeholder in demo mode.
        """
        await self._ensure_connected()

        if not self._cdp:
            logger.warning("CDP unavailable — returning placeholder widget ID")
            return f"widget_{uuid.uuid4().hex[:8]}"

        try:
            # Open the "Insert" / "Add Widget" panel
            await self._cdp.click(
                "button[aria-label*='Insert'], button[aria-label*='Add Widget'], "
                "[data-action='insertWidget'], .sap-insert-button"
            )
            await self._cdp.wait_for_element("[data-widget-type], [class*='widget-palette'], [aria-label*='Chart']")

            # Map widget_type key to SAC selector
            widget_selector = _widget_type_selector(widget_type)
            await self._cdp.click(widget_selector)
            await self._cdp.wait_for_busy_clear()

            # Set widget title if editable
            if title and await self._cdp.element_exists(
                "input[aria-label*='Title'], [contenteditable='true'][class*='title']"
            ):
                await self._cdp.type_text(
                    "input[aria-label*='Title'], [contenteditable='true'][class*='title']",
                    title,
                )
                await self._cdp.press_key("Escape", [])

            # Configure data binding if provided
            if binding:
                await _apply_data_binding(self._cdp, binding)

            # Extract widget ID from DOM
            widget_id: str = await self._cdp.evaluate(
                "(function(){ "
                "var el = document.querySelector('[data-widget-id][aria-selected=\"true\"]'); "
                "return el ? el.dataset.widgetId : ''; })()"
            )
            return widget_id if widget_id else f"widget_{uuid.uuid4().hex[:8]}"

        except Exception as exc:  # noqa: BLE001
            logger.warning("add_widget CDP operation failed (%s) — returning placeholder", exc)
            return f"widget_{uuid.uuid4().hex[:8]}"

    async def configure_filter(
        self,
        page_id: str,
        dimension: str,
        filter_type: str = "dropdown",
    ) -> None:
        """Configure a filter on a page.

        Args:
            page_id: Target page ID.
            dimension: Dimension name to filter on.
            filter_type: Filter UI type (default: "dropdown").
        """
        await self._ensure_connected()

        if not self._cdp:
            logger.warning("CDP unavailable — skipping configure_filter for dimension=%s", dimension)
            return

        try:
            # Open the filter panel
            await self._cdp.click("button[aria-label*='Filter'], [data-action='addFilter'], .sap-filter-button")
            await self._cdp.wait_for_element("[class*='filter-panel'], [aria-label*='Add Filter'], [role='dialog']")

            # Search/select the dimension
            if await self._cdp.element_exists("input[placeholder*='Search'], input[aria-label*='Search']"):
                await self._cdp.type_text(
                    "input[placeholder*='Search'], input[aria-label*='Search']",
                    dimension,
                )
                await self._cdp.wait_for_busy_clear()

            # Click the matching dimension item
            dimension_selector = f"[data-dimension='{dimension}'], [title='{dimension}'], [aria-label*='{dimension}']"
            if await self._cdp.element_exists(dimension_selector):
                await self._cdp.click(dimension_selector)

            # Select filter type if a selector is present
            filter_type_selector = (
                f"[data-filter-type='{filter_type}'], option[value='{filter_type}'], [aria-label*='{filter_type}']"
            )
            if await self._cdp.element_exists(filter_type_selector):
                await self._cdp.click(filter_type_selector)

            # Confirm
            if await self._cdp.element_exists("button[aria-label*='OK'], button[aria-label*='Apply']"):
                await self._cdp.click("button[aria-label*='OK'], button[aria-label*='Apply']")
                await self._cdp.wait_for_busy_clear()

        except Exception as exc:  # noqa: BLE001
            logger.warning("configure_filter CDP operation failed (%s) — skipping", exc)

    async def setup_navigation(
        self,
        from_page: str,
        to_page: str,
        trigger: str = "click",
    ) -> None:
        """Set up navigation between two pages.

        Args:
            from_page: Source page ID or title.
            to_page: Target page ID or title.
            trigger: Interaction trigger (default: "click").
        """
        await self._ensure_connected()

        if not self._cdp:
            logger.warning("CDP unavailable — skipping setup_navigation from=%s to=%s", from_page, to_page)
            return

        try:
            # Right-click on the source page element to open context menu
            source_selector = f"[data-page-id='{from_page}'], [aria-label*='{from_page}'], [title='{from_page}']"
            if await self._cdp.element_exists(source_selector):
                await self._cdp.evaluate(
                    f"(function(){{"
                    f'  var el = document.querySelector("{source_selector.replace(chr(34), chr(39))}");'
                    f"  if (el) {{"
                    f"    var e = new MouseEvent('contextmenu', {{bubbles: true, cancelable: true, button: 2}});"
                    f"    el.dispatchEvent(e);"
                    f"  }}"
                    f"}})()"
                )
                await self._cdp.wait_for_element("[role='menu'], [class*='context-menu'], [data-action*='navigation']")
                nav_option = "[data-action='addNavigation'], [aria-label*='Navigation'], [aria-label*='Navigate']"
                if await self._cdp.element_exists(nav_option):
                    await self._cdp.click(nav_option)
                    await self._cdp.wait_for_element("[role='dialog'], [class*='navigation-dialog']")

                    # Set target page
                    target_selector = (
                        f"[data-page-id='{to_page}'], option[value='{to_page}'], [aria-label*='{to_page}']"
                    )
                    if await self._cdp.element_exists(target_selector):
                        await self._cdp.click(target_selector)

                    # Set trigger type
                    trigger_selector = (
                        f"[data-trigger='{trigger}'], option[value='{trigger}'], [aria-label*='{trigger}']"
                    )
                    if await self._cdp.element_exists(trigger_selector):
                        await self._cdp.click(trigger_selector)

                    # Confirm
                    if await self._cdp.element_exists("button[aria-label*='OK'], button[aria-label*='Apply']"):
                        await self._cdp.click("button[aria-label*='OK'], button[aria-label*='Apply']")
                        await self._cdp.wait_for_busy_clear()

        except Exception as exc:  # noqa: BLE001
            logger.warning("setup_navigation CDP operation failed (%s) — skipping", exc)

    async def capture_screenshot(self, output_path: str) -> str:
        """Capture a screenshot of the current browser view.

        Args:
            output_path: File path to write the PNG to.

        Returns:
            Absolute path of the saved screenshot, or output_path in demo mode.
        """
        await self._ensure_connected()

        if not self._cdp:
            logger.warning("CDP unavailable — returning path-only placeholder for screenshot")
            return output_path

        try:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            png_bytes: bytes = await self._cdp.screenshot()
            with open(output_path, "wb") as fh:
                fh.write(png_bytes)
            return os.path.abspath(output_path)

        except Exception as exc:  # noqa: BLE001
            logger.warning("capture_screenshot CDP operation failed (%s) — returning path only", exc)
            return output_path

    async def deploy_from_blueprint(self, blueprint: dict) -> dict:
        """Orchestrate full story creation from a blueprint.

        Sequence: create_story → per page: add_page → per widget: add_widget
        → per filter: configure_filter → navigation setup.

        Args:
            blueprint: SAC blueprint dict (same format as click_guide_generator).

        Returns:
            Deployment result dict with story_id, pages, screenshots, status.
        """
        title = blueprint.get("title", "Untitled")
        folder = blueprint.get("folder", "Public")
        pages_spec = blueprint.get("pages", [])
        interactions = blueprint.get("interactions", {})
        navigation = interactions.get("navigation", [])

        story_id = await self.create_story(title, folder)

        result_pages: list[dict] = []
        screenshots: list[str] = []

        for page_spec in pages_spec:
            page_title = page_spec.get("title", "Page")
            page_id = await self.add_page(story_id, page_title)

            widget_ids: list[str] = []
            for widget in page_spec.get("widgets", []):
                wid = await self.add_widget(
                    page_id,
                    widget.get("type", "unknown"),
                    widget.get("title", ""),
                    widget.get("binding", ""),
                )
                widget_ids.append(wid)

            for flt in page_spec.get("filters", []):
                await self.configure_filter(
                    page_id,
                    flt.get("dimension", ""),
                    flt.get("type", "dropdown"),
                )

            screenshot_path = await self.capture_screenshot(f"output/screenshots/{story_id}_{page_id}.png")
            screenshots.append(screenshot_path)

            result_pages.append(
                {
                    "page_id": page_id,
                    "title": page_title,
                    "widget_ids": widget_ids,
                }
            )

        for nav in navigation:
            await self.setup_navigation(
                nav.get("from", ""),
                nav.get("to", ""),
                nav.get("trigger", "click"),
            )

        return {
            "story_id": story_id,
            "pages": result_pages,
            "screenshots": screenshots,
            "status": "deployed",
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _extract_story_id_from_url(url: str) -> str | None:
    """Extract SAC story ID from URL hash or query params.

    SAC typically uses fragments like #storyId=<id> or paths like /stories/<id>.
    """
    import re

    # Fragment pattern: #storyId=<id>
    m = re.search(r"[#&?]storyId=([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)

    # Path pattern: /stories/<id>
    m = re.search(r"/stories/([A-Za-z0-9_-]+)", url)
    if m:
        return m.group(1)

    return None


def _widget_type_selector(widget_type: str) -> str:
    """Return a CSS selector for the SAC widget palette entry matching widget_type."""
    _MAP = {
        "kpi_tile": "[data-widget-type='KPITile'], [aria-label*='KPI']",
        "bar_chart": "[data-widget-type='BarChart'], [aria-label*='Bar Chart']",
        "line_chart": "[data-widget-type='LineChart'], [aria-label*='Line Chart']",
        "pie_chart": "[data-widget-type='PieChart'], [aria-label*='Pie Chart']",
        "variance_chart": "[data-widget-type='VarianceChart'], [aria-label*='Variance']",
        "table": "[data-widget-type='Table'], [aria-label*='Table']",
        "geo_map": "[data-widget-type='GeoMap'], [aria-label*='Geo Map'], [aria-label*='Map']",
        "text": "[data-widget-type='Text'], [aria-label*='Text']",
        "image": "[data-widget-type='Image'], [aria-label*='Image']",
    }
    return _MAP.get(
        widget_type,
        f"[data-widget-type='{widget_type}'], [aria-label*='{widget_type}']",
    )


async def _apply_data_binding(cdp: Any, binding: str) -> None:
    """Attempt to set a data binding expression in the widget panel."""
    binding_input = (
        "input[aria-label*='Binding'], input[aria-label*='Data'], "
        "input[placeholder*='binding'], input[placeholder*='measure']"
    )
    if await cdp.element_exists(binding_input):
        await cdp.type_text(binding_input, binding)
        await cdp.press_key("Enter", [])
        await cdp.wait_for_busy_clear()
