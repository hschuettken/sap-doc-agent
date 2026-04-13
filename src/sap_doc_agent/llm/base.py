"""Abstract base for LLM providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, system: str = "") -> Optional[str]:
        """Generate a text completion. Returns None if LLM is unavailable."""

    @abstractmethod
    async def generate_json(self, prompt: str, schema: dict[str, Any], system: str = "") -> Optional[dict]:
        """Generate a structured JSON response. Returns None if LLM is unavailable."""

    @abstractmethod
    def is_available(self) -> bool:
        """Whether this provider can actually call an LLM."""
