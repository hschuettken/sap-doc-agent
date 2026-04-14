"""OllamaProvider — calls a local Ollama server via its OpenAI-compatible endpoint."""

from __future__ import annotations

import os

from sap_doc_agent.llm.base import OpenAICompatibleAdapter

_DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaProvider(OpenAICompatibleAdapter):
    """Calls a local (or remote) Ollama server via its OpenAI-compatible /v1 endpoint.

    Reads:
      OLLAMA_BASE_URL — optional, defaults to http://localhost:11434
      OLLAMA_MODEL    — required
    """

    def __init__(self) -> None:
        base_url = os.environ.get("OLLAMA_BASE_URL", _DEFAULT_OLLAMA_BASE_URL)
        model = os.environ.get("OLLAMA_MODEL", "")
        if not model:
            raise ValueError("OLLAMA_MODEL environment variable is not set")
        # Ollama exposes OpenAI-compatible endpoint at /v1; no auth needed
        super().__init__(base_url=f"{base_url.rstrip('/')}/v1", api_key="ollama", model=model)
