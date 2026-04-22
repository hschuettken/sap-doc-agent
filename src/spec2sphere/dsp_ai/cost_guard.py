"""Per-enhancement monthly cost cap with auto-pause on overrun.

Per-enhancement cap only applies to rows with non-NULL enhancement_id.
Global monthly total (COST_GUARD_GLOBAL_CAP_USD) covers agent + migration +
standards + knowledge LLM calls (enhancement_id = NULL rows).

Usage in engine:
    from .cost_guard import check_and_account, CostExceeded
    try:
        await check_and_account(enhancement_id, projected_cost_usd)
    except CostExceeded:
        return {"error_kind": "cost_cap", "content": None}
"""

from __future__ import annotations

import os

import asyncpg

from .settings import postgres_dsn

DEFAULT_CAP_USD = float(os.environ.get("COST_GUARD_DEFAULT_CAP_USD", "25.0"))
GLOBAL_CAP_USD = float(os.environ.get("COST_GUARD_GLOBAL_CAP_USD", "100.0"))


class CostExceeded(Exception):
    """Raised when an enhancement would breach its monthly cap."""


async def month_total_for(enhancement_id: str) -> tuple[float, float]:
    """Return (month_total_usd, cap_usd) for a given enhancement this calendar month."""
    conn = await asyncpg.connect(postgres_dsn())
    try:
        row = await conn.fetchrow(
            """
            SELECT
                coalesce(sum(g.cost_usd), 0) AS month_total,
                max((e.config->>'cost_cap_usd')::float) AS cap
            FROM dsp_ai.generations g
            JOIN dsp_ai.enhancements e ON e.id = g.enhancement_id
            WHERE g.enhancement_id = $1::uuid
              AND g.created_at >= date_trunc('month', NOW())
            """,
            enhancement_id,
        )
    finally:
        await conn.close()
    month_total = float(row["month_total"] or 0)
    cap = float(row["cap"] or DEFAULT_CAP_USD)
    return month_total, cap


async def check_and_account(enhancement_id: str, projected_cost_usd: float) -> None:
    """Raise CostExceeded (and auto-pause) if adding *projected_cost_usd* would breach cap.

    Called *before* the LLM call so we never pay for a call that would be over cap.
    """
    month_total, cap = await month_total_for(enhancement_id)
    if month_total + projected_cost_usd > cap:
        await _pause(enhancement_id, month_total, cap)
        raise CostExceeded(
            f"enhancement {enhancement_id}: {month_total + projected_cost_usd:.4f} USD "
            f"would exceed cap {cap:.2f} USD (month so far: {month_total:.4f} USD)"
        )


async def _pause(enhancement_id: str, total: float, cap: float) -> None:
    """Mark the enhancement as paused and write an audit row."""
    conn = await asyncpg.connect(postgres_dsn())
    try:
        await conn.execute(
            "UPDATE dsp_ai.enhancements SET status = 'paused', updated_at = NOW() "
            "WHERE id = $1::uuid",
            enhancement_id,
        )
        await conn.execute(
            "INSERT INTO dsp_ai.studio_audit (action, enhancement_id, author, after) "
            "VALUES ($1, $2::uuid, 'cost_guard', $3::jsonb)",
            "auto_pause",
            enhancement_id,
            f'{{"month_total": {total}, "cap": {cap}}}',
        )
    finally:
        await conn.close()

    try:
        from .events import emit  # avoid circular at module level
        await emit("enhancement_paused", {"id": enhancement_id, "reason": "cost_guard"})
    except Exception:
        pass


async def global_month_total() -> float:
    """Sum of all LLM costs this calendar month (including null-enhancement rows)."""
    conn = await asyncpg.connect(postgres_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT coalesce(sum(cost_usd), 0) AS total "
            "FROM dsp_ai.generations "
            "WHERE created_at >= date_trunc('month', NOW())"
        )
    finally:
        await conn.close()
    return float(row["total"] or 0)
