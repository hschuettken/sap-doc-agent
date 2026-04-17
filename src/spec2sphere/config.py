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
    """OAuth client credentials config (env-var style — used by existing YAML and DSPAuthFactory)."""

    client_id_env: Optional[str] = None
    client_secret_env: Optional[str] = None
    token_url_env: Optional[str] = None
    # Inline values (alternative to env var names)
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    token_url: Optional[str] = None


class DSPBasicAuthConfig(BaseModel):
    """Inline basic-auth credentials for Datasphere (resolved at runtime)."""

    username_env: Optional[str] = None
    password_env: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None


class DSPAuthConfig(BaseModel):
    """
    Top-level auth block on a SAPSystem entry.

    type: basic | oauth
      basic   → use DSPBasicAuthConfig fields (username/password)
      oauth   → use DSPAuthConfig.oauth sub-block OR top-level SAPSystem.oauth

    If ``type`` is omitted and an ``oauth`` sub-block is present → OAuth.
    If ``type`` is omitted and username/username_env is set → basic.
    """

    type: Optional[Literal["basic", "oauth"]] = None
    username_env: Optional[str] = None
    password_env: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    oauth: Optional[OAuthConfig] = None


class SAPSystem(BaseModel):
    name: str
    type: Literal["bw4hana", "datasphere"]
    transport: Optional[Literal["abapgit", "api", "filedrop"]] = None
    scan_scope: Optional[ScanScope] = None
    mcp_server: Optional[str] = None
    # Legacy OAuth block (env-var style) — kept for backward compat
    oauth: Optional[OAuthConfig] = None
    # New inline auth block (supports both basic and oauth, inline values + env)
    auth: Optional[DSPAuthConfig] = None
    spaces: Optional[list[str]] = None
    base_url: Optional[str] = None

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
