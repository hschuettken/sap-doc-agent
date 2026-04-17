"""LLM provider factory.

Provider selection priority:
1. LLM_PROVIDER environment variable (if set)
2. cfg.provider field (if set)
3. cfg.mode field (backward compat: "none", "copilot_passthrough", "direct")
4. Default to "router" (homelab default)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from spec2sphere.config import LLMConfig
from spec2sphere.llm.base import LLMProvider
from spec2sphere.llm.direct import DirectLLMProvider
from spec2sphere.llm.noop import NoopLLMProvider
from spec2sphere.llm.passthrough import CopilotPassthroughProvider


def _resolve_env(env_name: str) -> str:
    val = os.environ.get(env_name)
    if val is None:
        raise ValueError(f"Required environment variable '{env_name}' is not set")
    return val


def _create_from_provider_name(provider: str, cfg: LLMConfig, output_dir: Optional[Path]) -> LLMProvider:
    """Instantiate a provider by name string."""
    if provider == "none":
        return NoopLLMProvider()

    if provider == "copilot_passthrough":
        return CopilotPassthroughProvider(output_dir=output_dir or Path("reports/prompts"))

    if provider in ("direct", "openai_compatible"):
        # Legacy direct mode — reads env vars from cfg fields
        base_url = _resolve_env(cfg.base_url_env or "LLM_BASE_URL")
        api_key = _resolve_env(cfg.api_key_env or "LLM_API_KEY")
        return DirectLLMProvider(base_url=base_url, api_key=api_key, model=cfg.model or "gpt-4")

    if provider == "router":
        from spec2sphere.llm.router import RouterLLMProvider

        return RouterLLMProvider()

    if provider == "openai":
        from spec2sphere.llm.openai import OpenAIProvider

        return OpenAIProvider()

    if provider == "azure":
        from spec2sphere.llm.azure_openai import AzureOpenAIProvider

        return AzureOpenAIProvider()

    if provider == "anthropic":
        from spec2sphere.llm.anthropic import AnthropicProvider

        return AnthropicProvider()

    if provider == "vllm":
        from spec2sphere.llm.vllm import VLLMProvider

        return VLLMProvider()

    if provider == "ollama":
        from spec2sphere.llm.ollama import OllamaProvider

        return OllamaProvider()

    if provider == "gemini":
        from spec2sphere.llm.gemini import GeminiProvider

        return GeminiProvider()

    raise ValueError(f"Unknown LLM provider: {provider!r}")


def _wrap_with_tiered(local_provider: LLMProvider) -> LLMProvider:
    """Wrap a local provider with TieredProvider for tier-based model selection.

    The TieredProvider uses the same local provider for all tiers, but
    selects different models per tier (e.g. qwen2.5:7b for small,
    claude-sonnet-4-6 for reasoning). The LLM Router handles routing
    Claude model names to its Claude sidecar automatically.

    If ANTHROPIC_API_KEY is set, a dedicated Anthropic provider is used
    as cloud backend for large/reasoning tiers (direct API, no router).
    """
    cloud = None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        try:
            from spec2sphere.llm.anthropic import AnthropicProvider

            cloud = AnthropicProvider()
        except Exception:
            pass

    from spec2sphere.llm.tiered import TieredProvider

    return TieredProvider(local_provider=local_provider, cloud_provider=cloud)


def create_llm_provider(cfg: LLMConfig, output_dir: Optional[Path] = None) -> LLMProvider:
    """Create an LLM provider from config + environment variables.

    Resolution order:
    1. LLM_PROVIDER env var
    2. cfg.provider field
    3. cfg.mode field (backward compat)
    4. Default "router" (homelab default)

    If ANTHROPIC_API_KEY is set, the provider is automatically wrapped in a
    TieredProvider that routes large/reasoning calls to Anthropic and
    small/medium calls to the local provider.

    Every returned provider is wrapped in ObservedLLMProvider (outermost) so
    all generate() / generate_json() calls are logged to dsp_ai.generations.
    """
    from spec2sphere.llm.observed import ObservedLLMProvider

    def _wrap(p: LLMProvider) -> LLMProvider:
        return ObservedLLMProvider(p) if not isinstance(p, ObservedLLMProvider) else p

    # 1. Environment variable takes highest priority
    env_provider = os.environ.get("LLM_PROVIDER")
    if env_provider:
        # "anthropic" as sole provider — don't wrap with tiered, use directly
        if env_provider == "anthropic":
            return _wrap(_create_from_provider_name(env_provider, cfg, output_dir))
        provider = _create_from_provider_name(env_provider, cfg, output_dir)
        return _wrap(_wrap_with_tiered(provider))

    # 2. Config provider field
    if cfg.provider:
        if cfg.provider == "anthropic":
            return _wrap(_create_from_provider_name(cfg.provider, cfg, output_dir))
        provider = _create_from_provider_name(cfg.provider, cfg, output_dir)
        return _wrap(_wrap_with_tiered(provider))

    # 3. Backward compat: cfg.mode
    if cfg.mode == "none":
        return _wrap(NoopLLMProvider())
    if cfg.mode == "copilot_passthrough":
        return _wrap(CopilotPassthroughProvider(output_dir=output_dir or Path("reports/prompts")))
    if cfg.mode == "direct":
        base_url = _resolve_env(cfg.base_url_env or "LLM_BASE_URL")
        api_key = _resolve_env(cfg.api_key_env or "LLM_API_KEY")
        provider = DirectLLMProvider(base_url=base_url, api_key=api_key, model=cfg.model or "gpt-4")
        return _wrap(_wrap_with_tiered(provider))

    raise ValueError(f"Unknown LLM mode: {cfg.mode}")
