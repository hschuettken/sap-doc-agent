"""Stage 2: parallel context fetchers."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any

import asyncpg
import httpx

from ..brain.client import run as brain_run
from ..config import Enhancement
from ..settings import dsp_dsn


@dataclass
class GatheredContext:
    dsp_data: list[dict] = field(default_factory=list)
    brain_nodes: list[dict] = field(default_factory=list)
    external_info: list[dict] = field(default_factory=list)
    user_state: dict[str, Any] = field(default_factory=dict)
    quality_warnings: list[str] = field(default_factory=list)


async def _dsp_fetch(enh: Enhancement) -> list[dict]:
    conn = await asyncpg.connect(dsp_dsn())
    try:
        rows = await conn.fetch(
            enh.config.bindings.data.dsp_query,
            *enh.config.bindings.data.parameters.values(),
        )
        return [dict(r) for r in rows]
    finally:
        await conn.close()


async def _brain_fetch(enh: Enhancement) -> list[dict]:
    sb = enh.config.bindings.semantic
    if sb is None:
        return []
    return await brain_run(sb.cypher, **sb.parameters)


async def _external_fetch(enh: Enhancement, context: dict) -> list[dict]:
    eb = enh.config.bindings.external
    if eb is None or os.environ.get("SEARXNG_ENABLED", "true") != "true":
        return []
    url = os.environ.get("SEARXNG_URL", "http://searxng:8080/search")
    from jinja2 import Template  # noqa: PLC0415

    query = Template(eb.searxng_query).render(**context)
    async with httpx.AsyncClient(timeout=8.0) as c:
        resp = await c.get(
            url,
            params={"q": query, "format": "json", "categories": ",".join(eb.categories)},
        )
        data = resp.json() if resp.status_code == 200 else {}
        return data.get("results", [])[: eb.max_results]


async def _user_state(user_id: str) -> dict:
    from ..db import get_conn  # noqa: PLC0415

    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT last_visited_at, last_briefed_at, topics_of_interest, preferences "
            "FROM dsp_ai.user_state WHERE user_id = $1",
            user_id,
        )
        return dict(row) if row else {}


async def gather(enh: Enhancement, user_id: str | None, context_hints: dict) -> GatheredContext:
    ctx = GatheredContext()
    tasks: dict[str, asyncio.Task] = {
        "dsp": asyncio.create_task(_dsp_fetch(enh)),
        "brain": asyncio.create_task(_brain_fetch(enh)),
        "external": asyncio.create_task(_external_fetch(enh, context_hints)),
    }
    if user_id:
        tasks["user"] = asyncio.create_task(_user_state(user_id))

    for name, task in tasks.items():
        try:
            result = await asyncio.wait_for(task, timeout=10.0)
            if name == "dsp":
                ctx.dsp_data = result
            elif name == "brain":
                ctx.brain_nodes = result
            elif name == "external":
                ctx.external_info = result
            elif name == "user":
                ctx.user_state = result
        except Exception:
            ctx.quality_warnings.append(f"{name}_context_missing")
    return ctx
