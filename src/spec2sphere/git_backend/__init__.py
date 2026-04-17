"""Git backend factory."""

from __future__ import annotations
import os
from spec2sphere.config import GitConfig
from spec2sphere.git_backend.base import GitBackend


def _resolve_env(env_name: str) -> str:
    val = os.environ.get(env_name)
    if val is None:
        raise ValueError(f"Required environment variable '{env_name}' is not set")
    return val


def create_git_backend(cfg: GitConfig) -> GitBackend:
    token = _resolve_env(cfg.token_env)
    repo_url = _resolve_env(cfg.url_env)

    if cfg.type == "github":
        from spec2sphere.git_backend.github_backend import GitHubBackend

        return GitHubBackend(token=token, repo_name=repo_url)

    if cfg.type == "gitea":
        from spec2sphere.git_backend.github_backend import GitHubBackend

        base = os.environ.get("GITEA_BASE_URL", "http://localhost:3000/api/v1")
        return GitHubBackend(token=token, repo_name=repo_url, base_url=base)

    if cfg.type == "gitlab":
        from spec2sphere.git_backend.gitlab_backend import GitLabBackend

        base = os.environ.get("GITLAB_BASE_URL", "https://gitlab.com")
        return GitLabBackend(token=token, repo_name=repo_url, base_url=base)

    if cfg.type == "azure_devops":
        from spec2sphere.git_backend.azure_devops_backend import AzureDevOpsBackend

        return AzureDevOpsBackend(token=token, repo_url=repo_url)

    raise ValueError(
        f"Git backend type '{cfg.type}' not yet implemented. Supported: github, gitea, gitlab, azure_devops"
    )
