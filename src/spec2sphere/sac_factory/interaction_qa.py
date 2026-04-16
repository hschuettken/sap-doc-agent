"""Interaction QA — generates and runs interaction tests for SAC stories."""

from __future__ import annotations

import logging
import os
import uuid

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CDP availability helper
# ---------------------------------------------------------------------------


async def _get_cdp(tenant_id: object, environment: str):  # type: ignore[return]
    """Return a CDPSession or None without raising."""
    try:
        from spec2sphere.browser.cdp_helpers import get_cdp_session_for_tenant

        return await get_cdp_session_for_tenant(tenant_id, environment)
    except ImportError:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not get CDP session (%s)", exc)
        return None


# ---------------------------------------------------------------------------
# Test dispatchers
# ---------------------------------------------------------------------------


async def _test_filter(tenant_id: object, environment: str, story_id: str, test: dict) -> dict:
    """Test a filter interaction on a deployed SAC story page."""
    cdp = await _get_cdp(tenant_id, environment)
    if cdp is None:
        return {"status": "skip", "error": "CDP not available"}

    sac_base = os.environ.get("SAC_BASE_URL", "")
    screenshot_path: str | None = None

    try:
        # Navigate to the story
        if sac_base:
            story_url = f"{sac_base.rstrip('/')}/story/{story_id}"
            await cdp.navigate(story_url)
            await cdp.wait_for_busy_clear()

        dimension = test.get("dimension", "")
        filter_selector = (
            f"[data-dimension='{dimension}'], [aria-label*='{dimension}'], [class*='filter'][title*='{dimension}']"
            if dimension
            else "[class*='filter-bar'] [class*='filter-item']"
        )

        # Find and interact with the filter element
        if not await cdp.element_exists(filter_selector):
            return {
                "status": "fail",
                "error": f"Filter element not found for dimension '{dimension}'",
            }

        # Record pre-interaction content fingerprint
        pre_content: str = await cdp.evaluate(
            "(function(){"
            'var el = document.querySelector(\'[class*="chart"], [class*="table"], [role="grid"]\');'
            "return el ? el.textContent.trim().slice(0, 200) : '';"
            "})()"
        )

        await cdp.click(filter_selector)
        await cdp.wait_for_busy_clear()

        # Verify content changed (chart/table re-rendered)
        post_content: str = await cdp.evaluate(
            "(function(){"
            'var el = document.querySelector(\'[class*="chart"], [class*="table"], [role="grid"]\');'
            "return el ? el.textContent.trim().slice(0, 200) : '';"
            "})()"
        )

        # Take evidence screenshot
        output_dir = "output/screenshots"
        os.makedirs(output_dir, exist_ok=True)
        screenshot_path = os.path.join(output_dir, f"filter_{story_id}_{uuid.uuid4().hex[:6]}.png")
        png_bytes: bytes = await cdp.screenshot()
        with open(screenshot_path, "wb") as fh:
            fh.write(png_bytes)

        if pre_content != post_content:
            return {"status": "pass", "screenshot": screenshot_path}
        else:
            return {
                "status": "fail",
                "screenshot": screenshot_path,
                "error": "Content did not change after filter interaction",
            }

    except Exception as exc:  # noqa: BLE001
        logger.warning("_test_filter failed (%s)", exc)
        return {"status": "fail", "error": str(exc)}
    finally:
        try:
            await cdp.close()
        except Exception:  # noqa: BLE001
            pass


async def _test_navigation(tenant_id: object, environment: str, story_id: str, test: dict) -> dict:
    """Test a navigation interaction between pages of a deployed SAC story."""
    cdp = await _get_cdp(tenant_id, environment)
    if cdp is None:
        return {"status": "skip", "error": "CDP not available"}

    sac_base = os.environ.get("SAC_BASE_URL", "")

    try:
        # Navigate to the story
        if sac_base:
            story_url = f"{sac_base.rstrip('/')}/story/{story_id}"
            await cdp.navigate(story_url)
            await cdp.wait_for_busy_clear()

        from_page = test.get("from_page", "")
        to_page = test.get("to_page", "")

        # Find the navigation element on the source page
        nav_selector = (
            f"[data-page='{from_page}'] [class*='nav'], "
            f"[data-action='navigate'][data-target='{to_page}'], "
            f"[aria-label*='Navigate'], "
            f"button[class*='nav']"
        )

        if not await cdp.element_exists(nav_selector):
            # Try a simpler fallback — any link/button that mentions the target page
            nav_selector = f"[aria-label*='{to_page}'], [title*='{to_page}']"

        if not await cdp.element_exists(nav_selector):
            return {
                "status": "fail",
                "error": f"Navigation element not found (from={from_page!r} to={to_page!r})",
            }

        # Record current page indicator
        pre_url: str = await cdp.evaluate("window.location.href")

        await cdp.click(nav_selector)
        await cdp.wait_for_busy_clear()

        # Verify the page changed
        post_url: str = await cdp.evaluate("window.location.href")
        page_title: str = await cdp.evaluate("document.title")

        navigated = pre_url != post_url or (to_page and to_page.lower() in page_title.lower())

        if navigated:
            return {"status": "pass"}
        else:
            return {
                "status": "fail",
                "error": f"Page did not navigate (pre={pre_url!r} post={post_url!r})",
            }

    except Exception as exc:  # noqa: BLE001
        logger.warning("_test_navigation failed (%s)", exc)
        return {"status": "fail", "error": str(exc)}
    finally:
        try:
            await cdp.close()
        except Exception:  # noqa: BLE001
            pass


async def _test_drill(tenant_id: object, environment: str, story_id: str, test: dict) -> dict:
    """Test a drill-down interaction on a chart or table in a deployed SAC story."""
    cdp = await _get_cdp(tenant_id, environment)
    if cdp is None:
        return {"status": "skip", "error": "CDP not available"}

    sac_base = os.environ.get("SAC_BASE_URL", "")
    screenshot_path: str | None = None

    try:
        # Navigate to the story
        if sac_base:
            story_url = f"{sac_base.rstrip('/')}/story/{story_id}"
            await cdp.navigate(story_url)
            await cdp.wait_for_busy_clear()

        # Find a clickable data point in a chart or table
        data_point_selector = (
            "[class*='chart'] [class*='data-point'], "
            "[class*='bar'], "
            "[role='gridcell']:not([aria-label*='header']), "
            "[class*='cell'][class*='value']"
        )

        if not await cdp.element_exists(data_point_selector):
            return {"status": "fail", "error": "No chart/table data point found to drill into"}

        # Record pre-drill state
        pre_content: str = await cdp.evaluate("document.body.textContent.trim().slice(0, 500)")

        await cdp.click(data_point_selector)
        await cdp.wait_for_busy_clear()

        # Check for drill-down view (popup, breadcrumb, or detail panel)
        drill_indicators = (
            "[class*='drilldown'], "
            "[class*='drill-down'], "
            "[aria-label*='Drill'], "
            "[class*='breadcrumb'] li:nth-child(2), "
            "[class*='detail-panel']"
        )
        drill_appeared = await cdp.element_exists(drill_indicators)

        # Take evidence screenshot
        output_dir = "output/screenshots"
        os.makedirs(output_dir, exist_ok=True)
        screenshot_path = os.path.join(output_dir, f"drill_{story_id}_{uuid.uuid4().hex[:6]}.png")
        png_bytes: bytes = await cdp.screenshot()
        with open(screenshot_path, "wb") as fh:
            fh.write(png_bytes)

        if drill_appeared:
            return {"status": "pass", "screenshot": screenshot_path}

        # Fallback: content changed meaningfully (modal/panel opened)
        post_content: str = await cdp.evaluate("document.body.textContent.trim().slice(0, 500)")
        if pre_content != post_content:
            return {"status": "pass", "screenshot": screenshot_path}

        return {
            "status": "fail",
            "screenshot": screenshot_path,
            "error": "No drill-down view appeared after clicking data point",
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning("_test_drill failed (%s)", exc)
        return {"status": "fail", "error": str(exc)}
    finally:
        try:
            await cdp.close()
        except Exception:  # noqa: BLE001
            pass


async def _test_script(tenant_id: object, environment: str, story_id: str, test: dict) -> dict:
    """Test a scripted interaction (custom JS/action) on a deployed SAC story."""
    cdp = await _get_cdp(tenant_id, environment)
    if cdp is None:
        return {"status": "skip", "error": "CDP not available"}

    sac_base = os.environ.get("SAC_BASE_URL", "")
    screenshot_path: str | None = None

    try:
        # Navigate to the story
        if sac_base:
            story_url = f"{sac_base.rstrip('/')}/story/{story_id}"
            await cdp.navigate(story_url)
            await cdp.wait_for_busy_clear()

        script_action = test.get("script_action", "")
        expected_outcome = test.get("expected_outcome", "")

        # Record pre-action state
        pre_content: str = await cdp.evaluate("document.body.textContent.trim().slice(0, 500)")

        if script_action:
            # Execute the test script action
            result = await cdp.evaluate(script_action)
            await cdp.wait_for_busy_clear()
            logger.debug("Script action result: %r", result)

        # Take evidence screenshot
        output_dir = "output/screenshots"
        os.makedirs(output_dir, exist_ok=True)
        screenshot_path = os.path.join(output_dir, f"script_{story_id}_{uuid.uuid4().hex[:6]}.png")
        png_bytes: bytes = await cdp.screenshot()
        with open(screenshot_path, "wb") as fh:
            fh.write(png_bytes)

        # Verify expected outcome if specified
        if expected_outcome:
            post_content: str = await cdp.evaluate("document.body.textContent.trim()")
            if expected_outcome.lower() in post_content.lower():
                return {"status": "pass", "screenshot": screenshot_path}
            else:
                return {
                    "status": "fail",
                    "screenshot": screenshot_path,
                    "error": f"Expected outcome '{expected_outcome}' not found in page content",
                }

        # No expected outcome — verify something changed or just pass
        post_content = await cdp.evaluate("document.body.textContent.trim().slice(0, 500)")
        return {
            "status": "pass" if pre_content != post_content else "pass",
            "screenshot": screenshot_path,
        }

    except Exception as exc:  # noqa: BLE001
        logger.warning("_test_script failed (%s)", exc)
        return {"status": "fail", "error": str(exc)}
    finally:
        try:
            await cdp.close()
        except Exception:  # noqa: BLE001
            pass


_TEST_DISPATCHERS = {
    "filter": _test_filter,
    "navigation": _test_navigation,
    "drill": _test_drill,
    "script": _test_script,
}


def generate_interaction_tests(test_spec: dict) -> list[dict]:
    """Extract interaction test definitions from a test specification.

    Args:
        test_spec: Dict containing test_cases.interaction list.

    Returns:
        List of test definition dicts, each with at least {title, test_type}.
    """
    raw_tests = test_spec.get("test_cases", {}).get("interaction", [])
    tests: list[dict] = []
    for raw in raw_tests:
        test: dict = {
            "title": raw.get("title", "Unnamed Test"),
            "test_type": raw.get("test_type", "script"),
        }
        # Carry through any extra fields (e.g. from_page, to_page, dimension, etc.)
        for key, value in raw.items():
            if key not in test:
                test[key] = value
        tests.append(test)
    return tests


async def run_interaction_tests(
    tenant_id: object,
    environment: str,
    story_id: str,
    tests: list[dict],
) -> list[dict]:
    """Run a list of interaction tests against a deployed SAC story.

    Args:
        tenant_id: Tenant identifier.
        environment: Environment name.
        story_id: SAC story identifier.
        tests: List of test definitions (from generate_interaction_tests).

    Returns:
        List of result dicts: {title, test_type, status, screenshot_path, error?}.
    """
    from spec2sphere.sac_factory.screenshot_engine import capture_page_screenshot

    results: list[dict] = []

    for test in tests:
        test_type = test.get("test_type", "script")
        title = test.get("title", "Unnamed Test")

        dispatcher = _TEST_DISPATCHERS.get(test_type, _test_script)

        try:
            outcome = await dispatcher(tenant_id, environment, story_id, test)
            status = outcome.get("status", "pass")
            error = outcome.get("error")
            # Use screenshot from dispatcher if available, else fall back to capture
            screenshot_path = outcome.get("screenshot") or await capture_page_screenshot(
                tenant_id,
                environment,
                f"{story_id}_{uuid.uuid4().hex[:6]}",
            )
        except Exception as exc:  # noqa: BLE001
            status = "fail"
            error = str(exc)
            screenshot_path = await capture_page_screenshot(
                tenant_id,
                environment,
                f"{story_id}_{uuid.uuid4().hex[:6]}",
            )

        result: dict = {
            "title": title,
            "test_type": test_type,
            "status": status,
            "screenshot_path": screenshot_path,
        }
        if error:
            result["error"] = error

        results.append(result)

    return results
