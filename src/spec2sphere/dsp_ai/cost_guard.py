"""Per-enhancement monthly cost cap + global cap + auto-pause.

Session B's ObservedLLMProvider populates ``dsp_ai.generations.cost_usd``
for every LLM call (engine + agents + migration + standards + knowledge).
The per-enhancement cap only covers rows where ``enhancement_id`` is set
(i.e. actual DSP-AI enhancement runs). The global cap covers the lot.

Env:
  COST_GUARD_DEFAULT_CAP_USD — default 25.0
  COST_GUARD_GLOBAL_CAP_USD  — default 100.0 (0 = disabled)
  COST_GUARD_ENFORCED        — default "true"; "false" = log-only
"""

from __future__ import annotations

import json
import logging
import os

from .config import Enhancement
from .db import current_customer, get_conn
from .events import emit

logger = logging.getLogger(__name__)


class CostExceeded(Exception):
    """Raised when a projected LLM call would breach the monthly cap."""

    def __init__(
        self,
        scope: str,
        enhancement_id: str | None,
        month_total: float,
        projected: float,
        cap: float,
    ):
        self.scope = scope
        self.enhancement_id = enhancement_id
        self.month_total = month_total
        self.projected = projected
        self.cap = cap
        super().__init__(
            f"cost_cap breached [{scope}] enhancement={enhancement_id} "
            f"month_total={month_total:.4f} + projected={projected:.4f} > cap={cap:.4f}"
        )


def _default_cap() -> float:
    return float(os.environ.get("COST_GUARD_DEFAULT_CAP_USD", "25.0"))


def _global_cap() -> float:
    return float(os.environ.get("COST_GUARD_GLOBAL_CAP_USD", "100.0"))


def _enforced() -> bool:
    return os.environ.get("COST_GUARD_ENFORCED", "true").lower() == "true"


_MODEL_COST_PER_1K_TOKENS: dict[str, float] = {
    "gpt-4o": 0.005,
    "gpt-4o-mini": 0.00015,
    "claude-opus-4-7": 0.015,
    "claude-sonnet-4-6": 0.003,
    "claude-haiku-4-5": 0.0008,
}


def estimate_cost(model: str, tokens_in: int, tokens_out: int = 0) -> float:
    """Best-effort cost estimate. Unknown model → 0 (on-prem / free)."""
    rate = _MODEL_COST_PER_1K_TOKENS.get((model or "").lower(), 0.0)
    return rate * (tokens_in + tokens_out) / 1000.0


async def month_total_for_enhancement(enhancement_id: str) -> float:
    async with get_conn() as conn:
        v = await conn.fetchval(
            """
            SELECT coalesce(sum(cost_usd), 0)::float
              FROM dsp_ai.generations
             WHERE enhancement_id = $1::uuid
               AND created_at > date_trunc('month', NOW())
            """,
            enhancement_id,
        )
    return float(v or 0.0)


async def month_total_global() -> float:
    async with get_conn() as conn:
        v = await conn.fetchval(
            """
            SELECT coalesce(sum(cost_usd), 0)::float
              FROM dsp_ai.generations
             WHERE created_at > date_trunc('month', NOW())
            """,
        )
    return float(v or 0.0)


async def check_before_call(enh: Enhancement | None, projected_cost_usd: float) -> None:
    """Raise CostExceeded if projection would breach a cap. No-op if disabled."""
    # Global check always runs if cap > 0
    gcap = _global_cap()
    if gcap > 0:
        gtotal = await month_total_global()
        if gtotal + projected_cost_usd > gcap:
            if _enforced():
                raise CostExceeded("global", None, gtotal, projected_cost_usd, gcap)
            logger.warning(
                "cost_guard (log-only): global projected breach %.4f + %.4f > %.4f",
                gtotal,
                projected_cost_usd,
                gcap,
            )

    if enh is None:
        return
    cap = _extract_cap(enh) or _default_cap()
    total = await month_total_for_enhancement(enh.id)
    if total + projected_cost_usd > cap:
        if _enforced():
            await _pause(enh.id, total, cap)
            raise CostExceeded("enhancement", enh.id, total, projected_cost_usd, cap)
        logger.warning(
            "cost_guard (log-only): enhancement=%s breach %.4f + %.4f > %.4f",
            enh.id,
            total,
            projected_cost_usd,
            cap,
        )


def _extract_cap(enh: Enhancement) -> float | None:
    """Per-enhancement cap lives under config.cost_cap_usd (optional)."""
    cfg = getattr(enh, "config", None)
    if cfg is None:
        return None
    # Pydantic v2 model — access as attr; fall back to dict dump
    v = getattr(cfg, "cost_cap_usd", None)
    if v is None and hasattr(cfg, "model_dump"):
        v = cfg.model_dump().get("cost_cap_usd")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


async def _pause(enhancement_id: str, month_total: float, cap: float) -> None:
    async with get_conn() as conn:
        await conn.execute(
            "UPDATE dsp_ai.enhancements SET status = 'paused', updated_at = NOW() WHERE id = $1::uuid",
            enhancement_id,
        )
        await conn.execute(
            "INSERT INTO dsp_ai.studio_audit (action, enhancement_id, author, after, customer) "
            "VALUES ($1, $2::uuid, $3, $4::jsonb, $5)",
            "auto_pause",
            enhancement_id,
            "cost_guard",
            json.dumps({"month_total": month_total, "cap": cap, "reason": "cost_cap"}),
            current_customer(),
        )
    try:
        await emit("enhancement_paused", {"id": enhancement_id, "reason": "cost_guard"})
    except Exception:
        logger.exception("failed to emit enhancement_paused NOTIFY")
