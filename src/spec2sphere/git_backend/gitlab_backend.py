"""GitLab Git backend adapter using httpx REST API."""

from __future__ import annotations

import base64
from typing import Optional
from urllib.parse import quote

import httpx

from spec2sphere.git_backend.base import GitBackend


class GitLabBackend(GitBackend):
    def __init__(
        self,
        token: str,
        repo_name: str,
        branch: str = "main",
        base_url: str = "https://gitlab.com",
    ):
        self._branch = branch
        self._headers = {"PRIVATE-TOKEN": token}
        # URL-encode the repo path (e.g. "group/project" → "group%2Fproject")
        encoded = quote(repo_name, safe="")
        self._base = f"{base_url.rstrip('/')}/api/v4/projects/{encoded}/repository"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _file_url(self, path: str) -> str:
        return f"{self._base}/files/{quote(path, safe='')}"

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        return httpx.get(url, headers=self._headers, params=params)

    def _post(self, url: str, json: dict) -> httpx.Response:
        return httpx.post(url, headers=self._headers, json=json)

    def _put(self, url: str, json: dict) -> httpx.Response:
        return httpx.put(url, headers=self._headers, json=json)

    def _delete(self, url: str, json: dict) -> httpx.Response:
        return httpx.delete(url, headers=self._headers, json=json)

    # ------------------------------------------------------------------
    # GitBackend interface
    # ------------------------------------------------------------------

    def write_file(self, path: str, content: str, commit_message: str) -> None:
        encoded_content = base64.b64encode(content.encode()).decode()
        payload = {
            "branch": self._branch,
            "content": encoded_content,
            "encoding": "base64",
            "commit_message": commit_message,
        }
        # Check whether the file already exists
        check = self._get(self._file_url(path), params={"ref": self._branch})
        if check.status_code == 200:
            resp = self._put(self._file_url(path), json=payload)
        else:
            resp = self._post(self._file_url(path), json=payload)
        resp.raise_for_status()

    def read_file(self, path: str) -> Optional[str]:
        resp = self._get(self._file_url(path), params={"ref": self._branch})
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return base64.b64decode(data["content"]).decode("utf-8")

    def list_files(self, path: str) -> list[str]:
        resp = self._get(
            f"{self._base}/tree",
            params={"path": path, "ref": self._branch, "per_page": 100},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return [item["path"] for item in resp.json() if item["type"] == "blob"]

    def delete_file(self, path: str, commit_message: str) -> None:
        resp = self._delete(
            self._file_url(path),
            json={"branch": self._branch, "commit_message": commit_message},
        )
        if resp.status_code == 404:
            return
        resp.raise_for_status()
