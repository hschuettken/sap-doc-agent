"""Click Guide Generator — produces structured Markdown click-guides from SAC blueprints."""

from __future__ import annotations

_WIDGET_INSTRUCTIONS: dict[str, str] = {
    "kpi_tile": 'Insert → KPI Tile. Set title to "{title}". Bind measure to {binding}.',
    "bar_chart": 'Insert → Chart → Bar Chart. Set title to "{title}". Bind data to {binding}.',
    "line_chart": 'Insert → Chart → Line Chart. Set title to "{title}". Bind data to {binding}.',
    "variance_chart": 'Insert → Chart → Variance Chart. Set title to "{title}". Bind data to {binding}.',
    "waterfall_chart": 'Insert → Chart → Waterfall. Set title to "{title}". Bind data to {binding}.',
    "detail_table": 'Insert → Table. Set title to "{title}". Bind data to {binding}.',
    "ranked_bars": 'Insert → Chart → Bar Chart (horizontal). Sort descending. Set title to "{title}". Bind data to {binding}.',
    "driver_table": 'Insert → Table → Comparison Table. Set title to "{title}". Bind data to {binding}.',
    "pie_chart": 'Insert → Chart → Pie Chart. Set title to "{title}". Bind data to {binding}.',
}

_DEFAULT_INSTRUCTION = 'Insert widget of type "{type}". Set title to "{title}". Bind data to {binding}.'


def generate_click_guide(blueprint: dict) -> str:
    """Generate a structured Markdown click-guide from a SAC blueprint.

    Args:
        blueprint: dict with keys title, archetype, pages, interactions

    Returns:
        Markdown string with step-by-step instructions.
    """
    title = blueprint.get("title", "Untitled Story")
    archetype = blueprint.get("archetype", "unknown")
    pages = blueprint.get("pages", [])
    interactions = blueprint.get("interactions", {})
    navigation = interactions.get("navigation", [])

    lines: list[str] = []

    # Header
    lines.append(f"# SAC Click Guide: {title}")
    lines.append(f"\n**Archetype:** `{archetype}`\n")

    # Prerequisites
    lines.append("## Prerequisites\n")
    lines.append("1. Open SAC (SAP Analytics Cloud) and log in with your credentials.")
    lines.append("2. Navigate to **Stories** in the left-hand navigation panel.")
    lines.append(f"3. Create a new story or open the target story named **{title}**.")
    lines.append("4. Ensure you are in **Edit** mode before making changes.\n")

    # Per-page instructions
    for page_idx, page in enumerate(pages, start=1):
        page_title = page.get("title", f"Page {page_idx}")
        page_id = page.get("id", f"page_{page_idx}")
        widgets = page.get("widgets", [])
        filters = page.get("filters", [])

        lines.append(f"## Page {page_idx}: {page_title}\n")

        if widgets:
            lines.append("### Widget Setup\n")
            for w_idx, widget in enumerate(widgets, start=1):
                w_type = widget.get("type", "unknown")
                w_title = widget.get("title", "Untitled")
                w_binding = widget.get("binding", "N/A")

                template = _WIDGET_INSTRUCTIONS.get(w_type, _DEFAULT_INSTRUCTION)
                instruction = template.format(
                    title=w_title,
                    binding=w_binding,
                    type=w_type,
                )
                lines.append(f"{w_idx}. {instruction}")
            lines.append("")

        if filters:
            lines.append("### Filter Setup\n")
            for f_idx, flt in enumerate(filters, start=1):
                dimension = flt.get("dimension", "unknown")
                filter_type = flt.get("type", "dropdown")
                lines.append(
                    f"{f_idx}. Add filter: dimension **{dimension}**, type **{filter_type}**. "
                    f"In the toolbar, select **Add Filter → {dimension}** and choose **{filter_type}**."
                )
            lines.append("")

    # Navigation setup
    if navigation:
        lines.append("## Navigation Setup\n")
        for nav_idx, nav in enumerate(navigation, start=1):
            from_page = nav.get("from", "unknown")
            to_page = nav.get("to", "unknown")
            trigger = nav.get("trigger", "click")
            lines.append(
                f"{nav_idx}. Configure navigation from **{from_page}** to **{to_page}** "
                f"triggered by **{trigger}**. Select the source widget/button → "
                f"right-click → **Navigation** → set target page to **{to_page}**."
            )
        lines.append("")

    # Rollback and undo hints
    lines.append("## Rollback & Undo Hints\n")
    lines.append("- **Undo last action:** `Ctrl+Z` (Windows) / `Cmd+Z` (Mac)")
    lines.append("- **Save Version:** Use **File → Save Version** to create a named checkpoint before major changes.")
    lines.append("- **Version History:** Navigate to **File → Version History** to restore a previous state.")
    lines.append("- **Rollback to version:** Select the desired version in Version History and click **Restore**.")
    lines.append("- If a widget is misconfigured, delete it (select → `Delete` key) and re-insert from scratch.\n")

    # Verification checklist
    lines.append("## Verification Checklist\n")
    lines.append("- [ ] All pages are present and named correctly")
    lines.append("- [ ] All widgets display data (no empty/error state)")
    lines.append("- [ ] Filters respond to user input and update visuals")
    lines.append("- [ ] Navigation links work between pages")
    lines.append("- [ ] Story is saved (no unsaved indicator in title bar)")
    lines.append("- [ ] Story is published / shared with intended audience")
    lines.append("")

    return "\n".join(lines)
