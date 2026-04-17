"""Confluence documentation platform adapter."""

from __future__ import annotations
import asyncio
from functools import partial
from typing import Optional
from atlassian import Confluence
from spec2sphere.doc_platform.base import DocPlatformAdapter, Page, Space


class ConfluenceAdapter(DocPlatformAdapter):
    def __init__(
        self, url: str, token: Optional[str] = None, username: Optional[str] = None, password: Optional[str] = None
    ):
        kwargs: dict = {"url": url}
        if token:
            kwargs["token"] = token
        elif username and password:
            kwargs["username"] = username
            kwargs["password"] = password
        self._client = Confluence(**kwargs)

    async def _run_sync(self, func, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    async def create_space(self, name: str, description: str = "") -> Space:
        key = name.upper().replace(" ", "_")[:10]
        resp = await self._run_sync(self._client.create_space, key, name, description)
        return Space(id=resp["key"], name=resp["name"])

    async def create_page(
        self, space_id: str, title: str, content: str, parent_id: Optional[str] = None, is_chapter: bool = False
    ) -> Page:
        kwargs: dict = {"space": space_id, "title": title, "body": content, "type": "page"}
        if parent_id:
            kwargs["parent_id"] = parent_id
        resp = await self._run_sync(self._client.create_page, **kwargs)
        return Page(id=str(resp["id"]), title=resp["title"], content=content)

    async def update_page(self, page_id: str, content: str, title: Optional[str] = None) -> None:
        current = await self._run_sync(self._client.get_page_by_id, page_id)
        await self._run_sync(self._client.update_page, page_id, title or current["title"], content)

    async def get_page(self, page_id: str) -> Page:
        resp = await self._run_sync(self._client.get_page_by_id, page_id, expand="body.storage,metadata.labels")
        labels = {label["name"]: "" for label in resp.get("metadata", {}).get("labels", {}).get("results", [])}
        return Page(
            id=str(resp["id"]),
            title=resp["title"],
            content=resp.get("body", {}).get("storage", {}).get("value", ""),
            labels=labels,
        )

    async def search(self, query: str) -> list[Page]:
        resp = await self._run_sync(self._client.cql, f'text ~ "{query}"')
        return [
            Page(id=str(item.get("content", item)["id"]), title=item.get("content", item)["title"])
            for item in resp.get("results", [])
        ]

    async def delete_page(self, page_id: str) -> None:
        await self._run_sync(self._client.remove_page, page_id)

    async def get_hierarchy(self, space_id: str) -> list[Page]:
        """List all pages in a Confluence space."""
        pages: list[Page] = []
        start = 0
        limit = 50
        while True:
            resp = await self._run_sync(
                self._client.get_all_pages_from_space,
                space_id,
                start=start,
                limit=limit,
                expand="ancestors",
            )
            batch = resp if isinstance(resp, list) else resp.get("results", [])
            for item in batch:
                ancestors = item.get("ancestors", [])
                parent_id = str(ancestors[-1]["id"]) if ancestors else None
                pages.append(Page(id=str(item["id"]), title=item["title"], parent_id=parent_id))
            if len(batch) < limit:
                break
            start += limit
        return pages

    async def get_page_updated_at(self, page_id: str) -> Optional[str]:
        """Return the last-updated timestamp from Confluence history (ISO 8601)."""
        resp = await self._run_sync(
            self._client.get_page_by_id,
            page_id,
            expand="history.lastUpdated",
        )
        return resp.get("history", {}).get("lastUpdated", {}).get("when")
