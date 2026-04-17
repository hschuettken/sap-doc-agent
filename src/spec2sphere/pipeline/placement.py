"""Cross-platform placement engine.

Decides DSP vs SAC placement for each artifact in an HLA document.
Uses deterministic rules first; calls LLM only for genuinely ambiguous cases.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from spec2sphere.llm.base import LLMProvider

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


class Platform(str, Enum):
    DSP = "dsp"
    SAC = "sac"
    BOTH = "both"


@dataclass
class PlacementDecision:
    artifact_name: str
    artifact_type: str  # calculation, filter, hierarchy, aggregation, visualization, data_model
    platform: Platform
    rationale: str
    confidence: float  # 0.0 – 1.0

    def to_dict(self) -> dict:
        return {
            "artifact_name": self.artifact_name,
            "artifact_type": self.artifact_type,
            "platform": self.platform.value,
            "rationale": self.rationale,
            "confidence": self.confidence,
        }


# ---------------------------------------------------------------------------
# Deterministic placement rules
# ---------------------------------------------------------------------------

# High-confidence rule entries:  (artifact_type, property_check) → (Platform, rationale, confidence)
# property_check is a callable(artifact_details: dict) -> bool; None means always applies.


def _is_reusable(d: dict) -> bool:
    return bool(
        d.get("reuse") or d.get("reusable") or d.get("shared") or (d.get("sources") and len(d.get("sources", [])) > 1)
    )


def _is_complex(d: dict) -> bool:
    formula = str(d.get("formula", "") or d.get("sql_logic", "") or d.get("description", ""))
    complex_keywords = ("case when", "over (", "partition by", "nested", "recursive", "join")
    return any(kw in formula.lower() for kw in complex_keywords) or len(formula) > 200


def _is_data_level(d: dict) -> bool:
    desc = str(d.get("description", "") + d.get("type", "")).lower()
    return any(k in desc for k in ("row level", "row-level", "rls", "authorization", "security", "data level"))


def _is_interactive(d: dict) -> bool:
    desc = str(d.get("description", "")).lower()
    return any(k in desc for k in ("interactive", "user-facing", "story", "ad-hoc", "ad hoc"))


def _is_high_volume(d: dict) -> bool:
    vol = d.get("estimated_rows") or d.get("volume_rows") or 0
    return int(vol) > 1_000_000


def _is_master_data(d: dict) -> bool:
    desc = str(d.get("description", "") + d.get("type", "")).lower()
    return any(k in desc for k in ("master data", "master-data", "stable", "slowly changing", "scd"))


def _is_flexible(d: dict) -> bool:
    desc = str(d.get("description", "")).lower()
    return any(k in desc for k in ("flexible", "reporting", "dynamic", "variable"))


# Rule table: list of (artifact_type, condition_fn_or_none, platform, rationale_template, confidence)
_RULES: list[tuple] = [
    # Visualizations always go to SAC
    ("visualization", None, Platform.SAC, "Visualizations are always rendered in SAC Stories/Analytical Apps", 1.0),
    # Data model / table always DSP
    ("data_model", None, Platform.DSP, "Data models and physical tables always reside in DSP spaces", 1.0),
    ("table", None, Platform.DSP, "Physical tables always reside in DSP spaces", 1.0),
    ("replication_flow", None, Platform.DSP, "Replication flows run in DSP Data Integration", 1.0),
    ("analytic_model", None, Platform.DSP, "Analytic models are DSP consumption-layer artifacts", 0.95),
    # Calculations
    (
        "calculation",
        _is_complex,
        Platform.DSP,
        "Complex/reusable calculation belongs in a DSP view calculation for performance and reuse",
        0.9,
    ),
    (
        "calculation",
        _is_reusable,
        Platform.DSP,
        "Reusable calculation belongs in DSP to avoid duplication across SAC stories",
        0.9,
    ),
    (
        "calculation",
        _is_interactive,
        Platform.SAC,
        "Ad-hoc/interactive calculation is best expressed as a SAC calculated measure",
        0.85,
    ),
    # Filters
    (
        "filter",
        _is_data_level,
        Platform.DSP,
        "Data-level / security filter belongs in DSP as an input parameter or row-level security",
        0.95,
    ),
    ("filter", _is_interactive, Platform.SAC, "User-facing interactive filter belongs in SAC story filters", 0.9),
    # Hierarchies
    (
        "hierarchy",
        _is_master_data,
        Platform.DSP,
        "Stable master-data hierarchy belongs in DSP dimension hierarchy for consistency",
        0.9,
    ),
    ("hierarchy", _is_flexible, Platform.SAC, "Flexible reporting hierarchy is better managed in SAC", 0.85),
    # Aggregations
    (
        "aggregation",
        _is_high_volume,
        Platform.DSP,
        "High-volume aggregation should be pre-computed in a DSP persistence view",
        0.9,
    ),
    (
        "aggregation",
        _is_reusable,
        Platform.DSP,
        "Reused aggregation belongs in DSP to avoid redundant runtime computation",
        0.85,
    ),
    ("aggregation", _is_flexible, Platform.SAC, "Small/flexible aggregation is acceptable at SAC runtime", 0.8),
]


def _apply_rules(
    artifact_type: str,
    artifact_details: dict,
) -> Optional[PlacementDecision]:
    """Try each deterministic rule in order. Return first match, or None."""
    atype = artifact_type.lower().replace(" ", "_").replace("-", "_")

    for rule_type, condition_fn, platform, rationale, confidence in _RULES:
        if rule_type != atype:
            continue
        if condition_fn is None or condition_fn(artifact_details):
            return PlacementDecision(
                artifact_name=artifact_details.get("name", artifact_type),
                artifact_type=artifact_type,
                platform=platform,
                rationale=rationale,
                confidence=confidence,
            )
    return None


# ---------------------------------------------------------------------------
# LLM fallback for ambiguous cases
# ---------------------------------------------------------------------------


async def _llm_placement(
    artifact_name: str,
    artifact_type: str,
    artifact_details: dict,
    llm: LLMProvider,
) -> PlacementDecision:
    """Ask the LLM to decide placement for an ambiguous artifact."""
    from spec2sphere.llm.structured import generate_json_with_retry

    schema = {
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": ["dsp", "sac", "both"]},
            "rationale": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["platform", "rationale", "confidence"],
    }

    prompt = (
        f"Decide the platform placement for this SAP artifact:\n\n"
        f"Name: {artifact_name}\n"
        f"Type: {artifact_type}\n"
        f"Details: {artifact_details}\n\n"
        "Choose between:\n"
        "- dsp: belongs in SAP Datasphere (data layer, views, analytic models, complex logic, security)\n"
        "- sac: belongs in SAP Analytics Cloud (visualizations, user-facing filters, simple ad-hoc measures)\n"
        "- both: needed in both platforms\n\n"
        "Return platform, rationale, and confidence (0.0-1.0)."
    )

    result = await generate_json_with_retry(
        provider=llm,
        prompt=prompt,
        schema=schema,
        system=(
            "You are a senior SAP Data Sphere and SAC architect. "
            "Decide where each artifact belongs based on SAP best practices."
        ),
        max_retries=2,
        tier="placement",
        data_in_context=True,
    )

    if result is None:
        # Conservative fallback: DSP is the safer default for data artifacts
        return PlacementDecision(
            artifact_name=artifact_name,
            artifact_type=artifact_type,
            platform=Platform.DSP,
            rationale="LLM unavailable — defaulting to DSP as the safer data-layer placement",
            confidence=0.4,
        )

    try:
        platform = Platform(result["platform"])
    except (KeyError, ValueError):
        platform = Platform.DSP

    return PlacementDecision(
        artifact_name=artifact_name,
        artifact_type=artifact_type,
        platform=platform,
        rationale=result.get("rationale", ""),
        confidence=float(result.get("confidence", 0.6)),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def decide_placement(
    artifact_name: str,
    artifact_type: str,
    artifact_details: dict,
    llm: Optional[LLMProvider] = None,
) -> PlacementDecision:
    """Decide platform placement for a single artifact.

    Applies deterministic rules first. Calls LLM only if no rule matches
    and an LLM provider is supplied.

    Rules summary:
    - Calculations: complex/reusable -> DSP; simple/ad-hoc -> SAC
    - Filters: data-level/security -> DSP; user-facing/interactive -> SAC
    - Hierarchies: master-data/stable -> DSP; reporting/flexible -> SAC
    - Aggregation: high-volume/reused -> DSP; small/flexible -> SAC
    - Visualization: always SAC
    - Data model/table/replication_flow/analytic_model: always DSP
    """
    details_with_name = {**artifact_details, "name": artifact_name}
    decision = _apply_rules(artifact_type, details_with_name)

    if decision is not None:
        logger.debug(
            "Placement [deterministic] %s (%s) -> %s (confidence=%.2f)",
            artifact_name,
            artifact_type,
            decision.platform.value,
            decision.confidence,
        )
        return decision

    # No deterministic rule matched — call LLM if available
    if llm is not None and llm.is_available():
        logger.debug("Placement [llm] %s (%s) — no deterministic rule matched", artifact_name, artifact_type)
        decision = await _llm_placement(artifact_name, artifact_type, details_with_name, llm)
        return decision

    # Absolute fallback: default to DSP with low confidence
    logger.debug("Placement [fallback/dsp] %s (%s) — no rule, no LLM", artifact_name, artifact_type)
    return PlacementDecision(
        artifact_name=artifact_name,
        artifact_type=artifact_type,
        platform=Platform.DSP,
        rationale="No deterministic rule matched and LLM unavailable — defaulting to DSP",
        confidence=0.3,
    )


async def place_architecture(
    hla_content: dict,
    llm: Optional[LLMProvider] = None,
) -> list[PlacementDecision]:
    """Run placement for all artifacts in an HLA document.

    Processes views, replication flows, analytic models, and key_decisions.
    Returns a flat list of PlacementDecision objects.
    """
    decisions: list[PlacementDecision] = []

    # Views
    for view in hla_content.get("views", []):
        view_type = view.get("type", "relational_dataset")
        # Normalise SAC-specific view types
        if view_type in ("analytic_model",):
            artifact_type = "analytic_model"
        elif view.get("layer") == "CONSUMPTION":
            artifact_type = "analytic_model"
        else:
            artifact_type = "data_model"

        decision = await decide_placement(
            artifact_name=view.get("name", "unnamed_view"),
            artifact_type=artifact_type,
            artifact_details=view,
            llm=llm,
        )
        decisions.append(decision)

    # Replication flows
    for flow in hla_content.get("replication_strategy", []):
        decision = await decide_placement(
            artifact_name=flow.get("source_table", "replication_flow"),
            artifact_type="replication_flow",
            artifact_details=flow,
            llm=llm,
        )
        decisions.append(decision)

    # Key decisions — place based on the explicit platform_placement field
    for kd in hla_content.get("key_decisions", []):
        pp = kd.get("platform_placement", "dsp")
        try:
            platform = Platform(pp)
        except ValueError:
            platform = Platform.DSP
        decisions.append(
            PlacementDecision(
                artifact_name=kd.get("topic", "decision"),
                artifact_type="key_decision",
                platform=platform,
                rationale=kd.get("rationale", "Specified in key decisions"),
                confidence=0.95,
            )
        )

    logger.info(
        "place_architecture: %d decisions (%d DSP, %d SAC, %d BOTH)",
        len(decisions),
        sum(1 for d in decisions if d.platform == Platform.DSP),
        sum(1 for d in decisions if d.platform == Platform.SAC),
        sum(1 for d in decisions if d.platform == Platform.BOTH),
    )
    return decisions
