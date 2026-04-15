"""Abstract base for documentation platform adapters."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Page:
    id: str
    title: str
    content: str = ""
    parent_id: Optional[str] = None
    labels: dict[str, str] = field(default_factory=dict)
    url: Optional[str] = None


@dataclass
class Space:
    id: str
    name: str
    url: Optional[str] = None


class DocPlatformAdapter(ABC):
    @abstractmethod
    async def create_space(self, name: str, description: str = "") -> Space:
        """Create a top-level space/book."""

    @abstractmethod
    async def create_page(
        self, space_id: str, title: str, content: str, parent_id: Optional[str] = None, is_chapter: bool = False
    ) -> Page:
        """Create a page (or chapter in BookStack)."""

    @abstractmethod
    async def update_page(self, page_id: str, content: str, title: Optional[str] = None) -> None:
        """Update page content."""

    @abstractmethod
    async def get_page(self, page_id: str) -> Page:
        """Get a page by ID."""

    @abstractmethod
    async def search(self, query: str) -> list[Page]:
        """Search for pages."""

    @abstractmethod
    async def delete_page(self, page_id: str) -> None:
        """Delete a page."""
