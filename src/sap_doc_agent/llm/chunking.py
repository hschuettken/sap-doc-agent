"""Text chunking utilities for processing large documents with LLMs."""

from __future__ import annotations

import re
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sap_doc_agent.llm.base import LLMProvider

from sap_doc_agent.llm.structured import generate_json_with_retry

# Approximate tokens per word factor
_WORDS_PER_TOKEN = 1.3

# ABAP structural boundaries to split on
_ABAP_BOUNDARY_PATTERN = re.compile(
    r"(?=^\s*(?:FORM|METHOD|FUNCTION|ENDFORM|ENDMETHOD|ENDFUNCTION)\b)",
    re.MULTILINE | re.IGNORECASE,
)


def chunk_text(text: str, max_tokens: int, overlap: int = 50) -> list[str]:
    """Split text into chunks of approximately max_tokens (estimated by word count * 1.3).

    Splits on ABAP FORM/METHOD/FUNCTION/ENDFORM boundaries if present,
    otherwise splits by paragraphs, then by words as a fallback.

    Each chunk overlaps the previous by ``overlap`` words.
    """
    if not text:
        return []

    max_words = int(max_tokens / _WORDS_PER_TOKEN)

    # Try ABAP structural splits first
    abap_sections = _ABAP_BOUNDARY_PATTERN.split(text)
    if len(abap_sections) > 1:
        sections = [s.strip() for s in abap_sections if s.strip()]
    else:
        # Fall back to paragraph splitting
        sections = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    if not sections:
        sections = [text]

    chunks: list[str] = []
    current_words: list[str] = []

    for section in sections:
        section_words = section.split()
        # If the section itself exceeds max_words, break it into sub-chunks
        if len(section_words) > max_words:
            start = 0
            while start < len(section_words):
                end = min(start + max_words, len(section_words))
                sub_chunk_words = section_words[start:end]
                if current_words:
                    # Flush current buffer first
                    chunks.append(" ".join(current_words))
                    current_words = current_words[-overlap:] if overlap else []
                current_words.extend(sub_chunk_words)
                if len(current_words) >= max_words:
                    chunks.append(" ".join(current_words))
                    current_words = current_words[-overlap:] if overlap else []
                start = end
        else:
            # Would adding this section exceed the limit?
            if len(current_words) + len(section_words) > max_words and current_words:
                chunks.append(" ".join(current_words))
                current_words = current_words[-overlap:] if overlap else []
            current_words.extend(section_words)

    # Flush remaining words
    if current_words:
        chunks.append(" ".join(current_words))

    return chunks


async def chunk_and_aggregate(
    provider: "LLMProvider",
    prompt_template: str,
    chunks: list[str],
    schema: dict[str, Any],
) -> Optional[dict]:
    """Run generate_json_with_retry on each chunk, then merge the results.

    Merging strategy:
    - Lists: concatenated
    - Scalars: first non-None value wins
    - Nested dicts: recursively merged with the same strategy
    """
    results: list[dict] = []
    for chunk in chunks:
        prompt = prompt_template.replace("{chunk}", chunk)
        result = await generate_json_with_retry(provider, prompt, schema)
        if result is not None:
            results.append(result)

    if not results:
        return None
    if len(results) == 1:
        return results[0]

    return _merge_dicts(results)


def _merge_dicts(dicts: list[dict]) -> dict:
    """Merge a list of dicts: lists are concatenated, scalars use first-wins."""
    merged: dict[str, Any] = {}
    for d in dicts:
        for key, value in d.items():
            if key not in merged:
                merged[key] = value
            elif isinstance(merged[key], list) and isinstance(value, list):
                merged[key] = merged[key] + value
            elif isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = _merge_dicts([merged[key], value])
            # else: first value wins
    return merged
