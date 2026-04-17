"""MCP tool implementations for AI Studio.

Dispatched by mcp_server._call_tool when name == 'studio_*'. Each function
takes ``args: dict`` (from JSON-RPC) and returns the rendered MCP content
block. Rendering is plain-text summaries so Claude Code can act on them.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import asyncpg
import httpx

from spec2sphere.dsp_ai.settings import postgres_dsn


def _text(msg: str) -> dict:
    return {"content": [{"type": "text", "text": msg}]}


def _err(msg: str) -> dict:
    return {"content": [{"type": "text", "text": f"Error: {msg}"}], "isError": True}


async def list_enhancements(args: dict) -> dict:
    status = args.get("status")
    conn = await asyncpg.connect(postgres_dsn())
    try:
        if status:
            rows = await conn.fetch(
                "SELECT id::text AS id, name, kind, version, status "
                "FROM dsp_ai.enhancements WHERE status = $1 ORDER BY updated_at DESC",
                status,
            )
        else:
            rows = await conn.fetch(
                "SELECT id::text AS id, name, kind, version, status FROM dsp_ai.enhancements ORDER BY updated_at DESC"
            )
    finally:
        await conn.close()
    if not rows:
        return _text("No enhancements found.")
    lines = [f"Found {len(rows)} enhancement(s):"]
    for r in rows:
        lines.append(f"- [{r['status']}] {r['name']} (v{r['version']}, {r['kind']}) — id={r['id']}")
    return _text("\n".join(lines))


async def get_enhancement(args: dict) -> dict:
    enh_id = args.get("enhancement_id", "")
    if not enh_id:
        return _err("enhancement_id is required")
    conn = await asyncpg.connect(postgres_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT id::text AS id, name, kind, version, status, config FROM dsp_ai.enhancements WHERE id = $1::uuid",
            enh_id,
        )
    finally:
        await conn.close()
    if row is None:
        return _err(f"Enhancement not found: {enh_id}")
    cfg = row["config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    summary = (
        f"# {row['name']} (v{row['version']}, {row['status']}, {row['kind']})\n\n"
        f"## Config (JSON)\n```json\n{json.dumps(cfg, indent=2)}\n```"
    )
    return _text(summary)


async def create_enhancement(args: dict) -> dict:
    name = args.get("name", "")
    kind = args.get("kind", "")
    config = args.get("config") or {}
    author = args.get("author", "mcp")
    if not name or not kind:
        return _err("name and kind are required")
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except Exception:
            return _err("config must be a JSON object or stringified JSON")
    new_id = str(uuid.uuid4())
    conn = await asyncpg.connect(postgres_dsn())
    try:
        await conn.execute(
            "INSERT INTO dsp_ai.enhancements (id, name, kind, config, author) VALUES ($1::uuid, $2, $3, $4::jsonb, $5)",
            new_id,
            name,
            kind,
            json.dumps(config),
            author,
        )
    finally:
        await conn.close()
    return _text(f"Created enhancement {new_id} (status=draft).")


async def update_enhancement(args: dict) -> dict:
    enh_id = args.get("enhancement_id", "")
    patch = args.get("patch") or {}
    if not enh_id:
        return _err("enhancement_id is required")
    if isinstance(patch, str):
        try:
            patch = json.loads(patch)
        except Exception:
            return _err("patch must be a JSON object or stringified JSON")
    conn = await asyncpg.connect(postgres_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT config FROM dsp_ai.enhancements WHERE id = $1::uuid",
            enh_id,
        )
        if row is None:
            return _err(f"Enhancement not found: {enh_id}")
        current = row["config"]
        if isinstance(current, str):
            current = json.loads(current)
        merged = {**current, **patch}
        await conn.execute(
            "UPDATE dsp_ai.enhancements SET config = $1::jsonb, updated_at = NOW() WHERE id = $2::uuid",
            json.dumps(merged),
            enh_id,
        )
    finally:
        await conn.close()
    return _text(f"Updated enhancement {enh_id} (merged {len(patch)} key(s)).")


async def preview(args: dict) -> dict:
    enh_id = args.get("enhancement_id", "")
    user = args.get("user", "mcp")
    context_hints = args.get("context_hints") or {}
    if not enh_id:
        return _err("enhancement_id is required")
    base = os.environ.get("DSPAI_URL", "http://dsp-ai:8000")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base}/v1/enhance/{enh_id}",
                json={"user": user, "context_hints": context_hints, "preview": True},
            )
    except Exception as e:
        return _err(f"dsp-ai unreachable: {e}")
    if resp.status_code != 200:
        return _err(f"preview failed ({resp.status_code}): {resp.text[:200]}")
    return _text(f"Preview result:\n```json\n{json.dumps(resp.json(), indent=2)[:4000]}\n```")


async def publish(args: dict) -> dict:
    enh_id = args.get("enhancement_id", "")
    if not enh_id:
        return _err("enhancement_id is required")
    conn = await asyncpg.connect(postgres_dsn())
    try:
        row = await conn.fetchrow(
            "UPDATE dsp_ai.enhancements SET status='published', updated_at=NOW() "
            "WHERE id = $1::uuid RETURNING id::text AS id",
            enh_id,
        )
    finally:
        await conn.close()
    if row is None:
        return _err(f"Enhancement not found: {enh_id}")
    try:
        from spec2sphere.dsp_ai.events import emit

        await emit("enhancement_published", {"id": enh_id})
    except Exception:
        pass  # best-effort
    return _text(f"Published {enh_id}.")


async def query_brain(args: dict) -> dict:
    cypher = args.get("cypher", "")
    params = args.get("parameters") or {}
    if not cypher.strip():
        return _err("cypher is required")
    first = cypher.strip().split()[0].upper()
    if first not in {"MATCH", "RETURN", "CALL", "WITH", "UNWIND", "OPTIONAL"}:
        return _err(f"read-only Cypher required; got {first}")
    # Reject write verbs anywhere in the query
    for verb in ("CREATE", "DELETE", "DETACH", "SET", "MERGE", "REMOVE", "DROP"):
        if (" " + verb + " ") in (" " + cypher.upper() + " "):
            return _err(f"write verb '{verb}' not permitted")
    try:
        from spec2sphere.dsp_ai.brain.client import run as brain_run

        rows = await brain_run(cypher, **params)
    except Exception as e:
        return _err(f"brain query failed: {e}")
    return _text(f"{len(rows)} row(s):\n```json\n{json.dumps(rows, indent=2, default=str)[:4000]}\n```")


async def generation_log(args: dict) -> dict:
    enh_id: str | None = args.get("enhancement_id")
    user_id: str | None = args.get("user_id")
    limit = int(args.get("limit", 50))
    sql = (
        "SELECT id::text AS id, enhancement_id::text AS enhancement_id, user_id, "
        "model, quality_level, latency_ms, cost_usd, error_kind, preview, created_at "
        "FROM dsp_ai.generations"
    )
    params: list[Any] = []
    filters: list[str] = []
    if enh_id:
        params.append(enh_id)
        filters.append(f"enhancement_id = ${len(params)}::uuid")
    if user_id:
        params.append(user_id)
        filters.append(f"user_id = ${len(params)}")
    if filters:
        sql += " WHERE " + " AND ".join(filters)
    sql += f" ORDER BY created_at DESC LIMIT {max(1, min(limit, 200))}"
    conn = await asyncpg.connect(postgres_dsn())
    try:
        rows = await conn.fetch(sql, *params)
    finally:
        await conn.close()
    if not rows:
        return _text("No generations found.")
    lines = [f"{len(rows)} generation(s):"]
    for r in rows:
        lines.append(
            f"- {r['created_at'].isoformat()}  {r['model']}  {r['latency_ms']}ms  "
            f"user={r['user_id'] or '-'}  preview={r['preview']}  err={r['error_kind'] or '-'}"
        )
    return _text("\n".join(lines))
