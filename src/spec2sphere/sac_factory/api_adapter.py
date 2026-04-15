"""SAC API Adapter — wraps SAC REST API calls for story/model management and transport."""

from __future__ import annotations

import httpx


class SACApiAdapter:
    """Async adapter for SAP Analytics Cloud REST API."""

    def __init__(self, base_url: str, auth_token: str = "") -> None:
        self._base_url = base_url.rstrip("/")
        self._headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if auth_token:
            self._headers["Authorization"] = f"Bearer {auth_token}"

    async def list_stories(self, folder: str = "/") -> list[dict]:
        """List stories in the given folder.

        Args:
            folder: Target folder path (default: root "/").

        Returns:
            List of story metadata dicts.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/stories",
                headers=self._headers,
                params={"folder": folder},
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("value", [])

    async def get_story_metadata(self, story_id: str) -> dict:
        """Fetch metadata for a specific story.

        Args:
            story_id: SAC story identifier.

        Returns:
            Story metadata dict.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/stories/{story_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_model_metadata(self, model_id: str) -> dict:
        """Fetch metadata for a SAC data model.

        Args:
            model_id: SAC model identifier.

        Returns:
            Model metadata dict.
        """
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{self._base_url}/api/v1/models/{model_id}",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def export_transport(self, object_id: str, object_type: str = "story") -> bytes:
        """Export a story or app as a transport package.

        Args:
            object_id: Identifier of the object to export.
            object_type: "story" or "app" (default: "story").

        Returns:
            Raw bytes of the transport package (tgz).
        """
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/transport/export",
                headers=self._headers,
                json={"objectId": object_id, "objectType": object_type},
            )
            resp.raise_for_status()
            return resp.content

    async def sync_environment_inventory(self) -> dict:
        """Sync environment inventory — list all objects across stories, models, folders."""
        stories = await self.list_stories()
        models = []
        for story in stories:
            try:
                meta = await self.get_story_metadata(story.get("id", ""))
                models.extend(meta.get("models", []))
            except Exception:
                pass
        return {
            "stories": stories,
            "models": models,
            "total_stories": len(stories),
            "total_models": len(models),
        }

    async def import_transport(self, package: bytes, target_folder: str = "/") -> dict:
        """Import a transport package into SAC.

        Args:
            package: Raw tgz bytes to import.
            target_folder: Destination folder path (default: root "/").

        Returns:
            Import result dict (e.g. {"status": "success", "imported_id": "..."}).
        """
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/api/v1/transport/import",
                headers={**self._headers, "Content-Type": "application/octet-stream"},
                content=package,
                params={"targetFolder": target_folder},
            )
            resp.raise_for_status()
            return resp.json()
