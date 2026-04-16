"""SAC Blueprint generator.

Generates SAP Analytics Cloud (SAC) blueprints from approved HLA documents.
Each SAC reporting need identified in the HLA ``sac_reporting_strategy`` is
expanded into a full page/widget blueprint with interaction definitions and
design-token–backed styling.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Optional

from spec2sphere.db import _get_conn
from spec2sphere.llm.base import LLMProvider
from spec2sphere.llm.structured import generate_json_with_retry
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants — widget type mapping
# ---------------------------------------------------------------------------

_KPI_TO_WIDGET: dict[str, str] = {
    "variance": "chart_waterfall",
    "trend": "chart_line",
    "ranking": "chart_bar_horizontal",
    "composition": "chart_donut",
    "comparison": "chart_bar_grouped",
    "geographic": "chart_geo_map",
    "single_value": "kpi_tile",
    "table": "crosstab",
    "distribution": "chart_histogram",
    "correlation": "chart_scatter",
}

# Artifact type decision thresholds
_STORY_ARCHETYPE_KEYWORDS = {"executive", "overview", "summary", "operational", "kpi", "reporting"}
_APP_ARCHETYPE_KEYWORDS = {"planning", "guided", "workflow", "wizard", "scripted", "complex", "interactive"}
_WIDGET_ARCHETYPE_KEYWORDS = {"embedded", "custom", "branded", "unique", "specialized"}


# ---------------------------------------------------------------------------
# LLM schema
# ---------------------------------------------------------------------------

_BLUEPRINT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "artifact_type": {
            "type": "string",
            "enum": ["story", "analytic_application", "custom_widget"],
        },
        "artifact_type_rationale": {"type": "string"},
        "artifact_type_confidence": {"type": "number"},
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "page_id": {"type": "string"},
                    "title": {"type": "string"},
                    "layout_archetype": {"type": "string"},
                    "widgets": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "widget_id": {"type": "string"},
                                "type": {"type": "string"},
                                "title": {"type": "string"},
                                "metric_binding": {"type": "object"},
                                "size": {"type": "object"},
                                "position": {"type": "object"},
                            },
                            "required": ["widget_id", "type", "title"],
                        },
                    },
                },
                "required": ["page_id", "title", "widgets"],
            },
        },
        "interactions": {"type": "object"},
    },
    "required": ["title", "artifact_type", "pages"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _row_to_dict(row) -> dict:
    """Convert asyncpg Record to a plain dict, serialising UUID and datetime."""
    d = dict(row)
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            d[k] = str(v)
    return d


def _count_widgets(pages: list[dict]) -> int:
    return sum(len(page.get("widgets", [])) for page in pages)


def _determine_performance_class(widget_count: int) -> str:
    if widget_count < 5:
        return "lightweight"
    if widget_count <= 15:
        return "standard"
    return "heavy"


def _decide_artifact_type(dashboard_need: dict) -> tuple[str, str, float]:
    """Heuristic pre-decision before LLM call.

    Returns (artifact_type, rationale, confidence). The LLM may override this;
    we pass it as a hint rather than a mandate.

    Decision logic:
    - custom_widget: explicit justification field with 'custom'/'embed'/'branded'.
    - analytic_application: complex interactivity, planning, scripted flows.
    - story: default — standard reporting, moderate interaction, easy maintenance.
    """
    recommendation = (dashboard_need.get("recommendation") or "").lower()
    archetype = (dashboard_need.get("archetype") or "").lower()
    rationale_text = (dashboard_need.get("rationale") or "").lower()
    need_text = (dashboard_need.get("dashboard_need") or "").lower()

    combined = f"{recommendation} {archetype} {rationale_text} {need_text}"

    if recommendation == "custom_widget" or any(kw in combined for kw in _WIDGET_ARCHETYPE_KEYWORDS):
        return (
            "custom_widget",
            "Dashboard need describes a unique UX or branded visualisation requiring a custom SAC widget.",
            0.75,
        )

    if recommendation == "analytic_application" or any(kw in combined for kw in _APP_ARCHETYPE_KEYWORDS):
        return (
            "analytic_application",
            "Dashboard need involves complex interactivity, scripted behavior, or guided planning flows.",
            0.80,
        )

    return (
        "story",
        "Standard reporting need with moderate interaction — a Story provides the best maintenance/delivery balance.",
        0.85,
    )


def _enforce_widget_types(pages: list[dict]) -> list[dict]:
    """Post-process LLM output to enforce KPI-to-widget type mapping.

    If a widget has metric_binding with a kpi_type hint, ensure the widget
    type matches the canonical mapping.
    """
    for page in pages:
        for widget in page.get("widgets", []):
            binding = widget.get("metric_binding") or {}
            kpi_type = binding.get("kpi_type", "").lower()
            if kpi_type and kpi_type in _KPI_TO_WIDGET:
                canonical = _KPI_TO_WIDGET[kpi_type]
                if widget.get("type") != canonical:
                    widget["type"] = canonical
    return pages


def _apply_style_tokens(widget: dict, design_tokens: list[dict]) -> dict:
    """Attach style_tokens to a widget dict based on customer design tokens."""
    if not design_tokens:
        return widget

    color_token = next(
        (t for t in design_tokens if t.get("token_type") == "color" and "primary" in (t.get("token_name") or "")),
        None,
    )
    typography_token = next(
        (t for t in design_tokens if t.get("token_type") == "typography"),
        None,
    )

    style: dict = {}
    if color_token:
        style["color_series"] = color_token.get("token_name", "brand_primary")
        tv = color_token.get("token_value")
        if tv:
            style["color_value"] = tv if isinstance(tv, str) else json.dumps(tv)
    if typography_token:
        style["font_family"] = typography_token.get("token_name", "default")

    if style:
        widget["style_tokens"] = style
    return widget


def _build_system_prompt(design_tokens: list[dict], archetypes: list[dict]) -> str:
    archetype_names = [a.get("name", "") for a in archetypes if a.get("name")]
    token_summary = ", ".join(f"{t.get('token_type')}/{t.get('token_name')}" for t in design_tokens[:8])
    return (
        "You are a senior SAP Analytics Cloud architect. Generate a complete SAC blueprint "
        "for the given dashboard need. Design pages with clear titles, layout archetypes, and "
        "widgets. Choose widget types based on KPI semantics: "
        "variance→waterfall, trend→line chart, ranking→horizontal bar, composition→donut, "
        "comparison→grouped bar, geographic→geo map, single value→KPI tile, table→crosstab. "
        "Assign metric_binding (kpi + dimensions), size (cols 1-12, rows 1-8), and "
        "position (col, row) to every widget. "
        "For interactions, include global_filters (dimension, type), page_navigation "
        "(from/to/trigger), and drill_behavior (from_kpi, drill_to, filter_pass). "
        "Apply the customer design profile — "
        f"available layout archetypes: {archetype_names or ['executive_summary', 'operational', 'detail']}. "
        f"Available design tokens: {token_summary or 'none provided'}. "
        "Decide artifact_type deliberately: "
        "  story — standard reporting, easy maintenance; "
        "  analytic_application — complex interactivity, planning, guided flows; "
        "  custom_widget — unique UX, branded viz (requires justification). "
        "Provide artifact_type_rationale and artifact_type_confidence (0.0-1.0)."
    )


def _build_user_prompt(
    dashboard_need: dict,
    hla_content: dict,
    hint_type: str,
    hint_rationale: str,
) -> str:
    need_json = json.dumps(dashboard_need, indent=2)
    sac_strategy = json.dumps(hla_content.get("sac_reporting_strategy", [])[:3], indent=2)
    views_summary = [
        {"name": v.get("name"), "layer": v.get("layer"), "type": v.get("type")}
        for v in hla_content.get("views", [])
        if v.get("layer") in ("CONSUMPTION", "MART")
    ][:8]

    return (
        f"Dashboard need:\n{need_json}\n\n"
        f"SAC reporting strategy context:\n{sac_strategy}\n\n"
        f"Available consumption/mart views (for metric binding):\n{json.dumps(views_summary, indent=2)}\n\n"
        f"Pre-analysis hint — artifact type: {hint_type} ({hint_rationale}). "
        "Override only if the requirement clearly warrants a different type.\n\n"
        "Generate the full SAC blueprint. Include at least 1 page with at least 1 widget."
    )


# ---------------------------------------------------------------------------
# DB fetch helpers
# ---------------------------------------------------------------------------


async def _fetch_hla(conn, hla_id: str) -> dict:
    row = await conn.fetchrow(
        "SELECT * FROM hla_documents WHERE id = $1::uuid",
        hla_id,
    )
    if row is None:
        raise ValueError(f"HLA document {hla_id} not found")
    doc = _row_to_dict(row)
    content = doc.get("content") or {}
    if isinstance(content, str):
        content = json.loads(content)
    doc["content"] = content
    return doc


async def _fetch_design_tokens(conn, customer_id) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM design_tokens WHERE customer_id = $1 ORDER BY token_type, token_name",
        customer_id,
    )
    result = []
    for r in rows:
        d = _row_to_dict(r)
        tv = d.get("token_value")
        if isinstance(tv, str):
            try:
                d["token_value"] = json.loads(tv)
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


async def _fetch_layout_archetypes(conn, customer_id) -> list[dict]:
    rows = await conn.fetch(
        "SELECT * FROM layout_archetypes WHERE customer_id = $1 ORDER BY name",
        customer_id,
    )
    result = []
    for r in rows:
        d = _row_to_dict(r)
        defn = d.get("definition")
        if isinstance(defn, str):
            try:
                d["definition"] = json.loads(defn)
            except (json.JSONDecodeError, TypeError):
                pass
        result.append(d)
    return result


async def _insert_blueprint(
    conn,
    *,
    project_id,
    tech_spec_id: Optional[str],
    title: str,
    audience: str,
    archetype: str,
    style_profile: dict,
    pages: list[dict],
    interactions: dict,
    performance_class: str,
    artifact_type: str,
) -> uuid.UUID:
    blueprint_id = uuid.uuid4()
    await conn.execute(
        """
        INSERT INTO sac_blueprints
            (id, project_id, tech_spec_id, title, audience, archetype,
             style_profile, pages, interactions, performance_class, status, created_at)
        VALUES (
            $1, $2, $3::uuid, $4, $5, $6,
            $7::jsonb, $8::jsonb, $9::jsonb, $10, 'draft', NOW()
        )
        """,
        blueprint_id,
        project_id,
        tech_spec_id,
        title,
        audience,
        archetype or artifact_type,
        json.dumps(style_profile),
        json.dumps(pages),
        json.dumps(interactions),
        performance_class,
    )
    return blueprint_id


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_blueprint(
    hla_id: str,
    ctx: ContextEnvelope,
    llm: LLMProvider,
    tech_spec_id: Optional[str] = None,
) -> dict:
    """Generate SAC blueprints from an approved HLA document.

    For each dashboard need listed in the HLA's ``sac_reporting_strategy``,
    an LLM call produces a full page/widget/interaction blueprint which is
    stored as a ``sac_blueprints`` record.

    Returns a summary dict for the *first* (primary) blueprint generated:
    ``{"blueprint_id": str, "title": str, "artifact_type": str,
       "page_count": int, "widget_count": int, "status": "draft"}``

    If the HLA contains multiple dashboard needs, all are generated and the
    first one's ID is returned.  Callers can use ``list_blueprints`` to
    retrieve all results for the project.
    """
    # --- 1. Fetch HLA and supporting customer data ---
    conn = await _get_conn()
    try:
        hla = await _fetch_hla(conn, hla_id)
        design_tokens = await _fetch_design_tokens(conn, ctx.customer_id)
        archetypes = await _fetch_layout_archetypes(conn, ctx.customer_id)
    finally:
        await conn.close()

    hla_content: dict = hla.get("content") or {}
    sac_strategy: list[dict] = hla_content.get("sac_reporting_strategy") or []

    if not sac_strategy:
        logger.warning("HLA %s has no sac_reporting_strategy — generating a single default blueprint", hla_id)
        sac_strategy = [
            {
                "dashboard_need": hla.get("narrative") or "General SAC reporting dashboard",
                "recommendation": "story",
                "rationale": "Default single-story blueprint (no explicit SAC strategy in HLA).",
                "audience": "all",
                "archetype": "executive_summary",
            }
        ]

    system_prompt = _build_system_prompt(design_tokens, archetypes)

    # Build style profile from design tokens for storage
    style_profile: dict = {
        "colors": {t["token_name"]: t.get("token_value") for t in design_tokens if t.get("token_type") == "color"},
        "typography": {
            t["token_name"]: t.get("token_value") for t in design_tokens if t.get("token_type") == "typography"
        },
        "spacing": {t["token_name"]: t.get("token_value") for t in design_tokens if t.get("token_type") == "spacing"},
    }

    first_blueprint_id: Optional[str] = None
    first_result: Optional[dict] = None

    for idx, dashboard_need in enumerate(sac_strategy):
        # --- 2. Pre-decision heuristic ---
        hint_type, hint_rationale, hint_confidence = _decide_artifact_type(dashboard_need)

        # --- 3. LLM generation ---
        user_prompt = _build_user_prompt(dashboard_need, hla_content, hint_type, hint_rationale)

        logger.info(
            "Generating SAC blueprint %d/%d for HLA %s (hint: %s)",
            idx + 1,
            len(sac_strategy),
            hla_id,
            hint_type,
        )

        blueprint_data = await generate_json_with_retry(
            provider=llm,
            prompt=user_prompt,
            schema=_BLUEPRINT_SCHEMA,
            system=system_prompt,
            max_retries=3,
            tier="large",
        )

        if blueprint_data is None:
            logger.warning(
                "LLM returned None for blueprint %d/%d (HLA %s) — using minimal fallback",
                idx + 1,
                len(sac_strategy),
                hla_id,
            )
            blueprint_data = {
                "title": dashboard_need.get("dashboard_need", "Untitled Blueprint"),
                "artifact_type": hint_type,
                "artifact_type_rationale": hint_rationale,
                "artifact_type_confidence": hint_confidence,
                "pages": [
                    {
                        "page_id": "p1",
                        "title": "Overview",
                        "layout_archetype": dashboard_need.get("archetype", "executive_summary"),
                        "widgets": [
                            {
                                "widget_id": "w1",
                                "type": "kpi_tile",
                                "title": "Key Metric",
                                "metric_binding": {"kpi": "primary_kpi", "dimensions": ["time"]},
                                "size": {"cols": 3, "rows": 2},
                                "position": {"col": 0, "row": 0},
                            }
                        ],
                    }
                ],
                "interactions": {
                    "global_filters": [{"dimension": "time_period", "type": "dropdown"}],
                    "page_navigation": [],
                    "drill_behavior": [],
                },
            }

        # --- 4. Apply design tokens to widgets and enforce KPI-to-widget mapping ---
        pages: list[dict] = blueprint_data.get("pages") or []
        for page in pages:
            updated_widgets = []
            for widget in page.get("widgets") or []:
                widget = _apply_style_tokens(widget, design_tokens)
                updated_widgets.append(widget)
            page["widgets"] = updated_widgets

        pages = _enforce_widget_types(pages)

        interactions: dict = blueprint_data.get("interactions") or {
            "global_filters": [],
            "page_navigation": [],
            "drill_behavior": [],
        }

        # --- 5. Determine performance class ---
        widget_count = _count_widgets(pages)
        performance_class = _determine_performance_class(widget_count)

        title: str = blueprint_data.get("title") or dashboard_need.get("dashboard_need", "Untitled")
        artifact_type: str = blueprint_data.get("artifact_type") or hint_type
        audience: str = dashboard_need.get("audience") or "general"
        archetype_name: str = dashboard_need.get("archetype") or (pages[0].get("layout_archetype") if pages else "")

        # --- 6. Persist ---
        conn = await _get_conn()
        try:
            async with conn.transaction():
                blueprint_id = await _insert_blueprint(
                    conn,
                    project_id=ctx.project_id,
                    tech_spec_id=tech_spec_id,
                    title=title,
                    audience=audience,
                    archetype=archetype_name,
                    style_profile=style_profile,
                    pages=pages,
                    interactions=interactions,
                    performance_class=performance_class,
                    artifact_type=artifact_type,
                )
        finally:
            await conn.close()

        logger.info(
            "Stored SAC blueprint %s — title=%r artifact_type=%s pages=%d widgets=%d perf=%s",
            blueprint_id,
            title,
            artifact_type,
            len(pages),
            widget_count,
            performance_class,
        )

        if first_blueprint_id is None:
            first_blueprint_id = str(blueprint_id)
            first_result = {
                "blueprint_id": str(blueprint_id),
                "title": title,
                "artifact_type": artifact_type,
                "page_count": len(pages),
                "widget_count": widget_count,
                "status": "draft",
            }

    if first_result is None:
        # sac_strategy was empty — should not happen given the fallback above, but guard anyway
        raise RuntimeError(f"No blueprints were generated for HLA {hla_id}")

    return first_result


async def get_blueprint(blueprint_id: str, project_id=None) -> Optional[dict]:
    """Fetch a single SAC blueprint by ID.

    Parses ``pages``, ``interactions``, and ``style_profile`` from JSONB
    back to Python dicts.  Optionally scopes to a project.
    """
    conn = await _get_conn()
    try:
        if project_id is not None:
            row = await conn.fetchrow(
                "SELECT * FROM sac_blueprints WHERE id = $1::uuid AND project_id = $2",
                blueprint_id,
                project_id,
            )
        else:
            row = await conn.fetchrow(
                "SELECT * FROM sac_blueprints WHERE id = $1::uuid",
                blueprint_id,
            )
        if row is None:
            return None

        result = _row_to_dict(row)
        for jsonb_col in ("pages", "interactions", "style_profile"):
            val = result.get(jsonb_col)
            if isinstance(val, str):
                try:
                    result[jsonb_col] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        return result
    finally:
        await conn.close()


async def list_blueprints(ctx: ContextEnvelope) -> list[dict]:
    """List all SAC blueprints for the active project.

    Returns a lightweight summary list (no ``pages``/``interactions`` payload)
    sorted newest-first.
    """
    if ctx.project_id is None:
        return []

    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT id, project_id, tech_spec_id, title, audience, archetype,
                   performance_class, status, approved_by, approved_at, created_at
            FROM sac_blueprints
            WHERE project_id = $1
            ORDER BY created_at DESC
            """,
            ctx.project_id,
        )
        return [_row_to_dict(r) for r in rows]
    finally:
        await conn.close()
