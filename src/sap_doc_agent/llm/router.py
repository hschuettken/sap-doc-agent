"""RouterLLMProvider — wraps the homelab LLM Router."""

from __future__ import annotations

import os

from sap_doc_agent.llm.base import OpenAICompatibleAdapter


class RouterLLMProvider(OpenAICompatibleAdapter):
    """Thin wrapper around the homelab LLM Router (OpenAI-compatible endpoint).

    Reads:
      LLM_ROUTER_URL   — base URL of the router (e.g. http://router:8070/v1)
      LLM_ROUTER_API_KEY — API key for the router
    """

    def __init__(self) -> None:
        base_url = os.environ.get("LLM_ROUTER_URL", "")
        if not base_url:
            raise ValueError("LLM_ROUTER_URL environment variable is not set")
        api_key = os.environ.get("LLM_ROUTER_API_KEY", "no-key")
        model = os.environ.get("LLM_ROUTER_MODEL", "default")
        super().__init__(base_url=base_url, api_key=api_key, model=model)
