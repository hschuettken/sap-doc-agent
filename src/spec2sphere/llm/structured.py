"""Structured JSON extraction helpers for LLM providers."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from spec2sphere.llm.base import LLMProvider


def _extract_balanced(text: str, open_char: str, close_char: str) -> Optional[str]:
    """Find the first balanced occurrence of open_char...close_char in text."""
    start = text.find(open_char)
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape_next = False
    for i, ch in enumerate(text[start:], start=start):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\" and in_string:
            escape_next = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_json_from_response(text: str) -> Optional[dict]:
    """Strip markdown fences and extract the first JSON object or array from text.

    Attempts in order:
    1. Raw parse of the whole string
    2. Strip markdown fences, then parse
    3. Find the first '{' balanced bracket and parse
    4. Find the first '[' balanced bracket and parse
    """
    if not text:
        return None

    # 1. Try raw parse
    try:
        result = json.loads(text)
        if isinstance(result, (dict, list)):
            return result  # type: ignore[return-value]
    except json.JSONDecodeError:
        pass

    # 2. Strip markdown fences
    stripped = re.sub(r"```(?:json)?\s*\n?(.*?)\n?```", r"\1", text, flags=re.DOTALL).strip()
    if stripped != text:
        try:
            result = json.loads(stripped)
            if isinstance(result, (dict, list)):
                return result  # type: ignore[return-value]
        except json.JSONDecodeError:
            pass

    # 3. Find the first balanced { ... }
    obj_candidate = _extract_balanced(text, "{", "}")
    if obj_candidate is not None:
        try:
            result = json.loads(obj_candidate)
            if isinstance(result, (dict, list)):
                return result  # type: ignore[return-value]
        except json.JSONDecodeError:
            pass

    # 4. Find the first balanced [ ... ]
    arr_candidate = _extract_balanced(text, "[", "]")
    if arr_candidate is not None:
        try:
            result = json.loads(arr_candidate)
            if isinstance(result, (dict, list)):
                return result  # type: ignore[return-value]
        except json.JSONDecodeError:
            pass

    return None


async def generate_json_with_retry(
    provider: "LLMProvider",
    prompt: str,
    schema: dict[str, Any],
    system: str = "",
    max_retries: int = 2,
) -> Optional[dict]:
    """Call provider.generate(), parse with extract_json_from_response.

    On parse failure, re-prompts the provider with an explicit correction request.
    Returns None only after all retries are exhausted.
    """
    schema_str = json.dumps(schema, indent=2)
    system_with_schema = system or "You are a structured data extraction assistant."
    system_with_schema += f"\n\nRespond with valid JSON matching this schema:\n{schema_str}"

    for attempt in range(max_retries + 1):
        if attempt == 0:
            current_prompt = prompt
        else:
            current_prompt = (
                f"{prompt}\n\nIMPORTANT: Your previous response was not valid JSON. "
                f"Respond ONLY with a JSON object matching this schema:\n{schema_str}"
            )

        raw = await provider.generate(current_prompt, system=system_with_schema)
        if raw is None:
            return None

        result = extract_json_from_response(raw)
        if result is not None:
            return result

    return None
