"""AzureOpenAIProvider — calls the Azure OpenAI Service."""

from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from sap_doc_agent.llm.base import OpenAICompatibleAdapter

logger = logging.getLogger(__name__)

_API_VERSION = "2024-02-15-preview"


class AzureOpenAIProvider(OpenAICompatibleAdapter):
    """Calls the Azure OpenAI Service.

    Reads:
      AZURE_OPENAI_API_KEY    — required
      AZURE_OPENAI_ENDPOINT   — required (e.g. https://myresource.openai.azure.com)
      AZURE_OPENAI_DEPLOYMENT — required (deployment name = model alias in Azure)
    """

    def __init__(self) -> None:
        api_key = os.environ.get("AZURE_OPENAI_API_KEY", "")
        if not api_key:
            raise ValueError("AZURE_OPENAI_API_KEY environment variable is not set")
        endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
        if not endpoint:
            raise ValueError("AZURE_OPENAI_ENDPOINT environment variable is not set")
        deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "")
        if not deployment:
            raise ValueError("AZURE_OPENAI_DEPLOYMENT environment variable is not set")

        base_url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}"
        # Model name is not used in Azure requests (deployment carries it), but required by base class
        super().__init__(base_url=base_url, api_key=api_key, model=deployment)

    async def _chat(self, messages: list[dict]) -> Optional[str]:
        """Override to use Azure-specific endpoint path and api-key header."""
        url = f"{self._base_url}/chat/completions?api-version={_API_VERSION}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    url,
                    headers={"api-key": self._api_key, "Content-Type": "application/json"},
                    json={"model": self._model, "messages": messages},
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            logger.warning("Azure OpenAI API call failed: %s", exc)
            return None
