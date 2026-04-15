"""Semantic Interpreter: chain JSON → IntentCard via LLM."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Template

from spec2sphere.llm.base import LLMProvider
from spec2sphere.llm.structured import generate_json_with_retry
from spec2sphere.migration.bw_patterns import detect_pattern_names
from spec2sphere.migration.models import IntentCard, TransformationIntent
from spec2sphere.scanner.models import DataFlowChain

_PROMPT_DIR = Path(__file__).parent / "prompts"

_INTERPRET_SYSTEM = (
    "You are an SAP BW migration expert. You analyze BW data flow chains and "
    "produce structured business intent interpretations. Respond with valid JSON only."
)

_INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "business_purpose": {"type": "string"},
        "data_domain": {"type": "string"},
        "source_systems": {"type": "array", "items": {"type": "string"}},
        "key_entities": {"type": "array", "items": {"type": "string"}},
        "key_measures": {"type": "array", "items": {"type": "string"}},
        "grain": {"type": "string"},
        "consumers": {"type": "array", "items": {"type": "string"}},
        "transformations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step_number": {"type": "integer"},
                    "intent": {"type": "string"},
                    "implementation": {"type": "string"},
                    "is_business_logic": {"type": "boolean"},
                    "simplification_note": {"type": "string"},
                },
            },
        },
        "confidence": {"type": "number"},
        "review_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["business_purpose", "data_domain", "confidence"],
}


def _load_template() -> Template:
    template_path = _PROMPT_DIR / "interpret_chain.md"
    return Template(template_path.read_text())


def _build_prompt(chain: DataFlowChain, detected_patterns: list[str]) -> str:
    """Render the interpretation prompt for a chain."""
    template = _load_template()
    steps_data = []
    for step in chain.steps:
        steps_data.append(
            {
                "position": step.position,
                "name": step.name,
                "object_id": step.object_id,
                "object_type": step.object_type.value if hasattr(step.object_type, "value") else str(step.object_type),
                "step_summary": step.step_summary,
                "source_code": _truncate_source(step.source_code),
                "inter_step_object_name": step.inter_step_object_name,
                "inter_step_fields": step.inter_step_fields,
            }
        )
    return template.render(
        chain_id=chain.chain_id,
        terminal_object_id=chain.terminal_object_id,
        terminal_object_type=(
            chain.terminal_object_type.value
            if hasattr(chain.terminal_object_type, "value")
            else str(chain.terminal_object_type)
        ),
        source_object_ids=chain.source_object_ids,
        step_count=chain.step_count,
        steps=steps_data,
        chain_summary=chain.summary,
        detected_patterns=detected_patterns,
    )


async def interpret_chain(
    chain: DataFlowChain,
    llm: LLMProvider,
    confidence_threshold: float = 0.7,
) -> IntentCard:
    """Interpret a data flow chain into a structured IntentCard.

    Args:
        chain: The chain to interpret (with step summaries from chain_analyzer).
        llm: LLM provider for semantic analysis.
        confidence_threshold: Below this, needs_human_review is set True.

    Returns:
        IntentCard with business interpretation.
    """
    # Detect BW patterns in all transformation source code
    all_patterns: list[str] = []
    for step in chain.steps:
        if step.source_code:
            all_patterns.extend(detect_pattern_names(step.source_code))
    all_patterns = sorted(set(all_patterns))

    prompt = _build_prompt(chain, all_patterns)

    data = await generate_json_with_retry(llm, prompt, schema=_INTENT_SCHEMA, system=_INTERPRET_SYSTEM)

    if data is None:
        # Fallback: try plain generate and build minimal card
        raw = await llm.generate(prompt, system=_INTERPRET_SYSTEM)
        return IntentCard(
            chain_id=chain.chain_id,
            business_purpose=raw.strip() if raw else "",
            confidence=0.0,
            needs_human_review=True,
            review_notes=["LLM returned unstructured response — manual review required"],
        )

    # Build TransformationIntent objects from LLM response
    transformations = []
    for t in data.get("transformations", []):
        transformations.append(
            TransformationIntent(
                step_number=t.get("step_number", 0),
                intent=t.get("intent", ""),
                implementation=t.get("implementation", ""),
                is_business_logic=t.get("is_business_logic", True),
                simplification_note=t.get("simplification_note"),
                detected_patterns=[p for p in all_patterns if _pattern_relevant_to_step(p, t)],
            )
        )

    confidence = float(data.get("confidence", 0.0))
    return IntentCard(
        chain_id=chain.chain_id,
        business_purpose=data.get("business_purpose", ""),
        data_domain=data.get("data_domain", ""),
        source_systems=data.get("source_systems", []),
        key_entities=data.get("key_entities", []),
        key_measures=data.get("key_measures", []),
        grain=data.get("grain", ""),
        consumers=data.get("consumers", []),
        transformations=transformations,
        confidence=confidence,
        needs_human_review=confidence < confidence_threshold,
        review_notes=data.get("review_notes", []),
    )


def _pattern_relevant_to_step(pattern_name: str, step_data: dict) -> bool:
    """Check if a pattern is relevant to a specific step based on keywords."""
    step_text = (step_data.get("intent", "") + " " + step_data.get("implementation", "")).lower()
    # Simple keyword matching between pattern name and step text
    keywords = pattern_name.replace("_", " ").split()
    return any(kw in step_text for kw in keywords)


# Max tokens worth of source code per step in the interpretation prompt.
# Steps with summaries from chain_analyzer are preferred; raw source is
# truncated to keep the prompt within context window limits.
_MAX_SOURCE_TOKENS_PER_STEP = 2000


def _truncate_source(source_code: str, max_tokens: int = _MAX_SOURCE_TOKENS_PER_STEP) -> str:
    """Truncate source code to fit within token budget using ABAP-aware chunking."""
    if not source_code:
        return ""
    from spec2sphere.llm.chunking import chunk_text

    chunks = chunk_text(source_code, max_tokens=max_tokens)
    if not chunks:
        return ""
    # Use only the first chunk — the most important code is at the top
    result = chunks[0]
    if len(chunks) > 1:
        result += f"\n\n... [{len(chunks) - 1} more section(s) truncated]"
    return result
