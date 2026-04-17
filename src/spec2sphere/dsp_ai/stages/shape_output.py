"""Stage 6: normalize output and attach provenance."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from ..config import Enhancement
from .gather import GatheredContext


def shape(enh: Enhancement, raw_output: Any, meta: dict, ctx: GatheredContext, prompt: str) -> dict:
    gen_id = str(uuid.uuid4())
    prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
    input_ids = [n.get("id") for n in ctx.brain_nodes if isinstance(n, dict) and n.get("id")]
    return {
        "generation_id": gen_id,
        "enhancement_id": enh.id,
        "render_hint": enh.config.render_hint.value,
        "content": raw_output,
        "quality_warnings": ctx.quality_warnings,
        "provenance": {
            "prompt_hash": prompt_hash,
            "model": meta.get("model"),
            "quality_level": meta.get("quality_level"),
            "latency_ms": meta.get("latency_ms"),
            "tokens_in": meta.get("tokens_in"),
            "tokens_out": meta.get("tokens_out"),
            "cost_usd": meta.get("cost_usd"),
            "input_ids": input_ids,
        },
    }
