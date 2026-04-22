"""7-stage engine orchestrator."""

from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

from .config import Enhancement, EnhancementMode
from .cost_guard import CostExceeded, check_and_account
from .stages.adaptive_rules import apply as apply_rules
from .stages.compose_prompt import compose
from .stages.dispatch import dispatch
from .stages.gather import gather
from .stages.resolve import resolve
from .stages.run_llm import run as run_llm
from .stages.shape_output import shape

logger = logging.getLogger(__name__)

# Rough per-1k-token cost in USD; used for pre-call estimate only.
# Exact cost is written by ObservedLLMProvider after the call.
_TOKEN_COST_PER_1K = float(os.environ.get("COST_TOKEN_RATE_PER_1K", "0.003"))


def _classify_llm_error(exc: BaseException) -> str:
    """Map a run_llm exception to a stable error_kind tag."""
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return "llm_timeout"
    if "httpstatus" in name or "httperror" in name:
        return "llm_http_error"
    if "jsondecode" in name or "valueerror" in name:
        return "llm_bad_response"
    return "llm_error"


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
    ctx = apply_rules(enh, ctx, user_id, dt.datetime.now(dt.timezone.utc))
    prompt = compose(enh, ctx, user_id)

    # Cost guard: estimate tokens from prompt length and check monthly cap.
    # Skip guard for preview runs (no write-back, not charged to production cap).
    if not preview:
        prompt_token_estimate = max(1, len(prompt) // 4)
        projected = prompt_token_estimate * _TOKEN_COST_PER_1K / 1000
        try:
            await check_and_account(enhancement_id, projected)
        except CostExceeded as exc:
            logger.warning("cost_guard blocked enhancement=%s: %s", enhancement_id, exc)
            return {
                "error_kind": "cost_cap",
                "content": None,
                "quality_warnings": ["cost_cap"],
                "enhancement_id": enhancement_id,
            }

    # Per spec §5: "no single dependency can 500 the engine". LLM outages
    # must degrade to a shaped output with error_kind + quality_warnings,
    # never bubble as an HTTP 500.
    error_kind: str | None = None
    try:
        raw, meta = await run_llm(enh, prompt)
    except Exception as exc:
        error_kind = _classify_llm_error(exc)
        logger.warning(
            "run_llm failed for enhancement=%s user=%s: %s",
            enh.id,
            user_id,
            exc,
            exc_info=True,
        )
        ctx.quality_warnings.append(error_kind)
        raw = None
        meta = {"model": "unavailable", "quality_level": "Q3", "latency_ms": 0}

    shaped = shape(enh, raw, meta, ctx, prompt)
    if error_kind is not None:
        shaped["error_kind"] = error_kind
        shaped["content"] = None
    return await dispatch(enh, shaped, mode=mode, user_id=user_id, context_key=context_key, preview=preview)
