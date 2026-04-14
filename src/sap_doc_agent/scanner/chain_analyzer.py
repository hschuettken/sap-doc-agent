"""LLM-powered 2-pass chain analysis: step summaries -> chain summary."""

from __future__ import annotations

from sap_doc_agent.llm.base import LLMProvider
from sap_doc_agent.scanner.models import DataFlowChain

_STEP_SYSTEM = (
    "You are analyzing an SAP BW transformation routine. "
    "Describe what this ABAP code does in 1-3 plain language sentences. "
    "Focus on the business logic (what data is filtered, converted, aggregated, mapped), "
    "not ABAP syntax. If the code is a currency conversion, say so. "
    "If it filters by company code, say which codes."
)

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
    """Pass 1: Analyze each transformation step's ABAP source individually."""
    result = chain.model_copy(deep=True)

    for i, step in enumerate(result.steps):
        if not step.source_code.strip():
            continue

        context_parts = [f"Step {step.position} of {len(result.steps)} in the chain."]
        if step.inter_step_object_name:
            context_parts.append(f"Writes output to: {step.inter_step_object_name}")
        if step.inter_step_fields:
            context_parts.append(f"Output fields: {', '.join(step.inter_step_fields)}")

        prompt = "\n".join(context_parts) + f"\n\nABAP source:\n```\n{step.source_code}\n```"

        summary = await llm.generate(prompt, system=_STEP_SYSTEM)
        if summary:
            result.steps[i].step_summary = summary.strip()

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

    data = await llm.generate_json(prompt, schema=_CHAIN_SCHEMA, system=_CHAIN_SYSTEM)
    if data:
        result.name = data.get("name", "")
        result.summary = data.get("summary", "")
        result.observations = data.get("observations", [])
        result.confidence = data.get("confidence", 0.0)

    return result
