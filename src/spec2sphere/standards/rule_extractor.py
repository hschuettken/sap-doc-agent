"""LLM-based rule extraction from documentation standards."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from spec2sphere.llm.base import LLMProvider

logger = logging.getLogger(__name__)

RULE_SCHEMA = {
    "type": "object",
    "properties": {
        "sections": {"type": "array", "items": {"type": "string"}},
        "naming_rules": {"type": "array", "items": {"type": "object"}},
        "field_requirements": {"type": "array", "items": {"type": "object"}},
        "custom_rules": {"type": "array", "items": {"type": "object"}},
    },
}

SYSTEM_PROMPT = """You are an SAP documentation standards analyst.
Extract structured rules from the provided documentation standard text.
Return a JSON object with sections, naming_rules, field_requirements, and custom_rules."""


async def extract_rules(text: str, llm: "LLMProvider") -> dict:
    """Extract structured rules from documentation standard text using LLM."""
    from spec2sphere.llm.structured import generate_json_with_retry

    if not llm.is_available():
        logger.warning("LLM not available, returning empty rules")
        return {
            "sections": [],
            "naming_rules": [],
            "field_requirements": [],
            "custom_rules": [],
            "error": "LLM not available",
        }

    # Chunk large documents
    MAX_CHARS = 12000
    if len(text) > MAX_CHARS:
        from spec2sphere.llm.chunking import chunk_and_aggregate

        chunks_text = [text[i : i + MAX_CHARS] for i in range(0, len(text), MAX_CHARS - 500)]
        result = await chunk_and_aggregate(llm, "Extract rules from this section:\n\n{chunk}", chunks_text, RULE_SCHEMA)
        return result or {"sections": [], "naming_rules": [], "field_requirements": [], "custom_rules": []}

    prompt = f"Extract all documentation rules from the following standard:\n\n{text}"
    result = await generate_json_with_retry(llm, prompt, RULE_SCHEMA, system=SYSTEM_PROMPT)

    if result is None:
        logger.warning("Rule extraction returned None, using empty result")
        return {"sections": [], "naming_rules": [], "field_requirements": [], "custom_rules": []}

    return result
