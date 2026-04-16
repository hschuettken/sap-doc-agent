"""Tests for sac_factory/style_learning.py — Session 6."""

from __future__ import annotations


from spec2sphere.sac_factory.style_learning import (
    StylePreference,
    get_style_profile,
    update_preference,
)


def test_update_preference_creates_new():
    """Empty dict + approve layout:exec_overview → score > 0, evidence_count=1."""
    prefs: dict[str, StylePreference] = {}
    prefs = update_preference(prefs, "layout", "exec_overview", approved=True)

    assert "layout:exec_overview" in prefs
    pref = prefs["layout:exec_overview"]
    assert pref.score > 0
    assert pref.evidence_count == 1
    assert pref.preference_type == "layout"
    assert pref.preference_key == "exec_overview"


def test_update_preference_increments():
    """Existing preference score=1.0/evidence=2, approve → evidence=3, score > 1.0."""
    prefs: dict[str, StylePreference] = {
        "layout:exec_overview": StylePreference(
            preference_type="layout",
            preference_key="exec_overview",
            score=1.0,
            evidence_count=2,
        )
    }
    prefs = update_preference(prefs, "layout", "exec_overview", approved=True)

    pref = prefs["layout:exec_overview"]
    assert pref.evidence_count == 3
    assert pref.score > 1.0


def test_update_preference_negative():
    """Existing score=1.0, reject → score < 1.0."""
    prefs: dict[str, StylePreference] = {
        "chart:bar": StylePreference(
            preference_type="chart",
            preference_key="bar",
            score=1.0,
            evidence_count=1,
        )
    }
    prefs = update_preference(prefs, "chart", "bar", approved=False)

    pref = prefs["chart:bar"]
    assert pref.score < 1.0
    assert pref.evidence_count == 2


def test_get_style_profile_empty():
    """Empty prefs dict → all profile lists are empty."""
    profile = get_style_profile({})

    assert profile["preferred_layouts"] == []
    assert profile["preferred_charts"] == []


def test_get_style_profile_ranked():
    """Profile keys sorted by score descending; only score > 0 included."""
    prefs: dict[str, StylePreference] = {
        "layout:exec_overview": StylePreference(
            preference_type="layout",
            preference_key="exec_overview",
            score=3.0,
            evidence_count=3,
        ),
        "layout:table_first": StylePreference(
            preference_type="layout",
            preference_key="table_first",
            score=1.0,
            evidence_count=1,
        ),
        "chart:bar": StylePreference(
            preference_type="chart",
            preference_key="bar",
            score=2.0,
            evidence_count=2,
        ),
        "layout:rejected_layout": StylePreference(
            preference_type="layout",
            preference_key="rejected_layout",
            score=-0.5,
            evidence_count=1,
        ),
    }
    profile = get_style_profile(prefs)

    assert profile["preferred_layouts"][0] == "exec_overview", "Highest score layout should be first"
    assert "table_first" in profile["preferred_layouts"]
    assert "rejected_layout" not in profile["preferred_layouts"], "Negative score should be excluded"
    assert profile["preferred_charts"][0] == "bar"
