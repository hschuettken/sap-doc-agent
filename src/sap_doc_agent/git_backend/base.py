"""Abstract base for Git backend adapters."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional


class GitBackend(ABC):
    @abstractmethod
    def write_file(self, path: str, content: str, commit_message: str) -> None:
        """Create or update a file in the repo."""

    @abstractmethod
    def read_file(self, path: str) -> Optional[str]:
        """Read a file. Returns None if not found."""

    @abstractmethod
    def list_files(self, path: str) -> list[str]:
        """List files in a directory."""

    @abstractmethod
    def delete_file(self, path: str, commit_message: str) -> None:
        """Delete a file from the repo."""
