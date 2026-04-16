"""LLM-powered 2-pass chain analysis: step summaries -> chain summary."""

from __future__ import annotations


from spec2sphere.llm.base import LLMProvider
from spec2sphere.scanner.models import DataFlowChain

_STEP_SYSTEM = (
    "You are analyzing an SAP BW transformation routine. "
    "Describe what this ABAP code does in plain language. "
    "Focus on the business logic (what data is filtered, converted, aggregated, mapped), "
    "not ABAP syntax. If the code is a currency conversion, say so. "
    "If it filters by company code, say which codes. "
    "Respond with a JSON object containing: "
    '"summary" (1-3 sentence description), '
    '"confidence" (0.0-1.0 self-assessed confidence in your analysis).'
)

_STEP_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["summary", "confidence"],
}

_CHAIN_SYSTEM = (
    "You are analyzing a complete SAP BW data flow chain. "
    "Based on the step-by-step descriptions, produce a JSON object with: "
    '"name" (short business name, 3-8 words), '
    '"summary" (3-5 sentence business summary of the whole chain), '
    '"observations" (list of notable patterns: hardcoded values, potential simplifications, technical debt), '
    '"confidence" (0.0-1.0 self-assessed confidence in your analysis).'
)

_CHAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "summary": {"type": "string"},
        "observations": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number"},
    },
    "required": ["name", "summary", "confidence"],
}


async def analyze_chain_steps(chain: DataFlowChain, llm: LLMProvider) -> DataFlowChain:
    """Pass 1: Analyze each transformation step's ABAP source individually.

    Enriches each step with:
    - step_summary: plain-language description of what the ABAP does
    - confidence: LLM self-assessed confidence (0.0-1.0)
    - upstream_context: summaries of all preceding steps
    - downstream_context: summaries of all following steps (filled after all steps analyzed)
    """
    result = chain.model_copy(deep=True)

    # Forward pass: analyze each step, accumulating upstream context
    prior_summaries: list[str] = []
    for i, step in enumerate(result.steps):
        # Set upstream context from previously analyzed steps
        if prior_summaries:
            result.steps[i].upstream_context = " → ".join(prior_summaries)

        if not step.source_code.strip():
            prior_summaries.append(f"{step.name} (no source)")
            continue

        context_parts = [f"Step {step.position} of {len(result.steps)} in the chain."]
        if prior_summaries:
            context_parts.append(f"Previous steps: {' → '.join(prior_summaries)}")
        if step.inter_step_object_name:
            context_parts.append(f"Writes output to: {step.inter_step_object_name}")
        if step.inter_step_fields:
            context_parts.append(f"Output fields: {', '.join(step.inter_step_fields)}")

        prompt = "\n".join(context_parts) + f"\n\nABAP source:\n```\n{step.source_code}\n```"

        data = await llm.generate_json(prompt, schema=_STEP_SCHEMA, system=_STEP_SYSTEM, tier="chain_analyzer")
        if data and isinstance(data, dict):
            summary = data.get("summary", "")
            result.steps[i].step_summary = summary.strip()
            result.steps[i].confidence = float(data.get("confidence", 0.0))
            prior_summaries.append(summary.strip() or step.name)
        else:
            # Fallback: try plain text generate
            text = await llm.generate(prompt, system=_STEP_SYSTEM, tier="chain_analyzer")
            if text:
                result.steps[i].step_summary = text.strip()
                prior_summaries.append(text.strip())
            else:
                prior_summaries.append(step.name)

    # Backward pass: fill downstream_context for each step
    following_summaries: list[str] = []
    for i in range(len(result.steps) - 1, -1, -1):
        if following_summaries:
            result.steps[i].downstream_context = " → ".join(reversed(following_summaries))
        step_desc = result.steps[i].step_summary or result.steps[i].name
        following_summaries.append(step_desc)

    return result


async def summarize_chain(chain: DataFlowChain, llm: LLMProvider) -> DataFlowChain:
    """Pass 2: Generate chain-level business summary from step summaries."""
    result = chain.model_copy(deep=True)

    step_descriptions = []
    for step in result.steps:
        desc = f"Step {step.position}: {step.name}"
        if step.step_summary:
            desc += f" — {step.step_summary}"
        if step.inter_step_object_name:
            desc += f" (writes to {step.inter_step_object_name})"
        step_descriptions.append(desc)

    prompt = f"Chain from {result.source_object_ids} to {result.terminal_object_id}.\n\n" + "\n".join(step_descriptions)

    data = await llm.generate_json(prompt, schema=_CHAIN_SCHEMA, system=_CHAIN_SYSTEM, tier="chain_analyzer")
    if data:
        result.name = data.get("name", "")
        result.summary = data.get("summary", "")
        result.observations = data.get("observations", [])
        result.confidence = data.get("confidence", 0.0)

    from datetime import datetime, timezone

    result.analyzed_at = datetime.now(timezone.utc)

    return result
