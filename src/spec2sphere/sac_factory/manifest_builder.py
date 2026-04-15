"""Manifest Builder — builds a deployment manifest dict from a SAC blueprint."""

from __future__ import annotations


def build_manifest(blueprint: dict) -> dict:
    """Build a deployment manifest from a SAC blueprint.

    Args:
        blueprint: dict with title, archetype, artifact_type, pages, interactions

    Returns:
        Manifest dict ready for serialisation / transport packaging.
    """
    title = blueprint.get("title", "Untitled")
    artifact_type = blueprint.get("artifact_type", "story")
    archetype = blueprint.get("archetype", "unknown")
    raw_pages = blueprint.get("pages", [])
    interactions = blueprint.get("interactions", {})
    navigation = interactions.get("navigation", [])

    pages: list[dict] = []
    total_widgets = 0

    for page in raw_pages:
        widgets = page.get("widgets", [])
        widget_count = len(widgets)
        total_widgets += widget_count
        pages.append(
            {
                "id": page.get("id", ""),
                "title": page.get("title", ""),
                "widget_count": widget_count,
                "widgets": widgets,
            }
        )

    # Collect unique filters across all pages
    all_filters: list[dict] = []
    seen_dimensions: set[str] = set()
    for page in raw_pages:
        for flt in page.get("filters", []):
            dim = flt.get("dimension", "")
            if dim and dim not in seen_dimensions:
                seen_dimensions.add(dim)
                all_filters.append(flt)

    return {
        "title": title,
        "artifact_type": artifact_type,
        "archetype": archetype,
        "pages": pages,
        "total_widgets": total_widgets,
        "filters": all_filters,
        "navigation": navigation,
        "transport_hints": {
            "include_data_models": True,
            "include_themes": True,
            "package_format": "tgz",
        },
    }
