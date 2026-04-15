"""Design Quality Scoring Engine.

Scores a dashboard blueprint or knowledge_item against the Horvath design
standard.  Each of six sub-dimensions contributes a weighted score; the
weighted sum is the total (0-100).

Weight allocation (Spec 8.4):
  archetype_compliance  30 %
  layout_readability    25 %
  chart_choice          15 %
  title_quality         10 %
  filter_usability      10 %
  navigation_clarity    10 %
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Weight constants (must sum to 1.0)
_W_ARCHETYPE = 0.30
_W_READABILITY = 0.25
_W_CHART = 0.15
_W_TITLE = 0.10
_W_FILTER = 0.10
_W_NAV = 0.10


@dataclass
class DesignScore:
    total: float  # 0-100, weighted sum
    archetype_compliance: float  # 0-100
    layout_readability: float  # 0-100
    chart_choice: float  # 0-100
    title_quality: float  # 0-100
    filter_usability: float  # 0-100
    navigation_clarity: float  # 0-100
    details: dict = field(default_factory=dict)  # per-category breakdown notes


# ---------------------------------------------------------------------------
# Known good / bad patterns
# ---------------------------------------------------------------------------

# Chart types appropriate per semantic data role
_GOOD_CHART_FOR_ROLE: dict[str, set[str]] = {
    "trend": {"line_chart", "area_chart", "sparkline"},
    "comparison": {"bar_chart", "column_chart", "bullet_chart"},
    "composition": {"stacked_bar", "pie_chart", "treemap"},
    "relationship": {"scatter_plot", "bubble_chart"},
    "distribution": {"histogram", "box_plot"},
    "variance": {"waterfall", "bar_chart"},
    "kpi": {"kpi_tile", "gauge"},
    "geo": {"map", "heat_matrix"},
}

_ALL_KNOWN_CHART_TYPES: set[str] = {ct for types in _GOOD_CHART_FOR_ROLE.values() for ct in types}

_GENERIC_TITLE_PATTERNS = {
    "chart 1",
    "chart1",
    "widget 1",
    "widget1",
    "untitled",
    "new chart",
    "kpi 1",
    "kpi1",
    "table 1",
    "table1",
    "visualization",
}

# Archetype names from Section 8.2
_KNOWN_ARCHETYPES: set[str] = {
    "exec_overview",
    "management_cockpit",
    "variance_analysis",
    "regional_performance",
    "product_drill",
    "driver_analysis",
    "exception_dashboard",
    "table_first",
    "guided_analysis",
}


# ---------------------------------------------------------------------------
# Sub-scorers
# ---------------------------------------------------------------------------


def _score_archetype_compliance(
    bp: dict,
    archetypes: Optional[list[dict]],
) -> tuple[float, dict]:
    """Does the blueprint declare a known archetype type?

    Full score (100) if archetype matches a known layout archetype.
    Partial score (50) if a custom/unknown archetype is declared.
    Zero if no archetype is declared.
    """
    details: dict[str, Any] = {}

    # Blueprint may declare archetype via different keys
    arch_name = (bp.get("archetype") or bp.get("archetype_type") or bp.get("layout_archetype") or "").lower().strip()

    if not arch_name:
        details["issue"] = "No archetype declared"
        return 0.0, details

    # Check against seeded Horvath archetypes
    known_names = _KNOWN_ARCHETYPES.copy()
    if archetypes:
        for a in archetypes:
            n = (a.get("name") or a.get("archetype_type") or "").lower()
            if n:
                known_names.add(n)

    if arch_name in known_names:
        details["matched"] = arch_name
        return 100.0, details

    details["matched"] = arch_name
    details["issue"] = "Archetype not in Horvath standard set"
    return 50.0, details


def _score_layout_readability(bp: dict, tokens: Optional[dict]) -> tuple[float, dict]:
    """Score based on widget count, density setting, and whitespace.

    Scoring:
    - Widget count within density limit  → up to 60 pts
    - Density token declared             → 20 pts
    - Whitespace/padding token present   → 20 pts
    """
    details: dict[str, Any] = {}
    score = 0.0

    # Collect widget count from various blueprint shapes
    widgets = bp.get("widgets") or bp.get("widget_slots") or []
    widget_count = len(widgets) if isinstance(widgets, list) else (widgets or 0)

    density = bp.get("density") or bp.get("recommended_density") or ""

    # Determine limit from token data or defaults
    density_limits = {"sparse": 4, "medium": 8, "dense": 12}
    if tokens and "density" in tokens:
        for d_name, d_val in tokens["density"].items():
            if isinstance(d_val, dict) and "kpi_limit" in d_val:
                density_limits[d_name] = int(d_val["kpi_limit"])

    limit = density_limits.get(density.lower(), 8)

    # Widget count score (60 pts)
    if widget_count == 0:
        details["widget_count"] = "no widgets found"
        count_score = 30.0  # Neutral — we can't penalise for empty blueprint
    elif widget_count <= limit:
        count_score = 60.0
        details["widget_count"] = f"{widget_count} (within limit {limit})"
    else:
        # Proportional penalty
        excess_ratio = min((widget_count - limit) / limit, 1.0)
        count_score = max(0.0, 60.0 * (1.0 - excess_ratio))
        details["widget_count"] = f"{widget_count} (exceeds limit {limit})"

    score += count_score

    # Density declared (20 pts)
    if density:
        score += 20.0
        details["density"] = density
    else:
        details["density_issue"] = "No density declared"

    # Spacing/whitespace token present (20 pts)
    has_spacing = tokens and "spacing" in tokens and bool(tokens["spacing"])
    if has_spacing:
        score += 20.0
    else:
        details["spacing_issue"] = "No spacing token configured"

    return min(score, 100.0), details


def _score_chart_choice(bp: dict) -> tuple[float, dict]:
    """Evaluate whether chart types are appropriate.

    Scoring:
    - All charts from known set          → base 100
    - Deduct 20 per unknown chart type
    - If no charts declared              → 50 (neutral)
    """
    details: dict[str, Any] = {}
    widgets = bp.get("widgets") or []
    if not isinstance(widgets, list):
        return 50.0, {"issue": "Cannot parse widgets list"}

    chart_types = [(w.get("chart_type") or w.get("widget_type") or "").lower() for w in widgets if isinstance(w, dict)]
    chart_types = [ct for ct in chart_types if ct]

    if not chart_types:
        return 50.0, {"note": "No chart types declared — neutral score"}

    unknown = [ct for ct in chart_types if ct not in _ALL_KNOWN_CHART_TYPES]
    penalty = len(unknown) * 20
    score = max(0.0, 100.0 - penalty)

    details["chart_types"] = chart_types
    if unknown:
        details["unknown_types"] = unknown
    return score, details


def _score_title_quality(bp: dict) -> tuple[float, dict]:
    """Evaluate title and widget label quality.

    Rules:
    - Dashboard title present and not generic → 50 pts
    - At least half of widget titles non-generic → 50 pts
    """
    details: dict[str, Any] = {}
    score = 0.0

    # Dashboard-level title
    title = (bp.get("title") or bp.get("name") or "").strip().lower()
    if title and title not in _GENERIC_TITLE_PATTERNS:
        score += 50.0
    else:
        details["title_issue"] = f"Missing or generic dashboard title: '{title}'"

    # Widget-level titles
    widgets = bp.get("widgets") or []
    if isinstance(widgets, list) and widgets:
        widget_titles = [
            (w.get("title") or w.get("name") or "").strip().lower() for w in widgets if isinstance(w, dict)
        ]
        non_generic = [t for t in widget_titles if t and t not in _GENERIC_TITLE_PATTERNS]
        ratio = len(non_generic) / len(widget_titles) if widget_titles else 0
        score += 50.0 * ratio
        details["widget_title_ratio"] = f"{len(non_generic)}/{len(widget_titles)} non-generic"
    else:
        score += 25.0  # Neutral if no widgets

    return min(score, 100.0), details


def _score_filter_usability(bp: dict) -> tuple[float, dict]:
    """Check for filter presence, position, and scope.

    Scoring:
    - Filters declared                → 40 pts
    - Filters positioned in header    → 30 pts
    - Global scope filter present     → 30 pts
    """
    details: dict[str, Any] = {}
    score = 0.0

    filters = bp.get("filters") or bp.get("filter_widgets") or []
    if not isinstance(filters, list):
        filters = []

    if filters:
        score += 40.0
        details["filter_count"] = len(filters)

        # Check positioning
        positioned_header = any(
            (f.get("position") or "").lower() in ("header", "top") for f in filters if isinstance(f, dict)
        )
        if positioned_header:
            score += 30.0
        else:
            details["position_issue"] = "No filters placed in header"

        # Check for global-scope filter
        global_filter = any(
            (f.get("scope") or f.get("filter_scope") or "").lower() == "global" for f in filters if isinstance(f, dict)
        )
        if global_filter:
            score += 30.0
        else:
            details["scope_issue"] = "No global-scope filter declared"
    else:
        details["issue"] = "No filters declared"

    return min(score, 100.0), details


def _score_navigation_clarity(bp: dict) -> tuple[float, dict]:
    """Evaluate navigation structure.

    Scoring:
    - Page count <= 5           → 40 pts (more pages = proportional deduction)
    - Breadcrumb declared       → 30 pts
    - Drill paths defined       → 30 pts
    """
    details: dict[str, Any] = {}
    score = 0.0

    pages = bp.get("pages") or []
    page_count = len(pages) if isinstance(pages, list) else int(pages or 1)

    if page_count <= 5:
        score += 40.0
    else:
        ratio = 5.0 / page_count
        score += 40.0 * ratio
        details["page_count"] = f"{page_count} (exceeds recommended 5)"

    has_breadcrumb = bool(bp.get("breadcrumb") or bp.get("breadcrumbs") or bp.get("navigation", {}).get("breadcrumb"))
    if has_breadcrumb:
        score += 30.0
    else:
        details["breadcrumb_issue"] = "No breadcrumb navigation declared"

    drill_paths = bp.get("drill_paths") or bp.get("drilldowns") or []
    if isinstance(drill_paths, list) and drill_paths:
        score += 30.0
        details["drill_paths"] = len(drill_paths)
    elif isinstance(drill_paths, bool) and drill_paths:
        score += 30.0
    else:
        details["drill_issue"] = "No drill paths defined"

    return min(score, 100.0), details


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def score_dashboard(
    blueprint_or_item: dict,
    archetypes: Optional[list[dict]] = None,
    tokens: Optional[dict] = None,
) -> DesignScore:
    """Score a dashboard blueprint against the Horvath design standard.

    Accepts either a raw blueprint dict or a knowledge_item row (the scorer
    will look for the blueprint under the 'content' key as a nested dict, or
    parse the item directly if it looks like a blueprint).

    Parameters
    ----------
    blueprint_or_item:
        Dashboard blueprint dict or a knowledge_item record from the DB.
    archetypes:
        Optional list of archetype dicts (from list_archetypes) to extend
        the known-archetype check.
    tokens:
        Optional resolved design profile dict (from resolve_design_profile)
        to inform density limit lookups.

    Returns
    -------
    DesignScore with total and per-dimension breakdown.
    """
    # Normalise input: accept knowledge_item rows too
    bp = blueprint_or_item
    if "content" in bp and isinstance(bp["content"], dict):
        bp = bp["content"]
    elif "definition" in bp and isinstance(bp["definition"], dict):
        bp = bp["definition"]

    arch_score, arch_details = _score_archetype_compliance(bp, archetypes)
    read_score, read_details = _score_layout_readability(bp, tokens)
    chart_score, chart_details = _score_chart_choice(bp)
    title_score, title_details = _score_title_quality(bp)
    filt_score, filt_details = _score_filter_usability(bp)
    nav_score, nav_details = _score_navigation_clarity(bp)

    total = (
        arch_score * _W_ARCHETYPE
        + read_score * _W_READABILITY
        + chart_score * _W_CHART
        + title_score * _W_TITLE
        + filt_score * _W_FILTER
        + nav_score * _W_NAV
    )

    details = {
        "archetype_compliance": arch_details,
        "layout_readability": read_details,
        "chart_choice": chart_details,
        "title_quality": title_details,
        "filter_usability": filt_details,
        "navigation_clarity": nav_details,
    }

    return DesignScore(
        total=round(total, 2),
        archetype_compliance=round(arch_score, 2),
        layout_readability=round(read_score, 2),
        chart_choice=round(chart_score, 2),
        title_quality=round(title_score, 2),
        filter_usability=round(filt_score, 2),
        navigation_clarity=round(nav_score, 2),
        details=details,
    )
