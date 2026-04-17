"""Stage 7: write to dsp_ai.* (batch) or return JSON (live)."""

from __future__ import annotations

import json

import asyncpg

from ..config import Enhancement, EnhancementKind, EnhancementMode, RenderHint  # noqa: F401
from ..events import emit
from ..settings import postgres_dsn


async def _insert_generation(
    conn: asyncpg.Connection,
    enh: Enhancement,
    user_id: str | None,
    context_key: str | None,
    shaped: dict,
    preview: bool,
) -> None:
    prov = shaped["provenance"]
    await conn.execute(
        """
        INSERT INTO dsp_ai.generations
            (id, enhancement_id, user_id, context_key, prompt_hash, input_ids,
             model, quality_level, latency_ms, tokens_in, tokens_out, cost_usd,
             cached, quality_warnings, error_kind, preview)
        VALUES ($1::uuid, $2::uuid, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, $12, $13, $14::jsonb, $15, $16)
        """,
        shaped["generation_id"],
        enh.id,
        user_id,
        context_key,
        prov["prompt_hash"],
        json.dumps(prov.get("input_ids", [])),
        prov.get("model") or "unknown",
        prov.get("quality_level") or "Q3",
        prov.get("latency_ms") or 0,
        prov.get("tokens_in"),
        prov.get("tokens_out"),
        prov.get("cost_usd"),
        False,
        json.dumps(shaped.get("quality_warnings", [])),
        shaped.get("error_kind"),
        preview,
    )


async def _write_briefing(
    conn: asyncpg.Connection,
    enh: Enhancement,
    user_id: str,
    context_key: str,
    shaped: dict,
) -> None:
    c = shaped["content"] if isinstance(shaped["content"], dict) else {"narrative_text": str(shaped["content"])}
    await conn.execute(
        """
        INSERT INTO dsp_ai.briefings
            (enhancement_id, user_id, context_key, generated_at, narrative_text,
             key_points, suggested_actions, render_hint, generation_id)
        VALUES ($1::uuid, $2, $3, NOW(), $4, $5::jsonb, $6::jsonb, $7, $8::uuid)
        ON CONFLICT (enhancement_id, user_id, context_key) DO UPDATE SET
            generated_at = EXCLUDED.generated_at,
            narrative_text = EXCLUDED.narrative_text,
            key_points = EXCLUDED.key_points,
            suggested_actions = EXCLUDED.suggested_actions,
            generation_id = EXCLUDED.generation_id
        """,
        enh.id,
        user_id,
        context_key,
        c.get("narrative_text", ""),
        json.dumps(c.get("key_points", [])),
        json.dumps(c.get("suggested_actions", [])),
        enh.config.render_hint.value,
        shaped["generation_id"],
    )


async def _write_ranking(
    conn: asyncpg.Connection,
    enh: Enhancement,
    user_id: str,
    context_key: str,
    shaped: dict,
) -> None:
    content = shaped.get("content")
    items = content.get("items", []) if isinstance(content, dict) else []
    await conn.execute(
        "DELETE FROM dsp_ai.rankings WHERE enhancement_id=$1::uuid AND user_id=$2 AND context_key=$3",
        enh.id,
        user_id,
        context_key,
    )
    for i, item in enumerate(items):
        await conn.execute(
            """
            INSERT INTO dsp_ai.rankings
                (enhancement_id, user_id, context_key, item_id, rank, score, reason,
                 generated_at, generation_id)
            VALUES ($1::uuid, $2, $3, $4, $5, $6, $7, NOW(), $8::uuid)
            """,
            enh.id,
            user_id,
            context_key,
            str(item["item_id"]),
            i + 1,
            float(item.get("score", 0.0)),
            item.get("reason"),
            shaped["generation_id"],
        )


async def _write_item_enhancement(
    conn: asyncpg.Connection,
    enh: Enhancement,
    user_id: str | None,
    shaped: dict,
) -> None:
    content = shaped.get("content")
    enrichments = content.get("enrichments", []) if isinstance(content, dict) else []
    uid = user_id or "_global"
    for e in enrichments:
        await conn.execute(
            """
            INSERT INTO dsp_ai.item_enhancements
                (object_type, object_id, user_id, title_suggested, description_suggested,
                 tags, kpi_suggestions, generated_at, enhancement_id, generation_id)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, NOW(), $8::uuid, $9::uuid)
            ON CONFLICT (object_type, object_id, user_id) DO UPDATE SET
                title_suggested = EXCLUDED.title_suggested,
                description_suggested = EXCLUDED.description_suggested,
                tags = EXCLUDED.tags,
                kpi_suggestions = EXCLUDED.kpi_suggestions,
                generated_at = EXCLUDED.generated_at,
                enhancement_id = EXCLUDED.enhancement_id,
                generation_id = EXCLUDED.generation_id
            """,
            e["object_type"],
            e["object_id"],
            uid,
            e.get("title"),
            e.get("description"),
            json.dumps(e.get("tags", [])),
            json.dumps(e.get("kpi_suggestions", [])),
            enh.id,
            shaped["generation_id"],
        )


async def dispatch(
    enh: Enhancement,
    shaped: dict,
    *,
    mode: EnhancementMode,
    user_id: str | None,
    context_key: str | None,
    preview: bool = False,
) -> dict:
    conn = await asyncpg.connect(postgres_dsn())
    try:
        await _insert_generation(conn, enh, user_id, context_key, shaped, preview)
        # Skip write-back when content is missing — preserves the last good
        # briefing for SAC consumers instead of overwriting with empty text.
        has_content = shaped.get("content") is not None and shaped.get("error_kind") is None
        if has_content and mode in (EnhancementMode.BATCH, EnhancementMode.BOTH) and not preview:
            kind = enh.config.kind
            rh = enh.config.render_hint
            if kind == EnhancementKind.ITEM_ENRICH:
                await _write_item_enhancement(conn, enh, user_id, shaped)
            elif rh == RenderHint.RANKED_LIST:
                await _write_ranking(conn, enh, user_id or "_global", context_key or "default", shaped)
            elif rh in (RenderHint.NARRATIVE_TEXT, RenderHint.BRIEF, RenderHint.CALLOUT):
                await _write_briefing(conn, enh, user_id or "_global", context_key or "default", shaped)
            # action (button) + chart: no batch persistence (live-only)
            await emit(
                "briefing_generated",
                {"enhancement_id": enh.id, "user_id": user_id, "context_key": context_key},
            )
        return shaped
    finally:
        await conn.close()
