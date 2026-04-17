"""Microsoft Graph Connector — pushes Spec2Sphere content into M365 search index.

Uses the Microsoft Graph API with Azure AD client credentials flow.
All configuration comes from environment variables:
  M365_TENANT_ID       — Azure AD tenant ID
  M365_CLIENT_ID       — App registration client ID
  M365_CLIENT_SECRET   — App registration client secret
  M365_CONNECTION_ID   — External connection ID (a–z, 0–9, max 32 chars)

The connector is idempotent: create_connection() and create_schema() use
``if-match: *`` / ``update-or-insert`` semantics where available, and push_items()
calls the PUT /items/{id} endpoint which is inherently upsert.

Token caching: a single Bearer token is cached in the instance until 60 seconds
before expiry, then refreshed transparently on the next request.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

VALID_TYPES = {"spec", "route", "knowledge", "governance"}


@dataclass
class GraphItem:
    """A single item to push into the M365 external connection."""

    id: str
    title: str
    url: str
    body: str
    type: str  # one of VALID_TYPES
    last_modified: datetime
    author: str = "Spec2Sphere"

    def __post_init__(self) -> None:
        if self.type not in VALID_TYPES:
            raise ValueError(f"GraphItem.type must be one of {VALID_TYPES}, got {self.type!r}")
        if not self.id or not self.title or not self.url:
            raise ValueError("GraphItem.id, title, and url are required")


# ---------------------------------------------------------------------------
# Token cache
# ---------------------------------------------------------------------------


@dataclass
class _TokenCache:
    token: str = ""
    expires_at: float = 0.0  # epoch seconds

    def is_valid(self) -> bool:
        return bool(self.token) and time.time() < self.expires_at - 60


# ---------------------------------------------------------------------------
# Schema definition
# ---------------------------------------------------------------------------

_SCHEMA_PROPERTIES = [
    {"name": "title", "type": "String", "isSearchable": True, "isRetrievable": True, "isQueryable": True},
    {"name": "url", "type": "String", "isSearchable": False, "isRetrievable": True, "isQueryable": False},
    {"name": "body", "type": "String", "isSearchable": True, "isRetrievable": True, "isQueryable": False},
    {"name": "type", "type": "String", "isSearchable": False, "isRetrievable": True, "isQueryable": True},
    {"name": "lastModified", "type": "DateTime", "isSearchable": False, "isRetrievable": True, "isQueryable": True},
    {"name": "author", "type": "String", "isSearchable": True, "isRetrievable": True, "isQueryable": True},
]

# ---------------------------------------------------------------------------
# Main client
# ---------------------------------------------------------------------------


class GraphConnectorClient:
    """Client for the Microsoft Graph external connectors API.

    Raises ``RuntimeError`` if required env vars are missing at construction
    time (unless ``_allow_unconfigured=True`` is passed, used internally for
    the "skip gracefully" pattern in the sync task).
    """

    _GRAPH_BASE = "https://graph.microsoft.com/v1.0"
    _TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    def __init__(
        self,
        tenant_id: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        connection_id: Optional[str] = None,
        _allow_unconfigured: bool = False,
    ) -> None:
        self.tenant_id = tenant_id or os.environ.get("M365_TENANT_ID", "")
        self.client_id = client_id or os.environ.get("M365_CLIENT_ID", "")
        self.client_secret = client_secret or os.environ.get("M365_CLIENT_SECRET", "")
        self.connection_id = connection_id or os.environ.get("M365_CONNECTION_ID", "")

        missing = [
            k
            for k, v in {
                "M365_TENANT_ID": self.tenant_id,
                "M365_CLIENT_ID": self.client_id,
                "M365_CLIENT_SECRET": self.client_secret,
                "M365_CONNECTION_ID": self.connection_id,
            }.items()
            if not v
        ]
        if missing and not _allow_unconfigured:
            raise RuntimeError(f"Missing required M365 env vars: {', '.join(missing)}")

        self._token_cache = _TokenCache()

    @property
    def is_configured(self) -> bool:
        """Return True if all required env vars are present."""
        return all([self.tenant_id, self.client_id, self.client_secret, self.connection_id])

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    async def _get_token(self) -> str:
        """Return a valid Bearer token, refreshing if necessary."""
        if self._token_cache.is_valid():
            return self._token_cache.token

        url = self._TOKEN_URL_TEMPLATE.format(tenant=self.tenant_id)
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.post(
                url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        self._token_cache.token = payload["access_token"]
        self._token_cache.expires_at = time.time() + int(payload.get("expires_in", 3600))
        logger.debug("Graph API token refreshed, expires in %s s", payload.get("expires_in"))
        return self._token_cache.token

    async def _headers(self) -> dict[str, str]:
        token = await self._get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def create_connection(self) -> dict:
        """Create (or update) the external connection in Graph.

        Uses PATCH semantics — idempotent on repeated calls.
        Returns the connection resource JSON.
        """
        url = f"{self._GRAPH_BASE}/external/connections/{self.connection_id}"
        body = {
            "id": self.connection_id,
            "name": "Spec2Sphere Knowledge",
            "description": (
                "SAP Datasphere and SAC delivery knowledge: specs, routes, "
                "best practices, and governance rules from Spec2Sphere."
            ),
        }
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.patch(url, json=body, headers=await self._headers())
            if resp.status_code == 409:
                # Connection already exists — fetch it
                get_resp = await c.get(url, headers=await self._headers())
                get_resp.raise_for_status()
                logger.info("Graph connection %s already exists", self.connection_id)
                return get_resp.json()
            resp.raise_for_status()
            logger.info("Graph connection %s created/updated", self.connection_id)
            return resp.json() if resp.content else {}

    async def create_schema(self) -> None:
        """Register the schema for the external connection.

        The Graph API registers schemas asynchronously; this call fires-and-forgets
        (returns 202 Accepted). Repeated calls are safe.
        """
        url = f"{self._GRAPH_BASE}/external/connections/{self.connection_id}/schema"
        body = {"baseType": "microsoft.graph.externalItem", "properties": _SCHEMA_PROPERTIES}
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.patch(url, json=body, headers=await self._headers())
            if resp.status_code in (200, 202, 204):
                logger.info("Schema registration accepted for connection %s", self.connection_id)
                return
            if resp.status_code == 409:
                logger.info("Schema already registered for connection %s", self.connection_id)
                return
            resp.raise_for_status()

    # ------------------------------------------------------------------
    # Item operations
    # ------------------------------------------------------------------

    def _item_payload(self, item: GraphItem) -> dict:
        """Build the Graph API payload for a single item."""
        iso_ts = item.last_modified.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return {
            "@odata.type": "microsoft.graph.externalItem",
            "id": item.id,
            "acl": [{"type": "everyone", "value": "everyone", "accessType": "grant"}],
            "properties": {
                "title": item.title,
                "url": item.url,
                "body": item.body,
                "type": item.type,
                "lastModified": iso_ts,
                "author": item.author,
            },
            "content": {"value": item.body, "type": "text"},
        }

    async def push_item(self, item: GraphItem) -> None:
        """Upsert a single item into the external connection (PUT = idempotent)."""
        url = f"{self._GRAPH_BASE}/external/connections/{self.connection_id}/items/{item.id}"
        async with httpx.AsyncClient(timeout=30) as c:
            resp = await c.put(url, json=self._item_payload(item), headers=await self._headers())
            resp.raise_for_status()
            logger.debug("Pushed item %s (status %s)", item.id, resp.status_code)

    async def push_items(self, items: list[GraphItem]) -> dict:
        """Push a list of items, collecting successes and failures.

        Returns a summary dict::

            {"pushed": N, "failed": N, "errors": [{"id": "...", "error": "..."}]}
        """
        pushed = 0
        failed = 0
        errors: list[dict] = []
        for item in items:
            try:
                await self.push_item(item)
                pushed += 1
            except Exception as exc:
                failed += 1
                errors.append({"id": item.id, "error": str(exc)})
                logger.warning("Failed to push item %s: %s", item.id, exc)
        logger.info("push_items: pushed=%d failed=%d", pushed, failed)
        return {"pushed": pushed, "failed": failed, "errors": errors}

    async def delete_item(self, item_id: str) -> None:
        """Delete an item from the external connection."""
        url = f"{self._GRAPH_BASE}/external/connections/{self.connection_id}/items/{item_id}"
        async with httpx.AsyncClient(timeout=15) as c:
            resp = await c.delete(url, headers=await self._headers())
            if resp.status_code == 404:
                logger.debug("delete_item: %s not found (already gone)", item_id)
                return
            resp.raise_for_status()
            logger.info("Deleted item %s", item_id)

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------

    async def full_sync(self) -> dict:
        """Ensure connection + schema exist, then push all current content.

        Returns push summary dict.
        """
        await self.create_connection()
        await self.create_schema()
        items = _build_all_items()
        logger.info("full_sync: pushing %d items", len(items))
        return await self.push_items(items)

    async def incremental_sync(self, since: datetime) -> dict:
        """Push only items whose last_modified is after *since*.

        Returns push summary dict.
        """
        all_items = _build_all_items()
        since_utc = since.astimezone(timezone.utc)
        changed = [i for i in all_items if i.last_modified.astimezone(timezone.utc) > since_utc]
        logger.info("incremental_sync: %d/%d items modified since %s", len(changed), len(all_items), since_utc)
        if not changed:
            return {"pushed": 0, "failed": 0, "errors": []}
        return await self.push_items(changed)


# ---------------------------------------------------------------------------
# Content builders — pull from ContentHub
# ---------------------------------------------------------------------------


def _build_all_items() -> list[GraphItem]:
    """Collect all Spec2Sphere content and return as GraphItem list."""
    from spec2sphere.copilot.content_hub import ContentHub

    hub = ContentHub()
    items: list[GraphItem] = []
    now = datetime.now(tz=timezone.utc)

    for section in hub.get_index().get("sections", []):
        sid = section["id"]
        type_map = {
            "knowledge": "knowledge",
            "standards": "governance",
            "architecture": "spec",
            "migration": "spec",
            "quality": "governance",
            "glossary": "knowledge",
        }
        item_type = type_map.get(sid, "knowledge")
        sec_data = hub.get_section(sid)
        if not sec_data:
            continue
        for page_stub in sec_data.get("pages", []):
            pid = page_stub["id"]
            page = hub.get_page(sid, pid)
            if not page:
                continue
            item_id = f"s2s-{sid}-{pid}".replace("/", "-")[:100]
            raw_ts = page.get("updated_at", "")
            try:
                last_mod = datetime.fromisoformat(raw_ts.rstrip("Z")).replace(tzinfo=timezone.utc) if raw_ts else now
            except ValueError:
                last_mod = now
            items.append(
                GraphItem(
                    id=item_id,
                    title=page["title"],
                    url=f"/copilot/{sid}/{pid}",
                    body=page.get("content_md", "")[:8000],  # Graph API limit
                    type=item_type,
                    last_modified=last_mod,
                    author="Spec2Sphere",
                )
            )

    return items
