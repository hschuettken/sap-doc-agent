"""Screenshot Engine — pixel diff utilities and screenshot capture stubs."""

from __future__ import annotations

import os
import uuid

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


async def capture_page_screenshot(
    tenant_id: object,
    environment: str,
    page_id: str,
    output_dir: str = "output/screenshots",
) -> str:
    """Capture a screenshot of a SAC story page.

    Args:
        tenant_id: Tenant identifier.
        environment: Environment name (e.g. "prod", "dev").
        page_id: SAC page identifier.
        output_dir: Directory to write the PNG file.

    Returns:
        Absolute path of the saved screenshot (stub — returns path only).
    """
    os.makedirs(output_dir, exist_ok=True)
    filename = f"page_{page_id}_{uuid.uuid4().hex[:6]}.png"
    return os.path.join(output_dir, filename)


async def capture_widget_screenshot(
    tenant_id: object,
    environment: str,
    widget_id: str,
    output_dir: str = "output/screenshots",
) -> str:
    """Capture a screenshot of a specific SAC widget.

    Args:
        tenant_id: Tenant identifier.
        environment: Environment name (e.g. "prod", "dev").
        widget_id: SAC widget identifier.
        output_dir: Directory to write the PNG file.

    Returns:
        Absolute path of the saved screenshot (stub — returns path only).
    """
    os.makedirs(output_dir, exist_ok=True)
    filename = f"widget_{widget_id}_{uuid.uuid4().hex[:6]}.png"
    return os.path.join(output_dir, filename)
