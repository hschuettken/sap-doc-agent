"""Screenshot Engine — pixel diff utilities and screenshot capture stubs."""

from __future__ import annotations

import logging
import os
import uuid

logger = logging.getLogger(__name__)

_PIXEL_THRESHOLD = 10  # anti-aliasing tolerance (grayscale units)


def compute_pixel_diff(pixels_a: list[int], pixels_b: list[int]) -> float:
    """Compute the percentage of pixels that differ between two grayscale images.

    Pixels within _PIXEL_THRESHOLD of each other are considered identical
    (anti-aliasing tolerance).

    Args:
        pixels_a: Flat list of grayscale pixel values (0-255).
        pixels_b: Flat list of grayscale pixel values (0-255), same length.

    Returns:
        Percentage of differing pixels (0.0 to 100.0).

    Raises:
        ValueError: If the two pixel lists have different lengths.
    """
    if len(pixels_a) != len(pixels_b):
        raise ValueError(f"Pixel lists must be the same length ({len(pixels_a)} vs {len(pixels_b)})")
    if not pixels_a:
        return 0.0

    differing = sum(1 for a, b in zip(pixels_a, pixels_b) if abs(a - b) > _PIXEL_THRESHOLD)
    return (differing / len(pixels_a)) * 100.0


def classify_visual_diff(diff_pct: float, elements_missing: int = 0) -> str:
    """Classify a visual diff result into a human-readable category.

    Args:
        diff_pct: Percentage of differing pixels (from compute_pixel_diff).
        elements_missing: Number of expected UI elements not found.

    Returns:
        One of: "missing_element", "pass", "minor_diff", "major_diff".
    """
    if elements_missing > 0:
        return "missing_element"
    if diff_pct <= 1.0:
        return "pass"
    if diff_pct <= 10.0:
        return "minor_diff"
    return "major_diff"


def structural_screenshot_diff(expected_elements: list[str], actual_elements: list[str]) -> dict:
    """Compare expected vs actual UI elements (by label/ID).

    Returns: {match: bool, missing: [str], extra: [str], elements_missing: int}
    """
    expected_set = set(expected_elements)
    actual_set = set(actual_elements)
    missing = sorted(expected_set - actual_set)
    extra = sorted(actual_set - expected_set)
    return {
        "match": len(missing) == 0,
        "missing": missing,
        "extra": extra,
        "elements_missing": len(missing),
    }


def generate_diff_overlay_html(
    screenshot_path: str,
    differences: list[dict],
    width: int = 1920,
    height: int = 1080,
) -> str:
    """Generate an HTML overlay highlighting differences on a screenshot.

    Returns HTML string with positioned annotations over the screenshot.
    """
    annotations = []
    for i, diff in enumerate(differences):
        x = diff.get("x", 10 + i * 50)
        y = diff.get("y", 10 + i * 30)
        label = diff.get("label", diff.get("type", f"Diff {i + 1}"))
        annotations.append(
            f'<div style="position:absolute;left:{x}px;top:{y}px;'
            f"border:2px solid red;padding:2px 6px;background:rgba(255,0,0,0.15);"
            f'color:red;font-size:11px;border-radius:3px;">{label}</div>'
        )
    return (
        f'<div style="position:relative;width:{width}px;height:{height}px;">'
        f'<img src="{screenshot_path}" style="width:100%;height:100%;object-fit:contain;">'
        f"{''.join(annotations)}"
        f"</div>"
    )


async def capture_page_screenshot(
    tenant_id: object,
    environment: str,
    page_id: str,
    output_dir: str = "output/screenshots",
) -> str:
    """Capture a screenshot of a SAC story page.

    Attempts a real CDP screenshot; falls back to returning the path only when
    CDP is not available or SAC_BASE_URL is not configured.

    Args:
        tenant_id: Tenant identifier.
        environment: Environment name (e.g. "prod", "dev").
        page_id: SAC page identifier.
        output_dir: Directory to write the PNG file.

    Returns:
        Absolute path of the saved screenshot file, or a path placeholder in
        demo/no-CDP mode.
    """
    os.makedirs(output_dir, exist_ok=True)
    filename = f"page_{page_id}_{uuid.uuid4().hex[:6]}.png"
    output_path = os.path.join(output_dir, filename)

    cdp_session = None
    try:
        from spec2sphere.browser.cdp_helpers import get_cdp_session_for_tenant

        cdp_session = await get_cdp_session_for_tenant(tenant_id, environment)
        if cdp_session is None:
            logger.warning(
                "No CDP session for tenant=%s env=%s — returning path-only placeholder",
                tenant_id,
                environment,
            )
            return output_path

        png_bytes: bytes = await cdp_session.screenshot()
        with open(output_path, "wb") as fh:
            fh.write(png_bytes)
        return os.path.abspath(output_path)

    except ImportError:
        logger.warning("cdp_helpers not yet available — returning path-only placeholder")
        return output_path
    except Exception as exc:  # noqa: BLE001
        logger.warning("capture_page_screenshot CDP operation failed (%s) — returning path only", exc)
        return output_path
    finally:
        if cdp_session is not None:
            try:
                await cdp_session.close()
            except Exception:  # noqa: BLE001
                pass


async def capture_widget_screenshot(
    tenant_id: object,
    environment: str,
    widget_id: str,
    output_dir: str = "output/screenshots",
) -> str:
    """Capture a screenshot of a specific SAC widget.

    Uses element-scoped screenshot when a widget selector can be determined;
    falls back to a full-page screenshot. Returns path-only in demo mode.

    Args:
        tenant_id: Tenant identifier.
        environment: Environment name (e.g. "prod", "dev").
        widget_id: SAC widget identifier.
        output_dir: Directory to write the PNG file.

    Returns:
        Absolute path of the saved screenshot file, or a path placeholder in
        demo/no-CDP mode.
    """
    os.makedirs(output_dir, exist_ok=True)
    filename = f"widget_{widget_id}_{uuid.uuid4().hex[:6]}.png"
    output_path = os.path.join(output_dir, filename)

    cdp_session = None
    try:
        from spec2sphere.browser.cdp_helpers import get_cdp_session_for_tenant

        cdp_session = await get_cdp_session_for_tenant(tenant_id, environment)
        if cdp_session is None:
            logger.warning(
                "No CDP session for tenant=%s env=%s — returning path-only placeholder",
                tenant_id,
                environment,
            )
            return output_path

        # Attempt element-scoped screenshot using known widget ID selectors
        widget_selector = f"[data-widget-id='{widget_id}'], [id='{widget_id}'], [aria-label*='{widget_id}']"
        if await cdp_session.element_exists(widget_selector):
            png_bytes: bytes = await cdp_session.screenshot_element(widget_selector)
        else:
            # Fall back to full-page screenshot
            logger.warning(
                "Widget selector not found for widget_id=%s — taking full-page screenshot",
                widget_id,
            )
            png_bytes = await cdp_session.screenshot()

        with open(output_path, "wb") as fh:
            fh.write(png_bytes)
        return os.path.abspath(output_path)

    except ImportError:
        logger.warning("cdp_helpers not yet available — returning path-only placeholder")
        return output_path
    except Exception as exc:  # noqa: BLE001
        logger.warning("capture_widget_screenshot CDP operation failed (%s) — returning path only", exc)
        return output_path
    finally:
        if cdp_session is not None:
            try:
                await cdp_session.close()
            except Exception:  # noqa: BLE001
                pass
