"""GeminiProvider — calls Google Gemini via the OpenAI-compatible endpoint."""

from __future__ import annotations

import os

from sap_doc_agent.llm.base import OpenAICompatibleAdapter

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiProvider(OpenAICompatibleAdapter):
    """Calls Google Gemini via its OpenAI-compatible API.

    Reads:
      GEMINI_API_KEY — required (Google AI Studio API key)
      GEMINI_MODEL   — optional, defaults to gemini-2.5-flash
    """

    def __init__(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is not set")
        model = os.environ.get("GEMINI_MODEL", _DEFAULT_MODEL)
        super().__init__(base_url=_GEMINI_BASE_URL, api_key=api_key, model=model)
