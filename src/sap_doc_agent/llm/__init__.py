"""LLM provider factory."""

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


def create_llm_provider(cfg: LLMConfig, output_dir: Optional[Path] = None) -> LLMProvider:
    if cfg.mode == "none":
        return NoopLLMProvider()
    if cfg.mode == "copilot_passthrough":
        return CopilotPassthroughProvider(output_dir=output_dir or Path("reports/prompts"))
    if cfg.mode == "direct":
        base_url = _resolve_env(cfg.base_url_env)
        api_key = _resolve_env(cfg.api_key_env)
        return DirectLLMProvider(base_url=base_url, api_key=api_key, model=cfg.model or "gpt-4")
    raise ValueError(f"Unknown LLM mode: {cfg.mode}")
