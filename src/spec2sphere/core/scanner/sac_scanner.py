"""SAC Tenant Scanner — inventory SAP Analytics Cloud content.

Strategy:
  1. Try SAC Content Network API (stories, models) first — fast and reliable.
  2. Fall back to CDP browser session for metadata not exposed via API.
  3. Call store_sac_results() to persist into landscape_objects with platform='sac'.

SAC API references:
  Stories  : GET {sac_url}/api/v1/stories
  Models   : GET {sac_url}/api/v1/models
  Both endpoints support $top/$skip pagination.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional

import httpx

from spec2sphere.browser.pool import get_pool
from spec2sphere.tenant.context import ContextEnvelope

logger = logging.getLogger(__name__)

# SAC object types we recognise
SAC_OBJECT_TYPES = frozenset(
    [
        "story",
        "optimized_story",
        "analytic_application",
        "model",
        "folder",
        "data_action",
    ]
)

_SAC_TYPE_MAP: dict[str, str] = {
    "STORY": "story",
    "OPTIMIZED_STORY": "optimized_story",
    "ANALYTIC_APP": "analytic_application",
    "APPLICATION": "analytic_application",
    "MODEL": "model",
    "FOLDER": "folder",
    "DATA_ACTION": "data_action",
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SACInventoryItem:
    """A single SAC content object discovered during a tenant scan."""

    name: str
    object_type: str  # story | optimized_story | analytic_application | model | folder | data_action
    technical_id: str
    metadata: dict = field(default_factory=dict)
    pages: Optional[list[dict]] = None
    widgets: Optional[list[dict]] = None
    model_bindings: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Public scan entry point
# ---------------------------------------------------------------------------


async def scan_sac_tenant(
    ctx: ContextEnvelope,
    sac_url: str,
    auth_token: Optional[str] = None,
    use_cdp: bool = True,
) -> list[SACInventoryItem]:
    """Scan a SAC tenant and return the full content inventory.

    Tries the SAC Content Network API first (auth_token required).
    Falls back to CDP browser session when API is unavailable or returns
    an empty result set.

    Parameters
    ----------
    ctx:        Request context envelope (used for browser pool look-up).
    sac_url:    Base URL of the SAC tenant, e.g. https://mytenant.eu10.hcs.cloud.sap
    auth_token: Bearer token for SAC API calls.  If None, API path is skipped.
    use_cdp:    When True, CDP fallback is attempted if API yields nothing.
    """
    sac_url = sac_url.rstrip("/")
    items: list[SACInventoryItem] = []

    if auth_token:
        try:
            items = await _scan_via_api(sac_url, auth_token)
            logger.info("SAC API scan: found %d items", len(items))
        except Exception as exc:
            logger.warning("SAC API scan failed (%s) — will try CDP fallback", exc)

    if not items and use_cdp:
        try:
            items = await _scan_via_cdp(ctx, sac_url)
            logger.info("SAC CDP scan: found %d items", len(items))
        except Exception as exc:
            logger.warning("SAC CDP scan failed: %s", exc)

    return items


# ---------------------------------------------------------------------------
# API-based scan
# ---------------------------------------------------------------------------


async def _scan_via_api(sac_url: str, auth_token: str) -> list[SACInventoryItem]:
    """Fetch stories and models from the SAC Content Network API."""
    headers = {
        "Authorization": f"Bearer {auth_token}",
        "Accept": "application/json",
    }
    items: list[SACInventoryItem] = []

    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        # Stories
        items.extend(await _paginate_api(client, sac_url, "/api/v1/stories", "story"))
        # Models
        items.extend(await _paginate_api(client, sac_url, "/api/v1/models", "model"))

    return items


async def _paginate_api(
    client: httpx.AsyncClient,
    sac_url: str,
    path: str,
    default_type: str,
    page_size: int = 100,
) -> list[SACInventoryItem]:
    """Paginate a SAC API endpoint and collect all items."""
    collected: list[SACInventoryItem] = []
    skip = 0

    while True:
        resp = await client.get(
            f"{sac_url}{path}",
            params={"$top": page_size, "$skip": skip},
        )
        if resp.status_code != 200:
            logger.warning("SAC API %s returned %d", path, resp.status_code)
            break

        data = resp.json()
        # OData envelope uses "value"; plain list is also accepted
        rows = data.get("value", data) if isinstance(data, dict) else data
        if not rows:
            break

        for row in rows:
            raw_type = row.get("type") or row.get("contentType") or default_type
            obj_type = _SAC_TYPE_MAP.get(raw_type.upper(), default_type)
            tech_id = str(row.get("id") or row.get("storyId") or row.get("modelId") or "")
            name = row.get("name") or row.get("title") or tech_id

            meta: dict = {}
            for field_name in ("owner", "createdTime", "modifiedTime", "description", "category"):
                if field_name in row:
                    meta[field_name] = row[field_name]

            collected.append(
                SACInventoryItem(
                    name=name,
                    object_type=obj_type,
                    technical_id=tech_id,
                    metadata=meta,
                )
            )

        if len(rows) < page_size:
            break
        skip += page_size

    return collected


# ---------------------------------------------------------------------------
# CDP-based scan (fallback)
# ---------------------------------------------------------------------------


async def _scan_via_cdp(ctx: ContextEnvelope, sac_url: str) -> list[SACInventoryItem]:
    """Use the browser pool to navigate SAC and extract content inventory.

    Navigates to the SAC home / file repository page and extracts the
    content tree by evaluating JavaScript against the SAC shell DOM.
    For each story/application found we attempt to navigate to it and
    extract page structure and widget metadata.
    """
    pool = get_pool()
    session = await pool.get_session(ctx.tenant_id, ctx.environment)
    if session is None:
        logger.info("No CDP session available — SAC CDP scan skipped")
        return []

    from spec2sphere.scanner.cdp_client import CDPClient

    client = CDPClient(cdp_url=session.cdp_url)

    items: list[SACInventoryItem] = []

    try:
        # Navigate to the SAC home page so the shell loads
        await client.navigate(f"{sac_url}/", target_id=None)

        # Attempt to extract the content repository via SAC's internal JS API.
        # The SAC shell exposes sap.fpa.ui.utils.Globals.getContentRepository()
        # when fully loaded.  We attempt this and fall back to DOM scraping.
        raw = await client.evaluate(
            """
            (function() {
                try {
                    var repo = sap.fpa.ui.utils.Globals.getContentRepository();
                    var items = repo ? repo.getAllItems() : [];
                    return JSON.stringify(items.map(function(i) {
                        return {
                            id: i.getId ? i.getId() : i.id,
                            name: i.getTitle ? i.getTitle() : i.name,
                            type: i.getType ? i.getType() : i.type
                        };
                    }));
                } catch(e) {
                    return JSON.stringify([]);
                }
            })()
            """
        )

        if raw:
            try:
                raw_items = json.loads(raw) if isinstance(raw, str) else raw
                for entry in raw_items:
                    tech_id = str(entry.get("id", ""))
                    name = entry.get("name") or tech_id
                    raw_type = str(entry.get("type", "story")).upper()
                    obj_type = _SAC_TYPE_MAP.get(raw_type, "story")
                    items.append(
                        SACInventoryItem(
                            name=name,
                            object_type=obj_type,
                            technical_id=tech_id,
                            metadata={"source": "cdp"},
                        )
                    )
            except (json.JSONDecodeError, TypeError) as exc:
                logger.debug("CDP JS result parse error: %s", exc)

    except Exception as exc:
        logger.warning("SAC CDP navigation error: %s", exc)
        session.mark_unhealthy(str(exc))

    return items


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


async def store_sac_results(
    items: list[SACInventoryItem],
    ctx: ContextEnvelope,
) -> dict:
    """Persist SACInventoryItems as landscape_objects with platform='sac'.

    Maps pages, widgets, and model_bindings into the metadata JSONB field.
    Builds a dependency chain: story -> model_id entries go into the
    dependencies JSONB field as {target_id, dependency_type: 'model_binding'}.

    Returns {"stored": int}.
    """
    if not items:
        return {"stored": 0}

    # Import here to avoid circular at module level
    import json
    import os
    from datetime import datetime, timezone

    import asyncpg

    async def _get_conn():
        db_url = os.environ.get("DATABASE_URL", "")
        url = db_url.replace("postgresql+psycopg://", "postgresql://").replace("postgresql+asyncpg://", "postgresql://")
        return await asyncpg.connect(url)

    conn = await _get_conn()
    stored = 0
    now = datetime.now(timezone.utc)

    try:
        async with conn.transaction():
            for item in items:
                meta = dict(item.metadata)
                if item.pages:
                    meta["pages"] = item.pages
                if item.widgets:
                    meta["widgets"] = item.widgets
                if item.model_bindings:
                    meta["model_bindings"] = item.model_bindings

                deps = [
                    {"target_id": mid, "dependency_type": "model_binding", "metadata": {}}
                    for mid in (item.model_bindings or [])
                ]

                existing = await conn.fetchrow(
                    """
                    SELECT id FROM landscape_objects
                    WHERE customer_id = $1
                      AND ($2::uuid IS NULL OR project_id = $2)
                      AND platform = 'sac'
                      AND technical_name = $3
                    LIMIT 1
                    """,
                    ctx.customer_id,
                    ctx.project_id,
                    item.technical_id,
                )

                if existing:
                    await conn.execute(
                        """
                        UPDATE landscape_objects SET
                            object_type  = $1,
                            object_name  = $2,
                            metadata     = $3::jsonb,
                            dependencies = $4::jsonb,
                            last_scanned = $5
                        WHERE id = $6
                        """,
                        item.object_type,
                        item.name,
                        json.dumps(meta),
                        json.dumps(deps),
                        now,
                        existing["id"],
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO landscape_objects
                            (customer_id, project_id, platform, object_type,
                             object_name, technical_name, metadata, dependencies, last_scanned)
                        VALUES ($1, $2, 'sac', $3, $4, $5, $6::jsonb, $7::jsonb, $8)
                        """,
                        ctx.customer_id,
                        ctx.project_id,
                        item.object_type,
                        item.name,
                        item.technical_id,
                        json.dumps(meta),
                        json.dumps(deps),
                        now,
                    )
                    stored += 1

    finally:
        await conn.close()

    logger.info(
        "sac_scanner: stored=%d customer=%s project=%s",
        stored,
        ctx.customer_id,
        ctx.project_id,
    )
    return {"stored": stored}
