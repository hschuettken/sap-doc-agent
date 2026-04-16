"""TieredProvider — routes calls to different backends based on model tier.

Combines a local provider (LLM Router / Ollama) for cheap small/medium tasks
with a cloud provider (Anthropic) for large/reasoning tasks that need quality.

Configuration via environment variables:
  LLM_TIER_SMALL     = model name for small tier     (default: qwen2.5:7b)
  LLM_TIER_MEDIUM    = model name for medium tier     (default: qwen2.5:14b)
  LLM_TIER_LARGE     = "anthropic" or model name      (default: anthropic)
  LLM_TIER_REASONING = "anthropic" or model name      (default: anthropic)

When a tier resolves to "anthropic", calls go through the Anthropic provider
(which has its own tier→model mapping: Haiku/Sonnet/Opus).
Otherwise, calls go through the local provider with that model name.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from spec2sphere.llm.base import DEFAULT_TIER, LLMProvider

logger = logging.getLogger(__name__)

# Tier → default model/backend mapping
# When using the homelab LLM Router, Claude model names route to the Claude
# sidecar adapter automatically. No separate Anthropic provider needed.
_TIER_DEFAULTS = {
    "small": "qwen2.5:7b",
    "medium": "qwen2.5:14b",
    "large": "claude-haiku-4-5-20251001",
    "reasoning": "claude-sonnet-4-6",
}


class TieredProvider(LLMProvider):
    """Routes LLM calls to different backends based on tier.

    Args:
        local_provider: Provider for local/cheap models (Router, Ollama, vLLM).
        cloud_provider: Provider for high-quality models (Anthropic, OpenAI).
            If None, all tiers fall back to local_provider.
        tier_map: Override tier→model mapping. Keys are tier names, values are
            either "anthropic" (routes to cloud_provider) or a model name
            (routes to local_provider with that model).
    """

    def __init__(
        self,
        local_provider: LLMProvider,
        cloud_provider: LLMProvider | None = None,
        tier_map: dict[str, str] | None = None,
    ):
        self._local = local_provider
        self._cloud = cloud_provider
        self._tier_map: dict[str, str] = {}

        # Build tier map: env vars > explicit tier_map > defaults
        # When no cloud provider, replace "anthropic" defaults with best local model
        for tier, default_model in _TIER_DEFAULTS.items():
            env_key = f"LLM_TIER_{tier.upper()}"
            env_val = os.environ.get(env_key)
            if env_val:
                self._tier_map[tier] = env_val
            elif tier_map and tier in tier_map:
                self._tier_map[tier] = tier_map[tier]
            elif default_model == "anthropic" and cloud_provider is None:
                # No cloud backend — use best available local model
                self._tier_map[tier] = _TIER_DEFAULTS["medium"]
            else:
                self._tier_map[tier] = default_model

        logger.info(
            "TieredProvider initialized: %s (cloud=%s)",
            self._tier_map,
            "yes" if cloud_provider else "no",
        )

    def _route(self, tier: str) -> tuple[LLMProvider, str]:
        """Return (provider, tier_for_that_provider) for a given tier."""
        model = self._tier_map.get(tier, self._tier_map.get(DEFAULT_TIER, "anthropic"))

        if model == "anthropic" and self._cloud is not None:
            return self._cloud, tier
        if model == "anthropic" and self._cloud is None:
            # No cloud provider — fall back to local with default model
            logger.warning("Tier %r wants Anthropic but no cloud provider configured, falling back to local", tier)
            return self._local, "medium"

        # Local provider — override its model via tier
        # We pass the tier through; the local provider's _resolve_model will use its default
        # But we want to use the specific model from our tier map
        return self._local, tier

    def _get_model_for_tier(self, tier: str) -> str | None:
        """Get the explicit model name for a tier, or None if it routes to cloud."""
        model = self._tier_map.get(tier, "anthropic")
        if model == "anthropic":
            return None
        return model

    async def generate(self, prompt: str, system: str = "", *, tier: str = DEFAULT_TIER) -> Optional[str]:
        provider, routed_tier = self._route(tier)
        model_name = self._get_model_for_tier(tier)

        if model_name and hasattr(provider, "_chat"):
            # Local provider — directly call _chat with explicit model override
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            return await provider._chat(messages, model=model_name)

        # Cloud provider or provider without _chat — use generate with tier
        return await provider.generate(prompt, system=system, tier=routed_tier)

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        system: str = "",
        *,
        tier: str = DEFAULT_TIER,
    ) -> Optional[dict]:
        provider, routed_tier = self._route(tier)
        return await provider.generate_json(prompt, schema, system=system, tier=routed_tier)

    def is_available(self) -> bool:
        return self._local.is_available() or (self._cloud is not None and self._cloud.is_available())

    async def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        # Embeddings always go through local provider (cheaper, nomic-embed-text)
        return await self._local.embed(texts)
