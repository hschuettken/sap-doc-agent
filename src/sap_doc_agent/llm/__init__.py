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

from sap_doc_agent.config import LLMConfig
from sap_doc_agent.llm.base import LLMProvider
from sap_doc_agent.llm.direct import DirectLLMProvider
from sap_doc_agent.llm.noop import NoopLLMProvider
from sap_doc_agent.llm.passthrough import CopilotPassthroughProvider


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
        from sap_doc_agent.llm.router import RouterLLMProvider

        return RouterLLMProvider()

    if provider == "openai":
        from sap_doc_agent.llm.openai import OpenAIProvider

        return OpenAIProvider()

    if provider == "azure":
        from sap_doc_agent.llm.azure_openai import AzureOpenAIProvider

        return AzureOpenAIProvider()

    if provider == "anthropic":
        from sap_doc_agent.llm.anthropic import AnthropicProvider

        return AnthropicProvider()

    if provider == "vllm":
        from sap_doc_agent.llm.vllm import VLLMProvider

        return VLLMProvider()

    if provider == "ollama":
        from sap_doc_agent.llm.ollama import OllamaProvider

        return OllamaProvider()

    if provider == "gemini":
        from sap_doc_agent.llm.gemini import GeminiProvider

        return GeminiProvider()

    raise ValueError(f"Unknown LLM provider: {provider!r}")


def create_llm_provider(cfg: LLMConfig, output_dir: Optional[Path] = None) -> LLMProvider:
    """Create an LLM provider from config + environment variables.

    Resolution order:
    1. LLM_PROVIDER env var
    2. cfg.provider field
    3. cfg.mode field (backward compat)
    4. Default "router" (homelab default)
    """
    # 1. Environment variable takes highest priority
    env_provider = os.environ.get("LLM_PROVIDER")
    if env_provider:
        return _create_from_provider_name(env_provider, cfg, output_dir)

    # 2. Config provider field
    if cfg.provider:
        return _create_from_provider_name(cfg.provider, cfg, output_dir)

    # 3. Backward compat: cfg.mode
    if cfg.mode == "none":
        return NoopLLMProvider()
    if cfg.mode == "copilot_passthrough":
        return CopilotPassthroughProvider(output_dir=output_dir or Path("reports/prompts"))
    if cfg.mode == "direct":
        base_url = _resolve_env(cfg.base_url_env or "LLM_BASE_URL")
        api_key = _resolve_env(cfg.api_key_env or "LLM_API_KEY")
        return DirectLLMProvider(base_url=base_url, api_key=api_key, model=cfg.model or "gpt-4")

    raise ValueError(f"Unknown LLM mode: {cfg.mode}")
