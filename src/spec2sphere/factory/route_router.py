"""Route Router — selects the best execution route for each artifact deployment.

Routes are scored by learned fitness from past attempts (stored in route_fitness
table) combined with environment-specific safety multipliers.  When no fitness
data exists, sensible defaults are used.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spec2sphere.db import _get_conn
from spec2sphere.tenant.context import ContextEnvelope

# ---------------------------------------------------------------------------
# Route compatibility matrix
# ---------------------------------------------------------------------------

# DSP view artifact types
_DSP_VIEW_TYPES = {
    "relational_view",
    "fact_view",
    "dimension_view",
    "text_view",
    "hierarchy_view",
}

# Routes available per artifact type
_ARTIFACT_ROUTES: dict[str, list[str]] = {
    "relational_view": ["cdp", "api", "csn_import"],
    "fact_view": ["cdp", "api", "csn_import"],
    "dimension_view": ["cdp", "api", "csn_import"],
    "text_view": ["cdp", "api", "csn_import"],
    "hierarchy_view": ["cdp", "api", "csn_import"],
    "story": ["cdp", "click_guide", "manifest", "api"],
    "app": ["cdp", "click_guide", "manifest", "api"],
    "analytic_model": ["cdp", "api", "csn_import", "manifest"],
    "custom_widget": ["cdp", "click_guide"],
}

# Action-level restrictions (override artifact matrix when present)
_ACTION_ROUTES: dict[str, list[str]] = {
    "read": ["api", "cdp"],
    "screenshot": ["cdp"],
}

# Default fitness scores when no learned data exists
_DEFAULT_SCORES: dict[str, float] = {
    "cdp": 0.7,
    "api": 0.6,
    "csn_import": 0.5,
    "click_guide": 0.4,
    "manifest": 0.5,
}

# Production safety multipliers (higher = more preferred in production)
_PRODUCTION_MULTIPLIERS: dict[str, float] = {
    "click_guide": 1.3,
    "api": 1.2,
    "manifest": 1.1,
    "csn_import": 1.0,
    "cdp": 0.8,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RouteDecision:
    """Result of route selection for a single artifact deployment."""

    primary_route: str
    fallback_chain: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    reason: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_supported_routes(artifact_type: str, action: str) -> list[str]:
    """Return the list of routes compatible with this artifact type and action.

    Action restrictions take precedence over the artifact type matrix.
    """
    if action in _ACTION_ROUTES:
        return list(_ACTION_ROUTES[action])

    return list(_ARTIFACT_ROUTES.get(artifact_type, []))


async def select_route(
    ctx: ContextEnvelope,
    artifact_type: str,
    action: str,
    environment: str,
) -> RouteDecision:
    """Select the best route for an artifact deployment.

    1. Determine the compatible routes for this artifact type + action.
    2. Load learned fitness scores from route_fitness for the customer.
    3. Fill missing routes with default scores.
    4. Apply production safety multipliers when environment == "production".
    5. Sort descending — highest score is primary, remainder are fallbacks.
    """
    supported = get_supported_routes(artifact_type, action)
    if not supported:
        return RouteDecision(
            primary_route="api",
            fallback_chain=[],
            scores={},
            reason=f"No supported routes for artifact_type={artifact_type} action={action}; defaulting to api",
        )

    # Load fitness scores from DB
    fitness_map: dict[str, float] = {}
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            """
            SELECT route, fitness_score
            FROM route_fitness
            WHERE customer_id = $1
              AND object_type = $2
              AND action = $3
              AND route = ANY($4::text[])
            """,
            ctx.customer_id,
            artifact_type,
            action,
            supported,
        )
        for row in rows:
            fitness_map[row["route"]] = float(row["fitness_score"])
    finally:
        await conn.close()

    # Build scored dict: DB value takes priority over default
    scores: dict[str, float] = {}
    for route in supported:
        base = fitness_map.get(route, _DEFAULT_SCORES.get(route, 0.5))
        if environment == "production":
            multiplier = _PRODUCTION_MULTIPLIERS.get(route, 1.0)
            scores[route] = base * multiplier
        else:
            scores[route] = base

    # Sort routes by score descending
    ranked = sorted(scores, key=lambda r: scores[r], reverse=True)
    primary = ranked[0]
    fallbacks = ranked[1:]

    reason = (
        f"Selected {primary!r} (score={scores[primary]:.3f}) from {len(supported)} compatible routes "
        f"for {artifact_type}/{action} in {environment}"
    )

    return RouteDecision(
        primary_route=primary,
        fallback_chain=fallbacks,
        scores=scores,
        reason=reason,
    )


async def update_route_fitness(
    ctx: ContextEnvelope,
    artifact_type: str,
    action: str,
    route: str,
    success: bool,
    duration_seconds: float,
    failure_reason: str = "",
) -> None:
    """Update (or insert) fitness learning data for a route attempt.

    Uses an EMA with alpha=0.3 for duration smoothing.
    fitness_score = successes / attempts (simple success rate).
    """
    alpha = 0.3

    conn = await _get_conn()
    try:
        existing = await conn.fetchrow(
            """
            SELECT id, attempts, successes, avg_duration_seconds
            FROM route_fitness
            WHERE customer_id = $1
              AND object_type = $2
              AND action = $3
              AND route = $4
            """,
            ctx.customer_id,
            artifact_type,
            action,
            route,
        )

        if existing:
            new_attempts = existing["attempts"] + 1
            new_successes = existing["successes"] + (1 if success else 0)
            old_duration = existing["avg_duration_seconds"] or duration_seconds
            new_duration = alpha * duration_seconds + (1 - alpha) * old_duration
            new_fitness = new_successes / new_attempts

            await conn.execute(
                """
                UPDATE route_fitness
                SET attempts = $1,
                    successes = $2,
                    avg_duration_seconds = $3,
                    fitness_score = $4,
                    last_failure_reason = CASE WHEN $5 THEN last_failure_reason ELSE $6 END,
                    updated_at = NOW()
                WHERE id = $7
                """,
                new_attempts,
                new_successes,
                new_duration,
                new_fitness,
                success,
                failure_reason,
                existing["id"],
            )
        else:
            # First attempt for this (customer, artifact_type, action, route) combination
            fitness = 1.0 if success else 0.0
            await conn.execute(
                """
                INSERT INTO route_fitness
                    (customer_id, platform, object_type, action, route,
                     attempts, successes, avg_duration_seconds, fitness_score,
                     last_failure_reason, updated_at)
                VALUES ($1, $2, $3, $4, $5, 1, $6, $7, $8, $9, NOW())
                """,
                ctx.customer_id,
                "dsp",  # default platform; can be extended per artifact_type
                artifact_type,
                action,
                route,
                1 if success else 0,
                duration_seconds,
                fitness,
                failure_reason if not success else "",
            )
    finally:
        await conn.close()
