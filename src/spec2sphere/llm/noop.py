"""Noop LLM provider — rule-based mode, no LLM calls."""

from __future__ import annotations

from typing import Any, Optional

from spec2sphere.llm.base import LLMProvider


class NoopLLMProvider(LLMProvider):
    async def generate(self, prompt: str, system: str = "") -> Optional[str]:
        return None

    async def generate_json(self, prompt: str, schema: dict[str, Any], system: str = "") -> Optional[dict]:
        return None

    def is_available(self) -> bool:
        return False
