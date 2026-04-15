"""Abstract base for LLM providers."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


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

    async def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Generate embeddings for a list of texts. Returns None if not supported.

        Override in providers that support embeddings (OpenAI, Ollama/nomic-embed).
        Default implementation returns None (embeddings not supported).
        """
        return None


class OpenAICompatibleAdapter(LLMProvider):
    """Base for providers that speak the OpenAI /chat/completions API shape."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 60.0):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    async def generate(self, prompt: str, system: str = "") -> Optional[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return await self._chat(messages)

    async def generate_json(self, prompt: str, schema: dict[str, Any], system: str = "") -> Optional[dict]:
        system_msg = system or "You are a structured data extraction assistant."
        system_msg += f"\n\nRespond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"
        raw = await self.generate(prompt, system=system_msg)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON response, skipping: %s", raw[:200])
            return None

    def is_available(self) -> bool:
        return True

    async def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        """Generate embeddings via the OpenAI-compatible /embeddings endpoint."""
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={"model": self._model, "input": texts},
                )
                resp.raise_for_status()
                data = resp.json()
                return [item["embedding"] for item in data["data"]]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            logger.warning("Embedding API call failed: %s", exc)
            return None

    async def _chat(self, messages: list[dict]) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={"model": self._model, "messages": messages},
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            logger.warning("LLM API call failed: %s", exc)
            return None
