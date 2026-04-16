"""TieredProvider — routes calls to different backends based on quality level.

Uses the QualityRouter to resolve action names / quality levels / legacy tier
names to concrete model names. The LLM Router handles routing Claude model
names to its Claude sidecar adapter automatically.

Accepts any of these in the ``tier`` parameter:
  - Action name: "semantic_parser" → resolved via QualityRouter
  - Quality level: "Q1"–"Q5" → mapped to model via active profile
  - Legacy tier: "small"/"medium"/"large"/"reasoning" → mapped to Q1–Q4
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from spec2sphere.llm.base import DEFAULT_TIER, LLMProvider
from spec2sphere.llm.quality_router import get_quality_router

logger = logging.getLogger(__name__)


class TieredProvider(LLMProvider):
    """Routes LLM calls to different models via the QualityRouter.

    Args:
        local_provider: Provider for all models (Router, Ollama, vLLM).
            The LLM Router handles both local and Claude models.
        cloud_provider: Optional dedicated cloud provider (Anthropic direct API).
            Used only when a model resolves to "anthropic" (legacy).
    """

    def __init__(
        self,
        local_provider: LLMProvider,
        cloud_provider: LLMProvider | None = None,
        tier_map: dict[str, str] | None = None,  # ignored, kept for compat
    ):
        self._local = local_provider
        self._cloud = cloud_provider
        self._router = get_quality_router()
        logger.info(
            "TieredProvider initialized with QualityRouter (profile=%s, cloud=%s)",
            self._router.get_active_profile_name(),
            "yes" if cloud_provider else "no",
        )

    def _resolve(self, tier: str) -> tuple[LLMProvider, str]:
        """Resolve tier/action/quality to (provider, model_name)."""
        model = self._router.resolve(tier)

        # "anthropic" sentinel → route to cloud provider (legacy path)
        if model == "anthropic" and self._cloud is not None:
            return self._cloud, tier
        if model == "anthropic":
            logger.warning("Model resolved to 'anthropic' but no cloud provider; falling back to local")
            model = "qwen2.5:14b"

        return self._local, model

    async def generate(self, prompt: str, system: str = "", *, tier: str = DEFAULT_TIER) -> Optional[str]:
        provider, model = self._resolve(tier)

        if provider is self._local and hasattr(provider, "_chat"):
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            return await provider._chat(messages, model=model)

        return await provider.generate(prompt, system=system, tier=tier)

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        system: str = "",
        *,
        tier: str = DEFAULT_TIER,
    ) -> Optional[dict]:
        provider, model = self._resolve(tier)

        if provider is self._local and hasattr(provider, "_chat"):
            # Build JSON prompt manually so we can pass the explicit model
            import json as _json

            system_msg = system or "You are a structured data extraction assistant."
            system_msg += f"\n\nRespond with valid JSON matching this schema:\n{_json.dumps(schema, indent=2)}"
            messages = [
                {"role": "system", "content": system_msg},
                {"role": "user", "content": prompt},
            ]
            raw = await provider._chat(messages, model=model)
            if raw is None:
                return None
            try:
                return _json.loads(raw)
            except _json.JSONDecodeError:
                logger.warning("LLM returned non-JSON response: %s", raw[:200])
                return None

        return await provider.generate_json(prompt, schema, system=system, tier=tier)

    def is_available(self) -> bool:
        return self._local.is_available() or (self._cloud is not None and self._cloud.is_available())

    async def embed(self, texts: list[str]) -> Optional[list[list[float]]]:
        return await self._local.embed(texts)
