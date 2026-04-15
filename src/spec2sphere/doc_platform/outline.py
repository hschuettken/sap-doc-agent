"""Outline documentation platform adapter."""

from __future__ import annotations
from typing import Optional
import httpx
from spec2sphere.doc_platform.base import DocPlatformAdapter, Page, Space


class OutlineAdapter(DocPlatformAdapter):
    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout

    async def create_space(self, name: str, description: str = "") -> Space:
        resp = await self._request("collections.create", {"name": name, "description": description})
        return Space(id=resp["data"]["id"], name=resp["data"]["name"])

    async def create_page(
        self, space_id: str, title: str, content: str, parent_id: Optional[str] = None, is_chapter: bool = False
    ) -> Page:
        body: dict = {"collectionId": space_id, "title": title, "text": content, "publish": True}
        if parent_id:
            body["parentDocumentId"] = parent_id
        resp = await self._request("documents.create", body)
        return Page(id=resp["data"]["id"], title=resp["data"]["title"], content=resp["data"].get("text", ""))

    async def update_page(self, page_id: str, content: str, title: Optional[str] = None) -> None:
        body: dict = {"id": page_id, "text": content}
        if title:
            body["title"] = title
        await self._request("documents.update", body)

    async def get_page(self, page_id: str) -> Page:
        resp = await self._request("documents.info", {"id": page_id})
        return Page(id=resp["data"]["id"], title=resp["data"]["title"], content=resp["data"].get("text", ""))

    async def search(self, query: str) -> list[Page]:
        resp = await self._request("documents.search", {"query": query})
        return [
            Page(id=doc["document"]["id"], title=doc["document"]["title"], content=doc["document"].get("text", ""))
            for doc in resp.get("data", [])
        ]

    async def delete_page(self, page_id: str) -> None:
        await self._request("documents.delete", {"id": page_id})

    async def _request(self, endpoint: str, body: dict) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/api/{endpoint}", headers=self._headers, json=body)
            resp.raise_for_status()
            return resp.json()
