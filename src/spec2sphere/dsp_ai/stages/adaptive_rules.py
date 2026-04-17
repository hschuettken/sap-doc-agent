"""Stage 3: pure-Python filter/weight/re-rank on gathered context.

Deterministic, no LLM. Tests should pin behavior.
"""

from __future__ import annotations

import datetime as dt

from ..config import Enhancement
from .gather import GatheredContext


def apply(enh: Enhancement, ctx: GatheredContext, user_id: str | None, now: dt.datetime) -> GatheredContext:
    rules = enh.config.adaptive_rules
    if rules.per_delta and user_id and ctx.user_state.get("last_visited_at"):
        lv = ctx.user_state["last_visited_at"]
        # Keep brain nodes newer than last_visited_at; filter out stale ones
        ctx.brain_nodes = [n for n in ctx.brain_nodes if not (isinstance(n, dict) and n.get("ts") and n["ts"] < lv)]
    if rules.per_time:
        hour = now.hour
        ctx.user_state["time_bucket"] = (
            "morning"
            if 5 <= hour < 12
            else "afternoon"
            if 12 <= hour < 17
            else "evening"
            if 17 <= hour < 22
            else "night"
        )
    return ctx
