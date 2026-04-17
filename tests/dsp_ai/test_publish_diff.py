"""Publish-diff unit tests — no DB required for pure logic."""

from __future__ import annotations

from spec2sphere.dsp_ai.publish_diff import _config_delta, _humanize, _is_breaking


def test_detects_prompt_change_as_non_breaking():
    a = {"prompt_template": "v1", "render_hint": "narrative_text"}
    b = {"prompt_template": "v2", "render_hint": "narrative_text"}
    changes = _config_delta(a, b)
    assert "prompt_template" in changes
    assert _is_breaking(changes) is False
    msgs = _humanize(changes)
    assert any("prompt template" in m.lower() for m in msgs)


def test_detects_render_hint_as_breaking():
    a = {"render_hint": "narrative_text"}
    b = {"render_hint": "chart"}
    changes = _config_delta(a, b)
    assert _is_breaking(changes) is True
    msgs = _humanize(changes)
    assert any("render hint" in m.lower() for m in msgs)


def test_detects_kind_as_breaking():
    changes = _config_delta({"kind": "narrative"}, {"kind": "ranking"})
    assert _is_breaking(changes) is True


def test_detects_data_binding_as_breaking():
    a = {"data_binding": {"dsp_query": "SELECT 1"}}
    b = {"data_binding": {"dsp_query": "SELECT 2"}}
    assert _is_breaking(_config_delta(a, b)) is True


def test_no_changes_returns_empty():
    assert _config_delta({"a": 1}, {"a": 1}) == {}
    assert _is_breaking({}) is False
    assert _humanize({}) == []


def test_unknown_key_falls_back_generic():
    changes = _config_delta({"foo": 1}, {"foo": 2})
    msgs = _humanize(changes)
    assert "foo changed." in msgs
