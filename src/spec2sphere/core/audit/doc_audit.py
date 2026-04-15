"""Documentation Audit Engine.

Compares existing landscape object documentation against loaded standards
(naming conventions, description requirements, cross-reference completeness).

Returns per-object scorecards and an aggregated AuditReport.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import asyncpg

from spec2sphere.tenant.context import ContextEnvelope, ScopedQuery

logger = logging.getLogger(__name__)

# Generic placeholder strings that indicate a field was not meaningfully filled.
_GENERIC_TERMS = frozenset(["test", "todo", "tbd", "asdf", "placeholder", "n/a", "na", "fixme", "xxx"])

# Minimum description length to be considered non-trivial.
_MIN_DESCRIPTION_LEN = 20

# Keywords that signal a quality description (business purpose, context, etc.).
_QUALITY_KEYWORDS = frozenset(
    [
        "purpose",
        "source",
        "business",
        "context",
        "used",
        "contains",
        "provides",
        "maps",
        "calculates",
        "represents",
        "loads",
        "extracts",
        "transforms",
        "stores",
        "domain",
        "layer",
    ]
)


@dataclass
class ObjectScorecard:
    object_id: str
    object_name: str
    platform: str
    total_score: float  # 0-100
    documented_fields: float  # % of expected fields that have content
    naming_compliance: float  # how well names match naming convention rules
    description_quality: float  # description length, completeness, keyword coverage
    cross_references: float  # links to related objects documented
    recommendations: list[str] = field(default_factory=list)


@dataclass
class AuditReport:
    customer_id: str
    project_id: Optional[str]
    total_objects: int
    audited_objects: int
    average_score: float
    scorecards: list[ObjectScorecard] = field(default_factory=list)
    summary: dict = field(default_factory=dict)  # {excellent, good, needs_work, poor}
    recommendations: list[str] = field(default_factory=list)


async def _get_conn() -> asyncpg.Connection:
    db_url = os.environ.get("DATABASE_URL", "")
    url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
    return await asyncpg.connect(url)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def audit_documentation(ctx: ContextEnvelope) -> AuditReport:
    """Run full documentation audit for the current scope.

    Steps:
    1. Load all landscape_objects for the customer/project.
    2. Load naming rules from knowledge_items (category='naming').
    3. Score each object across four dimensions.
    4. Aggregate into an AuditReport with summary buckets.
    """
    conn = await _get_conn()
    try:
        objects = await _load_objects(conn, ctx)
        naming_rules = await get_naming_rules(ctx)

        scorecards: list[ObjectScorecard] = []
        for obj in objects:
            sc = await _score_object(obj, naming_rules, objects)
            scorecards.append(sc)

        total = len(objects)
        average = sum(sc.total_score for sc in scorecards) / total if total else 0.0

        summary = _bucket_summary(scorecards)
        top_recs = _top_recommendations(scorecards)

        return AuditReport(
            customer_id=str(ctx.customer_id),
            project_id=str(ctx.project_id) if ctx.project_id else None,
            total_objects=total,
            audited_objects=len(scorecards),
            average_score=round(average, 1),
            scorecards=scorecards,
            summary=summary,
            recommendations=top_recs,
        )
    finally:
        await conn.close()


async def audit_single_object(object_id: str, ctx: ContextEnvelope) -> ObjectScorecard:
    """Audit a single landscape object by its UUID."""
    conn = await _get_conn()
    try:
        sq = ScopedQuery(ctx)
        conditions, params = sq.tenant_customer_project()
        # landscape_objects has no tenant_id column — scope by customer/project only.
        cust_conditions = [c for c in conditions if "tenant_id" not in c]
        cust_params = params[: len(cust_conditions)]

        param_n = len(cust_params) + 1
        cust_conditions.append(f"id = ${param_n}")
        cust_params.append(UUID(object_id))

        where = " AND ".join(cust_conditions)
        row = await conn.fetchrow(f"SELECT * FROM landscape_objects WHERE {where}", *cust_params)
        if row is None:
            raise ValueError(f"Object {object_id} not found in current scope")

        obj = dict(row)
        naming_rules = await get_naming_rules(ctx)
        # Load peer objects for cross-reference validation (lightweight: IDs only).
        all_ids = await _load_object_ids(conn, ctx)
        return await _score_object(obj, naming_rules, all_ids)
    finally:
        await conn.close()


async def get_naming_rules(ctx: ContextEnvelope) -> list[dict]:
    """Load naming convention rules from knowledge_items where category='naming'."""
    conn = await _get_conn()
    try:
        sq = ScopedQuery(ctx)
        conditions, params = sq.tenant_customer_project()
        param_n = len(params) + 1
        conditions.append(f"category = ${param_n}")
        params.append("naming")
        where = " AND ".join(conditions)
        rows = await conn.fetch(
            f"SELECT id, title, content FROM knowledge_items WHERE {where}",
            *params,
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


async def _score_documented_fields(obj: dict) -> tuple[float, list[str]]:
    """Score how many expected fields are documented. Return (score, recommendations).

    Expected fields: documentation, metadata.description, layer, dependencies.
    Score = percentage of non-empty fields (0-100).
    """
    recs: list[str] = []

    checks: list[tuple[str, bool]] = []

    # documentation column
    doc_filled = bool(obj.get("documentation") and str(obj["documentation"]).strip())
    checks.append(("documentation", doc_filled))
    if not doc_filled:
        recs.append("Add a documentation text to describe what this object does.")

    # description inside metadata JSONB
    metadata = obj.get("metadata") or {}
    if isinstance(metadata, str):
        import json as _json

        try:
            metadata = _json.loads(metadata)
        except Exception:
            metadata = {}
    desc_filled = bool(metadata.get("description") and str(metadata["description"]).strip())
    checks.append(("metadata.description", desc_filled))
    if not desc_filled:
        recs.append("Add a description in the object metadata.")

    # layer
    layer_filled = bool(obj.get("layer") and str(obj["layer"]).strip())
    checks.append(("layer", layer_filled))
    if not layer_filled:
        recs.append("Assign an architecture layer (e.g. Acquisition, Transformation, Presentation).")

    # dependencies
    deps = obj.get("dependencies")
    if deps is None:
        deps = []
    if isinstance(deps, str):
        import json as _json

        try:
            deps = _json.loads(deps)
        except Exception:
            deps = []
    deps_filled = isinstance(deps, list) and len(deps) > 0
    checks.append(("dependencies", deps_filled))
    if not deps_filled:
        recs.append("Document object dependencies (source tables, upstream objects, etc.).")

    filled = sum(1 for _, ok in checks if ok)
    score = round((filled / len(checks)) * 100, 1)
    return score, recs


async def _score_naming_compliance(obj: dict, naming_rules: list[dict]) -> tuple[float, list[str]]:
    """Score naming compliance against naming_rules. Return (score, recommendations).

    Each rule's content is treated as a regex pattern or a descriptive rule.
    Lines starting with 'pattern:' are extracted and matched.
    Rules starting with 'require_prefix:' check for mandatory prefixes.
    Other content is advisory — if present, a partial deduction is applied.
    """
    recs: list[str] = []
    name = obj.get("object_name") or ""
    technical_name = obj.get("technical_name") or ""

    if not naming_rules:
        # No rules loaded — can't evaluate. Return neutral score with advice.
        return 75.0, ["No naming rules found in knowledge base. Load naming conventions to enable compliance scoring."]

    violations = 0
    total_checks = 0

    for rule in naming_rules:
        content: str = rule.get("content", "")
        title: str = rule.get("title", "")

        for line in content.splitlines():
            line = line.strip()

            if line.lower().startswith("pattern:"):
                pattern_str = line[len("pattern:") :].strip()
                total_checks += 1
                check_name = technical_name or name
                if check_name and not re.match(pattern_str, check_name, re.IGNORECASE):
                    violations += 1
                    recs.append(f"'{check_name}' does not match the naming pattern '{pattern_str}' (rule: {title}).")

            elif line.lower().startswith("require_prefix:"):
                prefix = line[len("require_prefix:") :].strip()
                total_checks += 1
                check_name = technical_name or name
                if check_name and not check_name.upper().startswith(prefix.upper()):
                    violations += 1
                    recs.append(f"'{check_name}' is missing required prefix '{prefix}' (rule: {title}).")

    if total_checks == 0:
        # Rules exist but none are pattern/prefix rules — give advisory score.
        return 80.0, [
            f"Naming rule '{r['title']}' loaded but contains no checkable patterns." for r in naming_rules[:2]
        ]

    score = max(0.0, round(((total_checks - violations) / total_checks) * 100, 1))
    return score, recs


async def _score_description_quality(obj: dict) -> tuple[float, list[str]]:
    """Score description quality. Return (score, recommendations).

    Checks:
    - Non-empty
    - Length >= _MIN_DESCRIPTION_LEN
    - Not a generic placeholder term
    - Bonus points for quality keyword presence
    """
    recs: list[str] = []

    # Prefer documentation column; fall back to metadata.description.
    text = obj.get("documentation") or ""
    if not text:
        metadata = obj.get("metadata") or {}
        if isinstance(metadata, str):
            import json as _json

            try:
                metadata = _json.loads(metadata)
            except Exception:
                metadata = {}
        text = metadata.get("description") or ""

    text = str(text).strip()

    if not text:
        return 0.0, ["Add a description — the object has no documentation text at all."]

    score = 40.0  # base for having any content

    # Length check
    if len(text) >= _MIN_DESCRIPTION_LEN:
        score += 20.0
    else:
        recs.append(
            f"Description is too short ({len(text)} chars). Aim for at least {_MIN_DESCRIPTION_LEN} characters."
        )

    # Generic term check
    lower = text.lower()
    if any(g == lower or lower.startswith(g + " ") for g in _GENERIC_TERMS):
        score -= 30.0
        recs.append("Description appears to be a placeholder. Replace with a meaningful explanation.")

    # Quality keyword bonus (up to 40 pts)
    hits = sum(1 for kw in _QUALITY_KEYWORDS if kw in lower)
    keyword_bonus = min(40.0, hits * 8.0)
    score += keyword_bonus

    if hits == 0:
        recs.append(
            "Description lacks business context keywords. "
            "Mention purpose, source system, business domain, or transformation logic."
        )

    score = max(0.0, min(100.0, round(score, 1)))
    return score, recs


async def _score_cross_references(obj: dict, all_objects: list[dict]) -> tuple[float, list[str]]:
    """Score cross-reference documentation. Return (score, recommendations).

    Checks:
    - dependencies array is populated
    - referenced IDs exist in the known object set (if IDs are UUIDs)
    """
    recs: list[str] = []

    deps = obj.get("dependencies")
    if isinstance(deps, str):
        import json as _json

        try:
            deps = _json.loads(deps)
        except Exception:
            deps = []
    if deps is None:
        deps = []

    if not deps:
        return 30.0, [
            "No dependencies documented. Link upstream sources, transformations, "
            "or related objects to improve traceability."
        ]

    score = 60.0  # base for having any dependencies listed

    # Resolve which fields to use from all_objects for ID lookup.
    # all_objects may be full dicts or lightweight ID-only dicts.
    known_ids: set[str] = set()
    for o in all_objects:
        if isinstance(o, dict):
            oid = o.get("id")
            if oid:
                known_ids.add(str(oid))

    if known_ids:
        valid_refs = 0
        uuid_pattern = re.compile(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            re.IGNORECASE,
        )
        uuid_deps = [str(d) for d in deps if uuid_pattern.match(str(d))]
        if uuid_deps:
            valid_refs = sum(1 for d in uuid_deps if d in known_ids)
            stale = len(uuid_deps) - valid_refs
            if stale > 0:
                recs.append(
                    f"{stale} dependency reference(s) point to objects not found "
                    "in the current landscape — they may be stale or from another project."
                )
            score += min(40.0, (valid_refs / len(uuid_deps)) * 40.0)
        else:
            # Dependencies exist but aren't UUIDs — treat as named references (good).
            score += 30.0

    score = max(0.0, min(100.0, round(score, 1)))
    return score, recs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _load_objects(conn: asyncpg.Connection, ctx: ContextEnvelope) -> list[dict]:
    """Load all landscape_objects for the current customer/project scope."""
    sq = ScopedQuery(ctx)
    # landscape_objects has customer_id and project_id but no tenant_id.
    conditions: list[str] = ["customer_id = $1"]
    params: list = [ctx.customer_id]
    if ctx.project_id is not None:
        conditions.append("project_id = $2")
        params.append(ctx.project_id)
    where = " AND ".join(conditions)
    rows = await conn.fetch(
        f"SELECT * FROM landscape_objects WHERE {where} ORDER BY object_name",
        *params,
    )
    return [dict(r) for r in rows]


async def _load_object_ids(conn: asyncpg.Connection, ctx: ContextEnvelope) -> list[dict]:
    """Load lightweight id-only records for cross-reference validation."""
    conditions: list[str] = ["customer_id = $1"]
    params: list = [ctx.customer_id]
    if ctx.project_id is not None:
        conditions.append("project_id = $2")
        params.append(ctx.project_id)
    where = " AND ".join(conditions)
    rows = await conn.fetch(f"SELECT id FROM landscape_objects WHERE {where}", *params)
    return [dict(r) for r in rows]


async def _score_object(obj: dict, naming_rules: list[dict], peer_objects: list[dict]) -> ObjectScorecard:
    """Compute all four dimension scores and aggregate into an ObjectScorecard."""
    fields_score, fields_recs = await _score_documented_fields(obj)
    naming_score, naming_recs = await _score_naming_compliance(obj, naming_rules)
    desc_score, desc_recs = await _score_description_quality(obj)
    xref_score, xref_recs = await _score_cross_references(obj, peer_objects)

    # Weighted average: fields 25%, naming 25%, description 30%, xrefs 20%.
    total = round(
        fields_score * 0.25 + naming_score * 0.25 + desc_score * 0.30 + xref_score * 0.20,
        1,
    )

    all_recs = fields_recs + naming_recs + desc_recs + xref_recs

    return ObjectScorecard(
        object_id=str(obj.get("id", "")),
        object_name=obj.get("object_name", ""),
        platform=obj.get("platform", ""),
        total_score=total,
        documented_fields=fields_score,
        naming_compliance=naming_score,
        description_quality=desc_score,
        cross_references=xref_score,
        recommendations=all_recs,
    )


def _bucket_summary(scorecards: list[ObjectScorecard]) -> dict:
    """Bucket scores: excellent ≥85, good ≥65, needs_work ≥40, poor <40."""
    summary = {"excellent": 0, "good": 0, "needs_work": 0, "poor": 0}
    for sc in scorecards:
        if sc.total_score >= 85:
            summary["excellent"] += 1
        elif sc.total_score >= 65:
            summary["good"] += 1
        elif sc.total_score >= 40:
            summary["needs_work"] += 1
        else:
            summary["poor"] += 1
    return summary


def _top_recommendations(scorecards: list[ObjectScorecard], top_n: int = 5) -> list[str]:
    """Collect the most common recommendations across all scorecards."""
    from collections import Counter

    counter: Counter = Counter()
    for sc in scorecards:
        for rec in sc.recommendations:
            # Normalise to the first sentence for deduplication.
            key = rec.split(".")[0].strip()
            counter[key] += 1

    return [rec for rec, _ in counter.most_common(top_n)]
