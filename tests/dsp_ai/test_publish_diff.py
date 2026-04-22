"""Unit tests for publish_diff.py — pure logic (no DB needed)."""

from __future__ import annotations

import pytest

from spec2sphere.dsp_ai.publish_diff import (
    _config_delta,
    _humanize,
    _is_breaking,
)


class TestConfigDelta:
    def test_no_changes(self):
        cfg = {"a": 1, "b": "hello"}
        assert _config_delta(cfg, cfg) == {}

    def test_added_key(self):
        delta = _config_delta({}, {"new_key": "val"})
        assert "new_key" in delta
        assert delta["new_key"]["from"] is None
        assert delta["new_key"]["to"] == "val"

    def test_removed_key(self):
        delta = _config_delta({"old_key": "val"}, {})
        assert "old_key" in delta
        assert delta["old_key"]["from"] == "val"
        assert delta["old_key"]["to"] is None

    def test_changed_value(self):
        delta = _config_delta({"prompt_template": "old"}, {"prompt_template": "new"})
        assert delta["prompt_template"] == {"from": "old", "to": "new"}

    def test_unchanged_nested_dict(self):
        cfg = {"bindings": {"data": {"dsp_query": "SELECT 1"}}}
        assert _config_delta(cfg, cfg) == {}


class TestIsBreaking:
    def test_render_hint_change_is_breaking(self):
        assert _is_breaking({"render_hint": {"from": "brief", "to": "ranked_list"}})

    def test_output_schema_change_is_breaking(self):
        assert _is_breaking({"output_schema": {"from": None, "to": {}}})

    def test_kind_change_is_breaking(self):
        assert _is_breaking({"kind": {"from": "briefing", "to": "action"}})

    def test_mode_change_is_breaking(self):
        assert _is_breaking({"mode": {"from": "batch", "to": "live"}})

    def test_prompt_template_change_not_breaking(self):
        assert not _is_breaking({"prompt_template": {"from": "old", "to": "new"}})

    def test_bindings_change_not_breaking(self):
        assert not _is_breaking({"bindings": {"from": {}, "to": {"data": {}}}})

    def test_empty_changes_not_breaking(self):
        assert not _is_breaking({})


class TestHumanize:
    def test_prompt_template_message(self):
        msgs = _humanize({"prompt_template": {"from": "a", "to": "b"}})
        assert any("prompt template" in m.lower() for m in msgs)

    def test_render_hint_message(self):
        msgs = _humanize({"render_hint": {"from": "brief", "to": "ranked_list"}})
        assert any("render hint" in m.lower() for m in msgs)

    def test_output_schema_message(self):
        msgs = _humanize({"output_schema": {"from": None, "to": {}}})
        assert any("schema" in m.lower() for m in msgs)

    def test_no_changes_returns_safe_message(self):
        msgs = _humanize({})
        assert msgs  # non-empty
        assert any("no significant" in m.lower() for m in msgs)

    def test_bindings_message(self):
        msgs = _humanize({"bindings": {"from": {}, "to": {}}})
        assert any("binding" in m.lower() for m in msgs)
