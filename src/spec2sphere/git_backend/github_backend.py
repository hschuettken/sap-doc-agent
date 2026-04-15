"""GitHub Git backend adapter."""

from __future__ import annotations
from typing import Optional
from github import Github, GithubException
from spec2sphere.git_backend.base import GitBackend


class GitHubBackend(GitBackend):
    def __init__(self, token: str, repo_name: str, branch: str = "main", base_url: Optional[str] = None):
        kwargs = {"login_or_token": token}
        if base_url:
            kwargs["base_url"] = base_url
        self._gh = Github(**kwargs)
        self._repo = self._gh.get_repo(repo_name)
        self._branch = branch

    def write_file(self, path: str, content: str, commit_message: str) -> None:
        try:
            existing = self._repo.get_contents(path, ref=self._branch)
            self._repo.update_file(path, commit_message, content, existing.sha, branch=self._branch)
        except GithubException as e:
            if e.status == 404:
                self._repo.create_file(path, commit_message, content, branch=self._branch)
            else:
                raise

    def read_file(self, path: str) -> Optional[str]:
        try:
            content = self._repo.get_contents(path, ref=self._branch)
            return content.decoded_content.decode("utf-8")
        except GithubException as e:
            if e.status == 404:
                return None
            raise

    def list_files(self, path: str) -> list[str]:
        try:
            contents = self._repo.get_contents(path, ref=self._branch)
            if not isinstance(contents, list):
                contents = [contents]
            return [c.path for c in contents if c.type == "file"]
        except GithubException as e:
            if e.status == 404:
                return []
            raise

    def delete_file(self, path: str, commit_message: str) -> None:
        try:
            existing = self._repo.get_contents(path, ref=self._branch)
            self._repo.delete_file(path, commit_message, existing.sha, branch=self._branch)
        except GithubException as e:
            if e.status == 404:
                return
            raise
