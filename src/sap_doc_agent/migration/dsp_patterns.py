"""DSP target architecture knowledge base.

Encodes SAP Datasphere naming conventions, SQL rules, persistence strategy,
and step collapse patterns. Derived from KNOWLEDGE.md and
DATASPHERE_BEST_PRACTICES.md (working session knowledge).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------- Layer model ----------


class DSPLayer(str, Enum):
    """The 4-layer DSP architecture."""

    STAGING = "staging"
    HARMONIZATION = "harmonization"
    MART = "mart"
    CONSUMPTION = "consumption"


# ---------- Naming conventions ----------

# (layer, usage_type) → prefix
# From KNOWLEDGE.md §Conventions & Naming
LAYER_PREFIXES: dict[tuple[str, str], str] = {
    # Layer 1 — Staging / Raw
    ("staging", "local_table"): "01_LT_",
    ("staging", "remote_table"): "01_RT_",
    ("staging", "replication_flow"): "01_RF_",
    # Layer 2 — Harmonization / Integration
    ("harmonization", "relational_dataset"): "02_RV_",
    ("harmonization", "fact"): "02_FV_",
    ("harmonization", "dimension"): "02_MD_",
    ("harmonization", "helper"): "02_HV_",
    # Layer 3 — Mart / Output
    ("mart", "fact"): "03_FV_",
    ("mart", "helper"): "03_HV_",
    ("mart", "dimension"): "03_MD_",
    # Layer 4 — Consumption (Analytic Models, no prefix convention)
}


def get_prefix_for_layer_and_usage(layer: str, usage: str) -> Optional[str]:
    """Return the DSP naming prefix for a layer+usage combination."""
    return LAYER_PREFIXES.get((layer, usage))


# ---------- Semantic usages ----------

SEMANTIC_USAGES: dict[str, str] = {
    "relational_dataset": "No semantic usage — intermediate staging/joins",
    "fact": "Measurable KPIs, transactions — basis for Analytic Models",
    "dimension": "Master data with key attribute (customers, materials)",
    "text": "Labels/descriptions for dimension keys",
    "hierarchy": "Parent-child data for drill-down",
}


# ---------- SQL rules ----------


@dataclass
class DSPSQLRule:
    """A DSP SQL syntax/semantic rule that must be enforced."""

    rule_id: str
    description: str
    severity: str  # "error" or "warning"
    rationale: str
    example_bad: str = ""
    example_good: str = ""


DSP_SQL_RULES: list[DSPSQLRule] = [
    DSPSQLRule(
        rule_id="no_cte",
        description="WITH / CTE clauses are not supported in DSP SQL",
        severity="error",
        rationale="DSP parser rejects CTEs. Use inline subqueries instead.",
        example_bad="WITH cte AS (SELECT ...) SELECT * FROM cte",
        example_good="SELECT * FROM (SELECT ...) cte",
    ),
    DSPSQLRule(
        rule_id="limit_in_union",
        description="LIMIT inside UNION ALL must be wrapped in parentheses",
        severity="error",
        rationale="DSP parser fails without parentheses around LIMIT legs.",
        example_bad="SELECT ... LIMIT 1 UNION ALL SELECT ... LIMIT 1",
        example_good="(SELECT ... LIMIT 1) UNION ALL (SELECT ... LIMIT 1)",
    ),
    DSPSQLRule(
        rule_id="union_aliases",
        description="Column aliases required on every UNION ALL leg",
        severity="error",
        rationale="DSP requires explicit aliases on each leg, not just the first.",
        example_bad="SELECT col UNION ALL SELECT col2",
        example_good='SELECT col AS "Name" UNION ALL SELECT col2 AS "Name"',
    ),
    DSPSQLRule(
        rule_id="no_select_star_cross_space",
        description="SELECT * fails on cross-space joins",
        severity="error",
        rationale="DSP blocks SELECT * when referencing views from another space.",
        example_bad='SELECT * FROM "OTHER_SPACE"."view"',
        example_good='SELECT a."COL1", a."COL2" FROM "OTHER_SPACE"."view" a',
    ),
    DSPSQLRule(
        rule_id="cross_space_prefix",
        description='Cross-space references must use full "SPACE"."view" prefix',
        severity="error",
        rationale="Views from other spaces need explicit space prefix to resolve.",
        example_bad="SELECT ... FROM other_view",
        example_good='SELECT ... FROM "SAP_ADMIN"."other_view"',
    ),
    DSPSQLRule(
        rule_id="no_arrow_in_comments",
        description="Avoid --> inside block comments",
        severity="warning",
        rationale="DSP parser may misread dash-arrow inside /* ... */ as syntax.",
        example_bad="/* This --> breaks the parser */",
        example_good="/* This => works fine */",
    ),
    DSPSQLRule(
        rule_id="datab_desc_in_row_number",
        description="ROW_NUMBER ORDER BY should include DATAB DESC for validity periods",
        severity="warning",
        rationale="Without DATAB DESC, stale conditions may win over current ones.",
        example_bad="ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ACCESS_PRIORITY ASC)",
        example_good="ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ACCESS_PRIORITY ASC, DATAB DESC)",
    ),
    DSPSQLRule(
        rule_id="varchar_date_comparison",
        description="Date comparisons must use VARCHAR YYYYMMDD format",
        severity="warning",
        rationale="SAP stores DATAB/DATBI as VARCHAR YYYYMMDD. Use string comparison.",
        example_bad="WHERE DATAB <= CURRENT_DATE",
        example_good="WHERE DATAB <= '20260101'",
    ),
]

SQL_RULES_BY_ID: dict[str, DSPSQLRule] = {r.rule_id: r for r in DSP_SQL_RULES}


# ---------- Persistence strategy ----------


@dataclass
class PersistenceThreshold:
    """A condition under which a view should be persisted."""

    name: str
    description: str
    check: str  # human-readable condition


PERSISTENCE_THRESHOLDS: list[PersistenceThreshold] = [
    PersistenceThreshold(
        name="cross_join",
        description="Views with CROSS JOIN should be persisted",
        check="has_cross_join",
    ),
    PersistenceThreshold(
        name="slow_preview",
        description="Views taking >30s in data preview",
        check="preview_seconds > 30",
    ),
    PersistenceThreshold(
        name="many_consumers",
        description="Views used as source by 3+ downstream views",
        check="consumer_count >= 3",
    ),
]


def suggest_persistence(
    has_cross_join: bool = False,
    preview_seconds: float = 0,
    consumer_count: int = 0,
) -> bool:
    """Suggest whether a view should be persisted based on thresholds."""
    if has_cross_join:
        return True
    if preview_seconds > 30:
        return True
    if consumer_count >= 3:
        return True
    return False


# ---------- Step collapse patterns ----------


@dataclass
class CollapsePattern:
    """A pattern where multiple BW steps can collapse into fewer DSP views."""

    name: str
    bw_pattern: str  # what BW typically has
    dsp_replacement: str  # what DSP should have
    rationale: str
    conditions: list[str] = field(default_factory=list)  # when this applies


STEP_COLLAPSE_PATTERNS: list[CollapsePattern] = [
    CollapsePattern(
        name="delta_staging_collapse",
        bw_pattern="DS → TRAN → staging DSO → TRAN → clean DSO",
        dsp_replacement="Replication flow + single SQL view (filter + transform)",
        rationale="Delta staging DSOs exist because BW needs them for CDC. DSP replication flows handle delta natively, so the staging DSO and its transformation can be eliminated.",
        conditions=["has_delta_staging", "steps >= 2"],
    ),
    CollapsePattern(
        name="multi_aggregation_collapse",
        bw_pattern="TRAN₁ (partial agg) → DSO → TRAN₂ (final agg)",
        dsp_replacement="Single GROUP BY in one SQL view",
        rationale="BW often splits aggregation across DSO boundaries. DSP can do it in one SQL view with GROUP BY.",
        conditions=["consecutive_simplify_steps >= 2"],
    ),
    CollapsePattern(
        name="filter_transform_collapse",
        bw_pattern="TRAN₁ (filter) → DSO → TRAN₂ (field mapping/conversion)",
        dsp_replacement="Single SQL view with WHERE + CASE WHEN/JOIN",
        rationale="Start routine filter + field routine mapping are separate BW concepts but combine naturally into one SQL view.",
        conditions=["consecutive_simplify_steps >= 2"],
    ),
    CollapsePattern(
        name="year_partition_collapse",
        bw_pattern="MultiProvider UNION ALL across year-partitioned ADSOs",
        dsp_replacement="Single view with date filter on one source",
        rationale="Year partitioning was a BW performance workaround. DSP HANA columnar store handles date filtering natively.",
        conditions=["has_year_partition"],
    ),
]


def suggest_collapse(
    step_classifications: list[str],
    has_delta_staging: bool = False,
    has_year_partition: bool = False,
    total_steps: int = 0,
) -> list[CollapsePattern]:
    """Suggest which collapse patterns apply to a given chain."""
    suggestions: list[CollapsePattern] = []

    # Count consecutive simplify steps
    consecutive_simplify = 0
    max_consecutive_simplify = 0
    for c in step_classifications:
        if c.lower() == "simplify":
            consecutive_simplify += 1
            max_consecutive_simplify = max(max_consecutive_simplify, consecutive_simplify)
        else:
            consecutive_simplify = 0

    if has_delta_staging and total_steps >= 2:
        suggestions.append(STEP_COLLAPSE_PATTERNS[0])  # delta_staging_collapse

    if max_consecutive_simplify >= 2:
        suggestions.append(STEP_COLLAPSE_PATTERNS[1])  # multi_aggregation_collapse

    if has_year_partition:
        suggestions.append(STEP_COLLAPSE_PATTERNS[3])  # year_partition_collapse

    return suggestions


# ---------- Layer & usage suggestion ----------


def suggest_layer(step_purpose: str) -> DSPLayer:
    """Suggest the DSP layer for a given step purpose."""
    purpose = step_purpose.lower()
    if any(k in purpose for k in ("replication", "ingest", "raw", "staging", "source")):
        return DSPLayer.STAGING
    if any(k in purpose for k in ("aggregat", "mart", "output", "final")):
        return DSPLayer.MART
    if any(k in purpose for k in ("consum", "analytic", "sac", "report", "query")):
        return DSPLayer.CONSUMPTION
    # Default to harmonization (most transformations land here)
    return DSPLayer.HARMONIZATION


def suggest_semantic_usage(description: str) -> str:
    """Suggest DSP semantic usage based on a view description."""
    desc = description.lower()
    if any(k in desc for k in ("master", "dimension", "customer", "material", "attribute")):
        return "dimension"
    if any(k in desc for k in ("transaction", "billing", "revenue", "amount", "kpi", "measure")):
        return "fact"
    if any(k in desc for k in ("label", "text", "description", "name")):
        return "text"
    if any(k in desc for k in ("hierarchy", "parent", "child", "level")):
        return "hierarchy"
    return "relational_dataset"
