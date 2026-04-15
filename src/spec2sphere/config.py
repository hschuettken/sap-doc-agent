"""
Configuration framework for SAP Doc Agent.

All settings loaded from config.yaml. Environment variable references
(fields ending in _env) are resolved at adapter initialization time,
not at config load time — this keeps config portable across environments.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, field_validator


class ScanScope(BaseModel):
    top_level_providers: list[str] = []
    namespace_filter: list[str] = ["Z*", "Y*"]
    object_types: list[str] = [
        "adso",
        "composite",
        "transformation",
        "class",
        "fm",
        "table",
        "data_element",
        "domain",
        "infoobject",
        "process_chain",
        "data_source",
    ]
    max_depth: int | Literal["unlimited"] = "unlimited"


class OAuthConfig(BaseModel):
    client_id_env: str
    client_secret_env: str
    token_url_env: str


class SAPSystem(BaseModel):
    name: str
    type: Literal["bw4hana", "datasphere"]
    transport: Optional[Literal["abapgit", "api", "filedrop"]] = None
    scan_scope: Optional[ScanScope] = None
    mcp_server: Optional[str] = None
    oauth: Optional[OAuthConfig] = None
    spaces: Optional[list[str]] = None

    @field_validator("transport")
    @classmethod
    def bw_needs_transport(cls, v, info):
        if info.data.get("type") == "bw4hana" and v is None:
            raise ValueError("BW/4HANA systems require a transport backend")
        return v


class AuthConfig(BaseModel):
    type: Literal["api_token", "basic", "oauth"]
    token_env: Optional[str] = None
    username_env: Optional[str] = None
    password_env: Optional[str] = None


class DocPlatformConfig(BaseModel):
    type: Literal["bookstack", "outline", "confluence"]
    url: str
    auth: AuthConfig
    space_key: Optional[str] = None


class GitConfig(BaseModel):
    type: Literal["github", "gitea", "gitlab", "azure_devops"]
    url_env: str
    token_env: str


class LLMConfig(BaseModel):
    mode: Literal["none", "copilot_passthrough", "direct"] = "direct"  # backward compat
    provider: Optional[str] = None  # env var LLM_PROVIDER overrides this
    base_url_env: Optional[str] = None
    api_key_env: Optional[str] = None
    model: Optional[str] = None
    chunk_size_tokens: Optional[int] = None
    token_budget_per_hour: Optional[int] = None
    max_concurrent: int = 4


class ReportingConfig(BaseModel):
    formats: list[Literal["html", "pdf", "markdown"]] = ["html", "markdown"]
    sitemap: bool = True
    schedule: Optional[str] = None


class AppConfig(BaseModel):
    sap_systems: list[SAPSystem]
    doc_platform: DocPlatformConfig
    git: GitConfig
    llm: LLMConfig
    standards: list[str] = []
    reporting: ReportingConfig = ReportingConfig()


def load_config(path: Path | str) -> AppConfig:
    """Load and validate config from a YAML file."""
    path = Path(path)
    with open(path) as f:
        raw = yaml.safe_load(f)
    return AppConfig.model_validate(raw)
