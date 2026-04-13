"""Top-level application entry point."""

from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from sap_doc_agent.config import AppConfig, load_config
from sap_doc_agent.doc_platform import create_doc_adapter
from sap_doc_agent.doc_platform.base import DocPlatformAdapter
from sap_doc_agent.git_backend import create_git_backend
from sap_doc_agent.git_backend.base import GitBackend
from sap_doc_agent.llm import create_llm_provider
from sap_doc_agent.llm.base import LLMProvider

import logging

logger = logging.getLogger(__name__)


@dataclass
class SAPDocAgent:
    config: AppConfig
    llm: LLMProvider
    doc_platform: DocPlatformAdapter
    git: GitBackend | None

    @classmethod
    def from_config(cls, config_path: Path | str) -> SAPDocAgent:
        config = load_config(config_path)
        llm = create_llm_provider(config.llm)
        doc_platform = create_doc_adapter(config.doc_platform)
        try:
            git = create_git_backend(config.git)
        except Exception as e:
            logger.warning("Git backend not available: %s — continuing without it", e)
            git = None
        return cls(config=config, llm=llm, doc_platform=doc_platform, git=git)
