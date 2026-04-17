"""Stage 7: write to dsp_ai.* (batch) or return JSON (live)."""

from __future__ import annotations

import json

import asyncpg

from ..config import Enhancement, EnhancementMode, RenderHint
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
            if enh.config.render_hint in (RenderHint.NARRATIVE_TEXT, RenderHint.BRIEF, RenderHint.CALLOUT):
                await _write_briefing(conn, enh, user_id or "_global", context_key or "default", shaped)
            # ranked_list + item_enrich writes added in Session B
            await emit(
                "briefing_generated",
                {"enhancement_id": enh.id, "user_id": user_id, "context_key": context_key},
            )
        return shaped
    finally:
        await conn.close()
