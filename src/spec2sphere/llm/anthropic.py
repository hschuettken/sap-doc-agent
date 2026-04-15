"""AnthropicProvider — calls the Anthropic Messages API via raw httpx (no SDK dependency)."""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

from spec2sphere.llm.base import LLMProvider

logger = logging.getLogger(__name__)

_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_DEFAULT_MODEL = "claude-opus-4-6"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_TOKENS = 4096


class AnthropicProvider(LLMProvider):
    """Calls the Anthropic Messages API.

    Uses raw httpx — no anthropic SDK dependency.

    Reads:
      ANTHROPIC_API_KEY — required
      ANTHROPIC_MODEL   — optional, defaults to claude-opus-4-6
    """

    def __init__(self) -> None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set")
        self._api_key = api_key
        self._model = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL)
        self._timeout = 60.0

    async def generate(self, prompt: str, system: str = "") -> Optional[str]:
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": _MAX_TOKENS,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            payload["system"] = system
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    _MESSAGES_URL,
                    headers={
                        "x-api-key": self._api_key,
                        "anthropic-version": _ANTHROPIC_VERSION,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                return data["content"][0]["text"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            logger.warning("Anthropic API call failed: %s", exc)
            return None

    async def generate_json(self, prompt: str, schema: dict[str, Any], system: str = "") -> Optional[dict]:
        import json

        system_msg = system or "You are a structured data extraction assistant."
        system_msg += f"\n\nRespond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"
        raw = await self.generate(prompt, system=system_msg)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Anthropic returned non-JSON response, skipping: %s", raw[:200])
            return None

    def is_available(self) -> bool:
        return True
