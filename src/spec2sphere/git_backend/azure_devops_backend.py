"""Azure DevOps Git backend adapter using httpx REST API."""

from __future__ import annotations

import base64
from typing import Optional

import httpx

from spec2sphere.git_backend.base import GitBackend

_API_VERSION = "7.0"


class AzureDevOpsBackend(GitBackend):
    """Adapter for Azure DevOps Git repositories.

    ``repo_url`` must be in the form ``"org/project/repo"``.
    ``token`` is a Personal Access Token (PAT).
    """

    def __init__(self, token: str, repo_url: str, branch: str = "main"):
        parts = repo_url.split("/")
        if len(parts) != 3:
            raise ValueError(f"Azure DevOps repo_url must be 'org/project/repo', got '{repo_url}'")
        org, project, repo = parts
        self._branch = branch
        self._ref_name = f"refs/heads/{branch}"
        # Basic auth: empty username + PAT
        pat_b64 = base64.b64encode(f":{token}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {pat_b64}",
            "Content-Type": "application/json",
        }
        self._base = f"https://dev.azure.com/{org}/{project}/_apis/git/repositories/{repo}"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _params(self, extra: dict | None = None) -> dict:
        p = {"api-version": _API_VERSION}
        if extra:
            p.update(extra)
        return p

    def _get_latest_commit(self) -> str:
        """Return the latest commit SHA on the configured branch."""
        resp = httpx.get(
            f"{self._base}/refs",
            headers=self._headers,
            params=self._params({"filter": f"heads/{self._branch}"}),
        )
        resp.raise_for_status()
        values = resp.json().get("value", [])
        if not values:
            raise ValueError(f"Branch '{self._branch}' not found in Azure DevOps repo")
        return values[0]["objectId"]

    def _push(self, changes: list[dict], commit_message: str) -> None:
        old_sha = self._get_latest_commit()
        payload = {
            "refUpdates": [{"name": self._ref_name, "oldObjectId": old_sha}],
            "commits": [{"comment": commit_message, "changes": changes}],
        }
        resp = httpx.post(
            f"{self._base}/pushes",
            headers=self._headers,
            params=self._params(),
            json=payload,
        )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # GitBackend interface
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str, commit_message: str) -> None:
        # Determine whether file exists to pick the right changeType
        existing = self.read_file(path)
        change_type = "edit" if existing is not None else "add"
        encoded = base64.b64encode(content.encode()).decode()
        change = {
            "changeType": change_type,
            "item": {"path": f"/{path.lstrip('/')}"},
            "newContent": {"content": encoded, "contentType": "base64Encoded"},
        }
        self._push([change], commit_message)

    def read_file(self, path: str) -> Optional[str]:
        resp = httpx.get(
            f"{self._base}/items",
            headers=self._headers,
            params=self._params(
                {
                    "path": f"/{path.lstrip('/')}",
                    "versionDescriptor.version": self._branch,
                    "versionDescriptor.versionType": "branch",
                    "$format": "text",
                }
            ),
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def list_files(self, path: str) -> list[str]:
        scope = f"/{path.lstrip('/')}" if path else "/"
        resp = httpx.get(
            f"{self._base}/items",
            headers=self._headers,
            params=self._params(
                {
                    "scopePath": scope,
                    "recursionLevel": "OneLevel",
                    "versionDescriptor.version": self._branch,
                    "versionDescriptor.versionType": "branch",
                }
            ),
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        items = resp.json().get("value", [])
        # Skip directories (gitObjectType == "tree") and the scope root itself
        return [item["path"].lstrip("/") for item in items if item.get("gitObjectType") == "blob"]

    def delete_file(self, path: str, commit_message: str) -> None:
        # If file doesn't exist, treat as no-op (matches GitHubBackend behaviour)
        if self.read_file(path) is None:
            return
        change = {
            "changeType": "delete",
            "item": {"path": f"/{path.lstrip('/')}"},
        }
        self._push([change], commit_message)
