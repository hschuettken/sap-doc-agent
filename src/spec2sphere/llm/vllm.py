"""VLLMProvider — calls a vLLM inference server (OpenAI-compatible endpoint)."""

from __future__ import annotations

import os

from spec2sphere.llm.base import OpenAICompatibleAdapter


class VLLMProvider(OpenAICompatibleAdapter):
    """Calls a vLLM server via its OpenAI-compatible endpoint.

    Reads:
      VLLM_BASE_URL — required (e.g. http://vllm-server:8000)
      VLLM_MODEL    — required
      VLLM_API_KEY  — optional, defaults to "no-key"
    """

    def __init__(self) -> None:
        base_url = os.environ.get("VLLM_BASE_URL", "")
        if not base_url:
            raise ValueError("VLLM_BASE_URL environment variable is not set")
        model = os.environ.get("VLLM_MODEL", "")
        if not model:
            raise ValueError("VLLM_MODEL environment variable is not set")
        api_key = os.environ.get("VLLM_API_KEY", "no-key")
        # vLLM exposes OpenAI-compatible endpoint at /v1
        super().__init__(base_url=f"{base_url.rstrip('/')}/v1", api_key=api_key, model=model)
