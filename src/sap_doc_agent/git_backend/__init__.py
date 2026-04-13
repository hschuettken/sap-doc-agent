"""Git backend factory."""
from __future__ import annotations
import os
from sap_doc_agent.config import GitConfig
from sap_doc_agent.git_backend.base import GitBackend


def _resolve_env(env_name: str) -> str:
    val = os.environ.get(env_name)
    if val is None:
        raise ValueError(f"Required environment variable '{env_name}' is not set")
    return val


def create_git_backend(cfg: GitConfig) -> GitBackend:
    token = _resolve_env(cfg.token_env)
    repo_url = _resolve_env(cfg.url_env)

    if cfg.type == "github":
        from sap_doc_agent.git_backend.github_backend import GitHubBackend
        return GitHubBackend(token=token, repo_name=repo_url)

    if cfg.type == "gitea":
        from sap_doc_agent.git_backend.github_backend import GitHubBackend
        base = os.environ.get("GITEA_BASE_URL", "http://192.168.0.64:3000/api/v1")
        return GitHubBackend(token=token, repo_name=repo_url, base_url=base)

    raise ValueError(f"Git backend type '{cfg.type}' not yet implemented. Supported: github, gitea")
