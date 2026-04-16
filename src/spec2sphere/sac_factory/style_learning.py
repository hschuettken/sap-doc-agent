"""Customer SAC style preference learning."""

from __future__ import annotations

from dataclasses import dataclass

from spec2sphere.db import _get_conn

_TYPE_TO_PROFILE_KEY: dict[str, str] = {
    "layout": "preferred_layouts",
    "chart": "preferred_charts",
    "density": "preferred_density",
    "title_style": "preferred_title_styles",
}


@dataclass
class StylePreference:
    preference_type: str
    preference_key: str
    score: float
    evidence_count: int


def update_preference(
    prefs: dict[str, "StylePreference"],
    pref_type: str,
    pref_key: str,
    approved: bool,
) -> dict[str, "StylePreference"]:
    """
    Update or create a style preference entry.

    Compound key = f"{pref_type}:{pref_key}".
    New: score=1.0 if approved, -0.5 if not; evidence_count=1.
    Existing: score += 1.0 if approved, += -0.5 if not; evidence_count += 1.
    Returns the updated prefs dict.
    """
    compound_key = f"{pref_type}:{pref_key}"
    delta = 1.0 if approved else -0.5

    if compound_key in prefs:
        existing = prefs[compound_key]
        existing.score += delta
        existing.evidence_count += 1
    else:
        prefs[compound_key] = StylePreference(
            preference_type=pref_type,
            preference_key=pref_key,
            score=delta,
            evidence_count=1,
        )
    return prefs


def get_style_profile(prefs: dict[str, "StylePreference"]) -> dict[str, list[str]]:
    """
    Build a style profile from the current preferences.

    Groups by preference_type, sorts by score descending, only includes score > 0.
    Returns empty lists for missing types.
    """
    buckets: dict[str, list[StylePreference]] = {}
    for pref in prefs.values():
        if pref.score > 0:
            buckets.setdefault(pref.preference_type, []).append(pref)

    profile: dict[str, list[str]] = {}
    for pref_type, profile_key in _TYPE_TO_PROFILE_KEY.items():
        sorted_prefs = sorted(buckets.get(pref_type, []), key=lambda p: p.score, reverse=True)
        profile[profile_key] = [p.preference_key for p in sorted_prefs]
    return profile


async def save_preferences(customer_id: str, prefs: dict[str, "StylePreference"]) -> None:
    """UPSERT style preferences into style_preferences table."""
    conn = await _get_conn()
    try:
        for pref in prefs.values():
            await conn.execute(
                """
                INSERT INTO style_preferences
                    (customer_id, preference_type, preference_key, score, evidence_count)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (customer_id, preference_type, preference_key)
                DO UPDATE SET score = EXCLUDED.score, evidence_count = EXCLUDED.evidence_count
                """,
                customer_id,
                pref.preference_type,
                pref.preference_key,
                pref.score,
                pref.evidence_count,
            )
    finally:
        await conn.close()


async def load_preferences(customer_id: str) -> dict[str, "StylePreference"]:
    """Load style preferences from DB, return as compound-keyed dict."""
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT preference_type, preference_key, score, evidence_count "
            "FROM style_preferences WHERE customer_id = $1",
            customer_id,
        )
        result: dict[str, StylePreference] = {}
        for row in rows:
            compound_key = f"{row['preference_type']}:{row['preference_key']}"
            result[compound_key] = StylePreference(
                preference_type=row["preference_type"],
                preference_key=row["preference_key"],
                score=row["score"],
                evidence_count=row["evidence_count"],
            )
        return result
    finally:
        await conn.close()
