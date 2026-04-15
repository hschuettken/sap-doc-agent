"""Design QA — scores SAC page designs against archetype expectations."""

from __future__ import annotations

# Archetype → {widget_type: (min_count, max_count)}
_ARCHETYPE_EXPECTATIONS: dict[str, dict[str, tuple[int, int]]] = {
    "management_cockpit": {
        "kpi_tile": (3, 8),
        "bar_chart": (1, 4),
        "variance_chart": (1, 3),
    },
    "exec_overview": {
        "kpi_tile": (3, 6),
        "bar_chart": (1, 3),
        "line_chart": (0, 2),
    },
    "variance_analysis": {
        "variance_chart": (1, 3),
        "detail_table": (1, 2),
        "waterfall_chart": (0, 2),
    },
    "operational_dashboard": {
        "kpi_tile": (2, 6),
        "line_chart": (1, 4),
        "bar_chart": (0, 3),
    },
    "self_service": {
        "detail_table": (1, 3),
        "bar_chart": (0, 4),
        "pie_chart": (0, 2),
    },
}

_GENERIC_TITLES = {"page 1", "page 2", "page 3", "dashboard", "untitled", "new page"}

# Action-verb prefixes — titles should ideally start with one of these
_ACTION_VERBS = {
    "analyze",
    "compare",
    "monitor",
    "track",
    "view",
    "review",
    "explore",
    "manage",
    "plan",
    "report",
    "assess",
    "evaluate",
}


def _score_archetype_compliance(widgets: list[dict], archetype: str) -> tuple[float, list[str]]:
    """Score widget distribution against archetype expectations (0-100)."""
    expectations = _ARCHETYPE_EXPECTATIONS.get(archetype, {})
    if not expectations:
        return 80.0, []  # unknown archetype — neutral score

    counts: dict[str, int] = {}
    for w in widgets:
        wtype = w.get("type", "unknown")
        counts[wtype] = counts.get(wtype, 0) + 1

    violations: list[str] = []
    penalty = 0.0
    for wtype, (min_c, max_c) in expectations.items():
        actual = counts.get(wtype, 0)
        if actual < min_c:
            penalty += 15.0
            violations.append(f"archetype '{archetype}' expects at least {min_c} {wtype} widget(s), found {actual}")
        elif actual > max_c:
            penalty += 15.0
            violations.append(f"archetype '{archetype}' expects at most {max_c} {wtype} widget(s), found {actual}")

    return max(0.0, 100.0 - penalty), violations


def _score_chart_choice(widgets: list[dict]) -> tuple[float, list[str]]:
    """Penalise pie charts (-10 each). Score 0-100."""
    violations: list[str] = []
    penalty = 0.0
    for w in widgets:
        if w.get("type") == "pie_chart":
            penalty += 10.0
            violations.append(f"pie_chart '{w.get('title', '')}' is discouraged — prefer bar/variance chart")
    return max(0.0, 100.0 - penalty), violations


def _score_kpi_density(widgets: list[dict]) -> tuple[float, list[str]]:
    """Penalise more than 8 KPI tiles per page (-15 per excess). Score 0-100."""
    kpi_count = sum(1 for w in widgets if w.get("type") == "kpi_tile")
    violations: list[str] = []
    if kpi_count <= 8:
        return 100.0, violations
    excess = kpi_count - 8
    penalty = excess * 15.0
    violations.append(f"kpi density too high: {kpi_count} KPI tiles (max 8 recommended)")
    return max(0.0, 100.0 - penalty), violations


def _score_title_quality(page: dict, widgets: list[dict]) -> tuple[float, list[str]]:
    """Penalise generic page/widget titles. Score 0-100."""
    violations: list[str] = []
    penalty = 0.0

    page_title = page.get("title", "").strip()
    if page_title.lower() in _GENERIC_TITLES:
        penalty += 20.0
        violations.append(f"generic page title '{page_title}' — use a descriptive action-oriented title")

    for w in widgets:
        w_title = w.get("title", "").strip()
        if w_title.lower() in _GENERIC_TITLES:
            penalty += 10.0
            violations.append(f"generic widget title '{w_title}'")

    # Check if page title starts with an action verb
    first_word = page_title.split()[0].lower() if page_title else ""
    if page_title and first_word not in _ACTION_VERBS and page_title.lower() not in _GENERIC_TITLES:
        # Soft penalty — not action-verb start
        penalty += 10.0
        violations.append(
            f"page title '{page_title}' does not start with an action verb (e.g. Analyze, Compare, Monitor)"
        )

    return max(0.0, 100.0 - penalty), violations


def _score_filter_usability(filters: list[dict]) -> tuple[float, list[str]]:
    """Penalise missing or excessive filters. Score 0-100."""
    violations: list[str] = []
    count = len(filters)
    if count == 0:
        return 40.0, ["no filters configured — users cannot slice the data"]
    if count > 6:
        return 60.0, [f"too many filters ({count}) — keep to 6 or fewer for usability"]
    return 100.0, violations


def _score_navigation_clarity(page: dict) -> tuple[float, list[str]]:
    """Default 80 for a single-page check — navigation is validated at story level."""
    return 80.0, []


def _score_layout_consistency(widgets: list[dict]) -> tuple[float, list[str]]:
    """Penalise too many (>12) or too few (<2) widgets per page. Score 0-100."""
    violations: list[str] = []
    count = len(widgets)
    if count > 12:
        violations.append(f"too many widgets ({count}) on one page — split into multiple pages")
        return 60.0, violations
    if count < 2:
        violations.append(f"too few widgets ({count}) — page looks sparse")
        return 60.0, violations
    return 100.0, violations


def score_design(page: dict, archetype: str = "exec_overview") -> dict:
    """Score a SAC page design against archetype and usability heuristics.

    Args:
        page: Page dict with keys: title, widgets (list), filters (list).
        archetype: Archetype key (e.g. "management_cockpit", "exec_overview").

    Returns:
        Dict with total_score (0-100), breakdown (dimension→score), violations (list[str]).
    """
    widgets: list[dict] = page.get("widgets", [])
    filters: list[dict] = page.get("filters", [])

    # Weighted dimensions
    weights = {
        "archetype_compliance": 0.30,
        "chart_choice": 0.15,
        "kpi_density": 0.10,
        "title_quality": 0.10,
        "filter_usability": 0.10,
        "navigation_clarity": 0.10,
        "layout_consistency": 0.15,
    }

    scores: dict[str, float] = {}
    all_violations: list[str] = []

    s, v = _score_archetype_compliance(widgets, archetype)
    scores["archetype_compliance"] = s
    all_violations.extend(v)

    s, v = _score_chart_choice(widgets)
    scores["chart_choice"] = s
    all_violations.extend(v)

    s, v = _score_kpi_density(widgets)
    scores["kpi_density"] = s
    all_violations.extend(v)

    s, v = _score_title_quality(page, widgets)
    scores["title_quality"] = s
    all_violations.extend(v)

    s, v = _score_filter_usability(filters)
    scores["filter_usability"] = s
    all_violations.extend(v)

    s, v = _score_navigation_clarity(page)
    scores["navigation_clarity"] = s
    all_violations.extend(v)

    s, v = _score_layout_consistency(widgets)
    scores["layout_consistency"] = s
    all_violations.extend(v)

    total = sum(scores[dim] * weight for dim, weight in weights.items())

    return {
        "total_score": round(total, 1),
        "breakdown": {dim: round(sc, 1) for dim, sc in scores.items()},
        "violations": all_violations,
    }
