"""Abstract base for LLM providers.

Model tier system
-----------------
Every ``generate`` / ``generate_json`` call accepts an optional **tier**
parameter that tells the provider which class of model to use:

* ``small``     – fast, cheap: naming checks, rule matching (e.g. qwen2.5:7b)
* ``medium``    – structured extraction, doc audit (e.g. qwen2.5:14b)
* ``large``     – complex reasoning: BRS parsing, HLA, blueprints (e.g. Sonnet)
* ``reasoning`` – deepest reasoning: architecture decisions (e.g. Opus)

Callers that omit tier default to ``"large"`` — prefer quality over speed.
Individual providers may ignore tier if they only have one backend.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Valid tier names, ordered from cheapest to most capable
TIERS = ("small", "medium", "large", "reasoning")
DEFAULT_TIER = "large"


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        tier: str = DEFAULT_TIER,
        data_in_context: bool = False,
    ) -> Optional[str]:
        """Generate a text completion. Returns None if LLM is unavailable.

        Args:
            data_in_context: Set True when the prompt contains customer SQL,
                ABAP source, field definitions, or any data from connected
                systems. Privacy-aware providers will route to local models.
        """

    @abstractmethod
    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        system: str = "",
        *,
        tier: str = DEFAULT_TIER,
        data_in_context: bool = False,
    ) -> Optional[dict]:
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

    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        tier: str = DEFAULT_TIER,
        data_in_context: bool = False,
    ) -> Optional[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        model = self._resolve_model(tier)
        return await self._chat(messages, model=model)

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        system: str = "",
        *,
        tier: str = DEFAULT_TIER,
        data_in_context: bool = False,
    ) -> Optional[dict]:
        system_msg = system or "You are a structured data extraction assistant."
        system_msg += f"\n\nRespond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"
        raw = await self.generate(prompt, system=system_msg, tier=tier, data_in_context=data_in_context)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("LLM returned non-JSON response, skipping: %s", raw[:200])
            return None

    def is_available(self) -> bool:
        return True

    def _resolve_model(self, tier: str) -> str:
        """Resolve tier to a model name. Subclasses can override for tier routing."""
        return self._model

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

    async def _chat(self, messages: list[dict], model: str | None = None) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
                    json={"model": model or self._model, "messages": messages},
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            logger.warning("LLM API call failed: %s", exc)
            return None
