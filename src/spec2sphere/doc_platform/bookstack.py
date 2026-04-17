"""BookStack documentation platform adapter."""

from __future__ import annotations
from typing import Optional
import httpx
from spec2sphere.doc_platform.base import DocPlatformAdapter, Page, Space


class BookStackAdapter(DocPlatformAdapter):
    def __init__(self, base_url: str, token_id: str, token_secret: str, timeout: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Token {token_id}:{token_secret}", "Content-Type": "application/json"}
        self._timeout = timeout

    async def create_space(self, name: str, description: str = "") -> Space:
        resp = await self._request("POST", "/api/books", json={"name": name, "description": description})
        return Space(id=str(resp["id"]), name=resp["name"])

    async def create_page(
        self, space_id: str, title: str, content: str, parent_id: Optional[str] = None, is_chapter: bool = False
    ) -> Page:
        if is_chapter:
            resp = await self._request("POST", "/api/chapters", json={"book_id": int(space_id), "name": title})
            return Page(id=str(resp["id"]), title=resp["name"])
        data: dict = {"name": title, "markdown": content}
        if parent_id:
            data["chapter_id"] = int(parent_id)
        else:
            data["book_id"] = int(space_id)
        resp = await self._request("POST", "/api/pages", json=data)
        return Page(id=str(resp["id"]), title=resp["name"], content=content)

    async def update_page(self, page_id: str, content: str, title: Optional[str] = None) -> None:
        data: dict = {"markdown": content}
        if title:
            data["name"] = title
        await self._request("PUT", f"/api/pages/{page_id}", json=data)

    async def get_page(self, page_id: str) -> Page:
        resp = await self._request("GET", f"/api/pages/{page_id}")
        labels = {tag["name"]: tag.get("value", "") for tag in resp.get("tags", [])}
        return Page(
            id=str(resp["id"]), title=resp["name"], content=resp.get("markdown", resp.get("html", "")), labels=labels
        )

    async def search(self, query: str) -> list[Page]:
        resp = await self._request("GET", "/api/search", params={"query": query})
        return [
            Page(id=str(item["id"]), title=item["name"], content=item.get("preview", {}).get("content", ""))
            for item in resp.get("data", [])
        ]

    async def delete_page(self, page_id: str) -> None:
        await self._request("DELETE", f"/api/pages/{page_id}")

    async def get_hierarchy(self, space_id: str) -> list[Page]:
        """List all pages in a book (space) with parent references."""
        resp = await self._request("GET", f"/api/books/{space_id}")
        pages: list[Page] = []
        for chapter in resp.get("contents", []):
            if chapter.get("type") == "chapter":
                chapter_id = str(chapter["id"])
                for page in chapter.get("pages", []):
                    pages.append(
                        Page(
                            id=str(page["id"]),
                            title=page["name"],
                            parent_id=chapter_id,
                        )
                    )
            elif chapter.get("type") == "page":
                pages.append(Page(id=str(chapter["id"]), title=chapter["name"]))
        return pages

    async def get_page_updated_at(self, page_id: str) -> Optional[str]:
        """Return the updated_at timestamp for a page (ISO 8601)."""
        resp = await self._request("GET", f"/api/pages/{page_id}")
        return resp.get("updated_at")

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.request(method, f"{self._base_url}{path}", headers=self._headers, **kwargs)
            resp.raise_for_status()
            return {} if resp.status_code == 204 else resp.json()
