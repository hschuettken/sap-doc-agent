"""OpenAIProvider — calls the OpenAI API."""

from __future__ import annotations

import os

from spec2sphere.llm.base import OpenAICompatibleAdapter

_OPENAI_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "gpt-4o"


class OpenAIProvider(OpenAICompatibleAdapter):
    """Calls the official OpenAI API.

    Reads:
      OPENAI_API_KEY — required
      OPENAI_MODEL   — optional, defaults to gpt-4o
    """

    def __init__(self) -> None:
        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        model = os.environ.get("OPENAI_MODEL", _DEFAULT_MODEL)
        super().__init__(base_url=_OPENAI_BASE_URL, api_key=api_key, model=model)
