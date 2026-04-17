"""7-stage engine orchestrator."""

from __future__ import annotations

import datetime as dt
from typing import Any

from .config import Enhancement, EnhancementMode
from .stages.adaptive_rules import apply as apply_rules
from .stages.compose_prompt import compose
from .stages.dispatch import dispatch
from .stages.gather import gather
from .stages.resolve import resolve
from .stages.run_llm import run as run_llm
from .stages.shape_output import shape


async def run_engine(
    enhancement_id: str,
    *,
    user_id: str | None = None,
    context_hints: dict[str, Any] | None = None,
    context_key: str | None = None,
    mode_override: EnhancementMode | None = None,
    preview: bool = False,
) -> dict:
    enh: Enhancement = await resolve(enhancement_id)
    mode = mode_override or enh.config.mode
    ctx = await gather(enh, user_id, context_hints or {})
    ctx = apply_rules(enh, ctx, user_id, dt.datetime.utcnow())
    prompt = compose(enh, ctx, user_id)
    raw, meta = await run_llm(enh, prompt)
    shaped = shape(enh, raw, meta, ctx, prompt)
    return await dispatch(enh, shaped, mode=mode, user_id=user_id, context_key=context_key, preview=preview)
