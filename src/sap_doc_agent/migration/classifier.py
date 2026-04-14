"""Migration Classifier: rule-based + LLM hybrid classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jinja2 import Template

from sap_doc_agent.llm.base import LLMProvider
from sap_doc_agent.llm.structured import generate_json_with_retry
from sap_doc_agent.migration.bw_patterns import BWPattern, detect_patterns
from sap_doc_agent.migration.models import (
    ClassifiedChain,
    IntentCard,
    MigrationClassification,
    StepClassification,
)
from sap_doc_agent.scanner.models import DataFlowChain

_PROMPT_DIR = Path(__file__).parent / "prompts"

_CLASSIFY_SYSTEM = (
    "You are an SAP BW migration classifier. Classify data flow chains for "
    "migration to SAP Datasphere. Respond with valid JSON only."
)

_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "classification": {"type": "string"},
        "rationale": {"type": "string"},
        "step_classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_number": {"type": "integer"},
                    "classification": {"type": "string"},
                    "rationale": {"type": "string"},
                    "dsp_equivalent": {"type": "string"},
                },
            },
        },
        "dsp_equivalent_pattern": {"type": "string"},
        "effort_category": {"type": "string"},
        "effort_rationale": {"type": "string"},
        "confidence": {"type": "number"},
        "needs_human_review": {"type": "boolean"},
    },
    "required": ["classification", "rationale", "confidence"],
}


@dataclass
class ActivityData:
    """Activity/usage data for a chain, used for DROP analysis."""

    last_execution: Optional[str] = None
    query_usage_count: Optional[int] = None


def classify_by_rules(
    intent_card: IntentCard,
    chain: DataFlowChain,
    activity: Optional[ActivityData] = None,
) -> Optional[ClassifiedChain]:
    """Attempt rule-based classification using BW pattern detection.

    Returns a ClassifiedChain if rules are confident enough, None otherwise
    (meaning LLM fallback is needed).
    """
    # Collect all pattern matches across steps
    all_matched: list[BWPattern] = []
    step_matches: dict[int, list[BWPattern]] = {}

    for step in chain.steps:
        metadata = step.model_dump() if hasattr(step, "model_dump") else {}
        patterns = detect_patterns(step.source_code, metadata)
        if patterns:
            step_matches[step.position] = patterns
            all_matched.extend(patterns)

    # Activity-based DROP detection
    if activity:
        meta = {}
        if activity.last_execution:
            meta["last_run"] = activity.last_execution
        if activity.query_usage_count == 0:
            meta["usage_count_zero"] = True
        activity_patterns = detect_patterns("", meta)
        all_matched.extend(activity_patterns)

    if not all_matched:
        return None  # No rule matches — need LLM

    # Count classifications across matched patterns
    classification_counts: dict[MigrationClassification, int] = {}
    for p in all_matched:
        classification_counts[p.classification] = classification_counts.get(p.classification, 0) + 1

    # Determine dominant classification
    # Priority order for tie-breaking: DROP > CLARIFY > REPLACE > SIMPLIFY > MIGRATE
    _PRIORITY = {
        MigrationClassification.DROP: 5,
        MigrationClassification.CLARIFY: 4,
        MigrationClassification.REPLACE: 3,
        MigrationClassification.SIMPLIFY: 2,
        MigrationClassification.MIGRATE: 1,
    }
    dominant = max(classification_counts, key=lambda c: (classification_counts[c], _PRIORITY.get(c, 0)))

    # DROP candidates always need human review
    needs_review = dominant == MigrationClassification.DROP
    if dominant == MigrationClassification.CLARIFY:
        needs_review = True

    # Build per-step classifications
    step_classifications = []
    for step in chain.steps:
        patterns = step_matches.get(step.position, [])
        if patterns:
            step_class = max(
                set(p.classification for p in patterns),
                key=lambda c: sum(1 for p in patterns if p.classification == c),
            )
            step_classifications.append(
                StepClassification(
                    step_number=step.position,
                    object_id=step.object_id,
                    classification=step_class,
                    rationale="; ".join(p.rationale for p in patterns[:2]),
                    detected_patterns=[p.name for p in patterns],
                    dsp_equivalent=patterns[0].dsp_equivalent if patterns else None,
                )
            )

    # Calculate effort based on step count and complexity
    effort = _estimate_effort(chain, all_matched)

    return ClassifiedChain(
        chain_id=intent_card.chain_id,
        intent_card=intent_card,
        classification=dominant,
        rationale=_build_rule_rationale(dominant, all_matched),
        step_classifications=step_classifications,
        dsp_equivalent_pattern=all_matched[0].dsp_equivalent if all_matched else None,
        last_execution=activity.last_execution if activity else None,
        query_usage_count=activity.query_usage_count if activity else None,
        effort_category=effort,
        effort_rationale=_effort_rationale(effort, chain),
        confidence=0.85,  # Rule-based gets high confidence
        needs_human_review=needs_review,
    )


async def classify_with_llm(
    intent_card: IntentCard,
    chain: DataFlowChain,
    llm: LLMProvider,
    activity: Optional[ActivityData] = None,
    confidence_threshold: float = 0.7,
) -> ClassifiedChain:
    """LLM-based classification for chains that rules couldn't handle."""
    # Still detect patterns to feed as context
    all_matched: list[BWPattern] = []
    for step in chain.steps:
        metadata = step.model_dump() if hasattr(step, "model_dump") else {}
        all_matched.extend(detect_patterns(step.source_code, metadata))

    template = Template((_PROMPT_DIR / "classify_chain.md").read_text())
    prompt = template.render(
        chain_id=intent_card.chain_id,
        business_purpose=intent_card.business_purpose,
        data_domain=intent_card.data_domain,
        grain=intent_card.grain,
        transformations=[
            {
                "step_number": t.step_number,
                "intent": t.intent,
                "implementation": t.implementation,
                "is_business_logic": t.is_business_logic,
                "simplification_note": t.simplification_note,
                "detected_patterns": t.detected_patterns,
            }
            for t in intent_card.transformations
        ],
        detected_patterns=[
            {
                "name": p.name,
                "classification": p.classification.value,
                "description": p.description,
                "dsp_equivalent": p.dsp_equivalent,
            }
            for p in all_matched
        ],
        activity_data=activity,
    )

    data = await generate_json_with_retry(llm, prompt, schema=_CLASSIFY_SCHEMA, system=_CLASSIFY_SYSTEM)

    if data is None:
        return ClassifiedChain(
            chain_id=intent_card.chain_id,
            intent_card=intent_card,
            classification=MigrationClassification.CLARIFY,
            rationale="LLM classification failed — manual review required",
            confidence=0.0,
            needs_human_review=True,
        )

    classification = _parse_classification(data.get("classification", "clarify"))
    confidence = float(data.get("confidence", 0.0))

    step_classifications = []
    for sc in data.get("step_classifications", []):
        step_classifications.append(
            StepClassification(
                step_number=sc.get("step_number", 0),
                object_id="",
                classification=_parse_classification(sc.get("classification", "clarify")),
                rationale=sc.get("rationale", ""),
                dsp_equivalent=sc.get("dsp_equivalent"),
            )
        )

    return ClassifiedChain(
        chain_id=intent_card.chain_id,
        intent_card=intent_card,
        classification=classification,
        rationale=data.get("rationale", ""),
        step_classifications=step_classifications,
        dsp_equivalent_pattern=data.get("dsp_equivalent_pattern"),
        last_execution=activity.last_execution if activity else None,
        query_usage_count=activity.query_usage_count if activity else None,
        effort_category=data.get("effort_category"),
        effort_rationale=data.get("effort_rationale"),
        confidence=confidence,
        needs_human_review=(
            data.get("needs_human_review", False)
            or confidence < confidence_threshold
            or classification == MigrationClassification.DROP
        ),
    )


async def classify_chain(
    intent_card: IntentCard,
    chain: DataFlowChain,
    llm: LLMProvider,
    activity: Optional[ActivityData] = None,
    confidence_threshold: float = 0.7,
) -> ClassifiedChain:
    """Classify a chain: try rules first, fall back to LLM.

    This is the main entry point for classification.
    """
    # Try rule-based first
    rule_result = classify_by_rules(intent_card, chain, activity)
    if rule_result is not None:
        return rule_result

    # Fall back to LLM
    return await classify_with_llm(intent_card, chain, llm, activity, confidence_threshold)


# --- Helpers ---


def _parse_classification(value: str) -> MigrationClassification:
    try:
        return MigrationClassification(value.lower())
    except ValueError:
        return MigrationClassification.CLARIFY


def _build_rule_rationale(classification: MigrationClassification, patterns: list[BWPattern]) -> str:
    pattern_names = sorted(set(p.name for p in patterns))
    return f"Rule-based classification: {classification.value}. Matched patterns: {', '.join(pattern_names[:5])}."


def _estimate_effort(chain: DataFlowChain, patterns: list[BWPattern]) -> str:
    """Estimate migration effort based on chain complexity."""
    step_count = chain.step_count
    has_complex = any(p.name == "complex_abap_routine" for p in patterns)
    total_source_lines = sum(len(s.source_code.splitlines()) for s in chain.steps if s.source_code)

    if has_complex or total_source_lines > 200:
        return "complex"
    if step_count > 5 or total_source_lines > 50:
        return "moderate"
    return "trivial"


def _effort_rationale(effort: str, chain: DataFlowChain) -> str:
    step_count = chain.step_count
    total_lines = sum(len(s.source_code.splitlines()) for s in chain.steps if s.source_code)
    return f"{step_count} steps, ~{total_lines} lines of ABAP"
