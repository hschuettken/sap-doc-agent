"""Per-stage unit tests for the 7-stage DSP-AI engine.

All external dependencies (asyncpg, neo4j, LLM) are mocked — no DB or
network required.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest

from spec2sphere.dsp_ai.config import (
    AdaptiveRules,
    DataBinding,
    Enhancement,
    EnhancementBindings,
    EnhancementConfig,
    EnhancementKind,
    EnhancementMode,
    RenderHint,
    SemanticBinding,
)
from spec2sphere.dsp_ai.stages.gather import GatheredContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_enhancement(
    *,
    enhancement_id: str | None = None,
    prompt_template: str = "Hello {{ user_id }}, data={{ dsp_data|length }}",
    render_hint: RenderHint = RenderHint.BRIEF,
    mode: EnhancementMode = EnhancementMode.BATCH,
    adaptive_rules: AdaptiveRules | None = None,
    semantic: SemanticBinding | None = None,
) -> Enhancement:
    eid = enhancement_id or str(uuid.uuid4())
    return Enhancement(
        id=eid,
        version=1,
        status="draft",
        author="test",
        config=EnhancementConfig(
            name="morning_brief",
            kind=EnhancementKind.BRIEFING,
            mode=mode,
            bindings=EnhancementBindings(
                data=DataBinding(dsp_query="SELECT 1", parameters={}),
                semantic=semantic,
            ),
            adaptive_rules=adaptive_rules or AdaptiveRules(),
            prompt_template=prompt_template,
            render_hint=render_hint,
        ),
    )


def _make_context(
    dsp_data: list | None = None,
    brain_nodes: list | None = None,
    user_state: dict | None = None,
    quality_warnings: list | None = None,
) -> GatheredContext:
    return GatheredContext(
        dsp_data=dsp_data or [],
        brain_nodes=brain_nodes or [],
        external_info=[],
        user_state=user_state or {},
        quality_warnings=quality_warnings or [],
    )


# ---------------------------------------------------------------------------
# Stage 1: Resolve
# ---------------------------------------------------------------------------


class TestResolve:
    @pytest.mark.asyncio
    async def test_resolve_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spec2sphere.dsp_ai.stages import resolve as resolve_mod

        enh_id = str(uuid.uuid4())
        config_dict = {
            "name": "morning_brief",
            "kind": "briefing",
            "mode": "batch",
            "bindings": {
                "data": {"dsp_query": "SELECT 1", "parameters": {}},
            },
            "adaptive_rules": {},
            "prompt_template": "Hello",
            "render_hint": "brief",
        }

        fake_row = {
            "id": enh_id,
            "version": 2,
            "status": "staging",
            "author": "alice",
            "config": json.dumps(config_dict),  # simulate asyncpg returning a str
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)
        mock_conn.close = AsyncMock()

        monkeypatch.setattr("spec2sphere.dsp_ai.db.asyncpg.connect", AsyncMock(return_value=mock_conn))

        enh = await resolve_mod.resolve(enh_id)

        assert enh.id == enh_id
        assert enh.version == 2
        assert enh.status == "staging"
        assert enh.config.name == "morning_brief"

    @pytest.mark.asyncio
    async def test_resolve_not_found_raises_lookup_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spec2sphere.dsp_ai.stages import resolve as resolve_mod

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.close = AsyncMock()

        monkeypatch.setattr("spec2sphere.dsp_ai.db.asyncpg.connect", AsyncMock(return_value=mock_conn))

        with pytest.raises(LookupError, match="not found"):
            await resolve_mod.resolve(str(uuid.uuid4()))

    @pytest.mark.asyncio
    async def test_resolve_dict_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """asyncpg may return JSONB as dict — model_validate should handle it."""
        from spec2sphere.dsp_ai.stages import resolve as resolve_mod

        enh_id = str(uuid.uuid4())
        config_dict = {
            "name": "brief",
            "kind": "briefing",
            "mode": "batch",
            "bindings": {"data": {"dsp_query": "SELECT 1", "parameters": {}}},
            "adaptive_rules": {},
            "prompt_template": "Hi",
            "render_hint": "brief",
        }
        fake_row = {"id": enh_id, "version": 1, "status": "draft", "author": None, "config": config_dict}

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=fake_row)
        mock_conn.close = AsyncMock()

        monkeypatch.setattr("spec2sphere.dsp_ai.db.asyncpg.connect", AsyncMock(return_value=mock_conn))

        enh = await resolve_mod.resolve(enh_id)
        assert enh.config.render_hint == RenderHint.BRIEF


# ---------------------------------------------------------------------------
# Stage 2: Gather
# ---------------------------------------------------------------------------


class TestGather:
    @pytest.mark.asyncio
    async def test_gather_happy_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spec2sphere.dsp_ai.stages import gather as gather_mod

        enh = _make_enhancement()

        monkeypatch.setattr(gather_mod, "_dsp_fetch", AsyncMock(return_value=[{"col": "val"}]))
        monkeypatch.setattr(gather_mod, "_brain_fetch", AsyncMock(return_value=[{"id": "node1"}]))
        monkeypatch.setattr(gather_mod, "_external_fetch", AsyncMock(return_value=[]))
        monkeypatch.setattr(gather_mod, "_user_state", AsyncMock(return_value={"last_visited_at": "2024-01-01"}))

        ctx = await gather_mod.gather(enh, "user42", {})

        assert ctx.dsp_data == [{"col": "val"}]
        assert ctx.brain_nodes == [{"id": "node1"}]
        assert ctx.quality_warnings == []
        assert ctx.user_state["last_visited_at"] == "2024-01-01"

    @pytest.mark.asyncio
    async def test_gather_dsp_failure_adds_warning(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spec2sphere.dsp_ai.stages import gather as gather_mod

        enh = _make_enhancement()

        monkeypatch.setattr(gather_mod, "_dsp_fetch", AsyncMock(side_effect=RuntimeError("DB down")))
        monkeypatch.setattr(gather_mod, "_brain_fetch", AsyncMock(return_value=[]))
        monkeypatch.setattr(gather_mod, "_external_fetch", AsyncMock(return_value=[]))
        monkeypatch.setattr(gather_mod, "_user_state", AsyncMock(return_value={}))

        ctx = await gather_mod.gather(enh, "user42", {})

        assert "dsp_context_missing" in ctx.quality_warnings

    @pytest.mark.asyncio
    async def test_gather_no_semantic_binding_returns_empty_brain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When semantic binding is absent, _brain_fetch returns []."""
        from spec2sphere.dsp_ai.stages import gather as gather_mod

        enh = _make_enhancement(semantic=None)  # no semantic binding

        monkeypatch.setattr(gather_mod, "_dsp_fetch", AsyncMock(return_value=[]))
        monkeypatch.setattr(gather_mod, "_brain_fetch", AsyncMock(return_value=[]))
        monkeypatch.setattr(gather_mod, "_external_fetch", AsyncMock(return_value=[]))

        ctx = await gather_mod.gather(enh, None, {})

        assert ctx.brain_nodes == []
        assert ctx.quality_warnings == []

    @pytest.mark.asyncio
    async def test_gather_no_user_id_skips_user_state(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spec2sphere.dsp_ai.stages import gather as gather_mod

        enh = _make_enhancement()
        user_state_mock = AsyncMock(return_value={"some": "state"})

        monkeypatch.setattr(gather_mod, "_dsp_fetch", AsyncMock(return_value=[]))
        monkeypatch.setattr(gather_mod, "_brain_fetch", AsyncMock(return_value=[]))
        monkeypatch.setattr(gather_mod, "_external_fetch", AsyncMock(return_value=[]))
        monkeypatch.setattr(gather_mod, "_user_state", user_state_mock)

        ctx = await gather_mod.gather(enh, None, {})  # no user_id

        user_state_mock.assert_not_called()
        assert ctx.user_state == {}


# ---------------------------------------------------------------------------
# Stage 3: AdaptiveRules
# ---------------------------------------------------------------------------


class TestAdaptiveRules:
    def test_per_delta_filters_old_nodes(self) -> None:
        from spec2sphere.dsp_ai.stages.adaptive_rules import apply

        last_visited = "2024-06-01T10:00:00"
        enh = _make_enhancement(adaptive_rules=AdaptiveRules(per_delta=True))
        ctx = _make_context(
            brain_nodes=[
                {"id": "old", "ts": "2024-05-01T00:00:00"},  # older than lv → filtered
                {"id": "new", "ts": "2024-07-01T00:00:00"},  # newer → kept
                {"id": "no_ts"},  # no ts → kept
            ],
            user_state={"last_visited_at": last_visited},
        )

        result = apply(enh, ctx, "user1", dt.datetime.utcnow())

        ids = [n.get("id") for n in result.brain_nodes]
        assert "old" not in ids
        assert "new" in ids
        assert "no_ts" in ids

    def test_per_delta_skipped_without_user(self) -> None:
        from spec2sphere.dsp_ai.stages.adaptive_rules import apply

        enh = _make_enhancement(adaptive_rules=AdaptiveRules(per_delta=True))
        ctx = _make_context(
            brain_nodes=[{"id": "node", "ts": "2020-01-01"}],
            user_state={"last_visited_at": "2024-01-01"},
        )

        result = apply(enh, ctx, None, dt.datetime.utcnow())  # no user_id

        # Filtering should NOT happen when user_id is None
        assert len(result.brain_nodes) == 1

    @pytest.mark.parametrize(
        ("hour", "expected_bucket"),
        [
            (8, "morning"),
            (14, "afternoon"),
            (19, "evening"),
            (2, "night"),
        ],
    )
    def test_per_time_sets_time_bucket(self, hour: int, expected_bucket: str) -> None:
        from spec2sphere.dsp_ai.stages.adaptive_rules import apply

        enh = _make_enhancement(adaptive_rules=AdaptiveRules(per_time=True))
        ctx = _make_context()
        now = dt.datetime(2024, 6, 1, hour, 0, 0)

        result = apply(enh, ctx, "user1", now)

        assert result.user_state["time_bucket"] == expected_bucket

    def test_no_rules_leaves_context_unchanged(self) -> None:
        from spec2sphere.dsp_ai.stages.adaptive_rules import apply

        enh = _make_enhancement(adaptive_rules=AdaptiveRules())
        nodes = [{"id": "n1", "ts": "2020-01-01"}]
        ctx = _make_context(brain_nodes=nodes)

        result = apply(enh, ctx, "user1", dt.datetime.utcnow())

        assert result.brain_nodes == nodes


# ---------------------------------------------------------------------------
# Stage 4: ComposePrompt
# ---------------------------------------------------------------------------


class TestComposePrompt:
    def test_compose_renders_template(self) -> None:
        from spec2sphere.dsp_ai.stages.compose_prompt import compose

        enh = _make_enhancement(prompt_template="hello {{ user_id }}, data={{ dsp_data|length }}")
        ctx = _make_context(dsp_data=[{"x": 1}, {"x": 2}])

        result = compose(enh, ctx, "alice")

        assert result == "hello alice, data=2"

    def test_compose_missing_variable_raises(self) -> None:
        from jinja2 import UndefinedError

        from spec2sphere.dsp_ai.stages.compose_prompt import compose

        enh = _make_enhancement(prompt_template="{{ this_does_not_exist }}")
        ctx = _make_context()

        with pytest.raises(UndefinedError):
            compose(enh, ctx, "alice")

    def test_compose_uses_render_hint(self) -> None:
        from spec2sphere.dsp_ai.stages.compose_prompt import compose

        enh = _make_enhancement(
            prompt_template="hint={{ render_hint }}",
            render_hint=RenderHint.NARRATIVE_TEXT,
        )
        ctx = _make_context()

        result = compose(enh, ctx, None)

        assert result == "hint=narrative_text"


# ---------------------------------------------------------------------------
# Stage 6: ShapeOutput
# ---------------------------------------------------------------------------


class TestShapeOutput:
    def test_shape_generates_uuid_generation_id(self) -> None:
        from spec2sphere.dsp_ai.stages.shape_output import shape

        enh = _make_enhancement()
        ctx = _make_context()
        meta: dict[str, Any] = {"model": "gpt-4o", "quality_level": "Q4", "latency_ms": 500}

        result = shape(enh, {"narrative_text": "Morning brief"}, meta, ctx, "some prompt")

        # generation_id must be a valid UUID string
        parsed = uuid.UUID(result["generation_id"])
        assert str(parsed) == result["generation_id"]

    def test_shape_prompt_hash_is_64_hex_chars(self) -> None:
        from spec2sphere.dsp_ai.stages.shape_output import shape

        enh = _make_enhancement()
        ctx = _make_context()
        prompt = "This is my prompt"
        meta: dict[str, Any] = {"model": "gpt-4o"}

        result = shape(enh, "output", meta, ctx, prompt)

        ph = result["provenance"]["prompt_hash"]
        assert len(ph) == 64
        assert ph == hashlib.sha256(prompt.encode()).hexdigest()

    def test_shape_collects_brain_node_ids(self) -> None:
        from spec2sphere.dsp_ai.stages.shape_output import shape

        enh = _make_enhancement()
        ctx = _make_context(
            brain_nodes=[
                {"id": "n1", "label": "View"},
                {"id": "n2"},
                {"no_id": True},  # should be skipped
            ]
        )
        meta: dict[str, Any] = {"model": "gpt-4o"}

        result = shape(enh, "output", meta, ctx, "prompt")

        assert result["provenance"]["input_ids"] == ["n1", "n2"]

    def test_shape_model_in_provenance(self) -> None:
        from spec2sphere.dsp_ai.stages.shape_output import shape

        enh = _make_enhancement()
        ctx = _make_context()
        meta: dict[str, Any] = {"model": "claude-3-opus", "tokens_in": 100, "tokens_out": 200}

        result = shape(enh, "text", meta, ctx, "p")

        assert result["provenance"]["model"] == "claude-3-opus"
        assert result["provenance"]["tokens_in"] == 100


# ---------------------------------------------------------------------------
# Stage 7: Dispatch
# ---------------------------------------------------------------------------


class TestDispatch:
    """Verifies INSERT routing and NOTIFY behaviour without touching Postgres."""

    def _make_shaped(self, enh: Enhancement, render_hint: str | None = None) -> dict:
        gen_id = str(uuid.uuid4())
        return {
            "generation_id": gen_id,
            "enhancement_id": enh.id,
            "render_hint": render_hint or enh.config.render_hint.value,
            "content": {"narrative_text": "Good morning!"},
            "quality_warnings": [],
            "provenance": {
                "prompt_hash": "a" * 64,
                "model": "gpt-4o",
                "quality_level": "Q4",
                "latency_ms": 300,
                "tokens_in": 50,
                "tokens_out": 100,
                "cost_usd": 0.001,
                "input_ids": [],
            },
        }

    @pytest.mark.asyncio
    async def test_preview_writes_generation_not_briefing_no_notify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spec2sphere.dsp_ai.stages import dispatch as dispatch_mod

        enh = _make_enhancement(render_hint=RenderHint.BRIEF)
        shaped = self._make_shaped(enh)

        executed: list[str] = []

        async def fake_execute(query: str, *args: Any, **kwargs: Any) -> None:
            executed.append(query.strip())

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=fake_execute)
        mock_conn.close = AsyncMock()

        monkeypatch.setattr(dispatch_mod.asyncpg, "connect", AsyncMock(return_value=mock_conn))
        emit_mock = AsyncMock()
        monkeypatch.setattr(dispatch_mod, "emit", emit_mock)

        await dispatch_mod.dispatch(
            enh,
            shaped,
            mode=EnhancementMode.BATCH,
            user_id="user1",
            context_key="ctx1",
            preview=True,
        )

        # Only the generations INSERT should have run
        assert any("dsp_ai.generations" in q for q in executed)
        assert not any("dsp_ai.briefings" in q for q in executed)
        emit_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_batch_brief_writes_briefing_and_emits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spec2sphere.dsp_ai.stages import dispatch as dispatch_mod

        enh = _make_enhancement(render_hint=RenderHint.BRIEF)
        shaped = self._make_shaped(enh)

        executed: list[str] = []

        async def fake_execute(query: str, *args: Any, **kwargs: Any) -> None:
            executed.append(query.strip())

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=fake_execute)
        mock_conn.close = AsyncMock()

        monkeypatch.setattr(dispatch_mod.asyncpg, "connect", AsyncMock(return_value=mock_conn))
        emit_mock = AsyncMock()
        monkeypatch.setattr(dispatch_mod, "emit", emit_mock)

        result = await dispatch_mod.dispatch(
            enh,
            shaped,
            mode=EnhancementMode.BATCH,
            user_id="user1",
            context_key="ctx1",
            preview=False,
        )

        assert any("dsp_ai.generations" in q for q in executed)
        assert any("dsp_ai.briefings" in q for q in executed)
        emit_mock.assert_awaited_once()
        call_args = emit_mock.call_args
        assert call_args[0][0] == "briefing_generated"
        assert result["generation_id"] == shaped["generation_id"]

    @pytest.mark.asyncio
    async def test_live_mode_skips_briefing_and_notify(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spec2sphere.dsp_ai.stages import dispatch as dispatch_mod

        enh = _make_enhancement(mode=EnhancementMode.LIVE, render_hint=RenderHint.BRIEF)
        shaped = self._make_shaped(enh)

        executed: list[str] = []

        async def fake_execute(query: str, *args: Any, **kwargs: Any) -> None:
            executed.append(query.strip())

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=fake_execute)
        mock_conn.close = AsyncMock()

        monkeypatch.setattr(dispatch_mod.asyncpg, "connect", AsyncMock(return_value=mock_conn))
        emit_mock = AsyncMock()
        monkeypatch.setattr(dispatch_mod, "emit", emit_mock)

        await dispatch_mod.dispatch(
            enh,
            shaped,
            mode=EnhancementMode.LIVE,
            user_id="user1",
            context_key="ctx1",
            preview=False,
        )

        assert any("dsp_ai.generations" in q for q in executed)
        assert not any("dsp_ai.briefings" in q for q in executed)
        emit_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Engine orchestration
# ---------------------------------------------------------------------------


class TestEngineOrchestration:
    @pytest.mark.asyncio
    async def test_run_engine_chains_all_stages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import spec2sphere.dsp_ai.engine as engine_mod

        enh = _make_enhancement()
        ctx = _make_context(dsp_data=[{"x": 1}])
        shaped = {
            "generation_id": str(uuid.uuid4()),
            "enhancement_id": enh.id,
            "render_hint": "brief",
            "content": {"narrative_text": "Morning brief content"},
            "quality_warnings": [],
            "provenance": {"prompt_hash": "a" * 64, "model": "gpt-4o", "input_ids": []},
        }

        async def fake_resolve(_eid: str) -> Enhancement:
            return enh

        async def fake_gather(_enh: Any, _uid: Any, _hints: Any) -> GatheredContext:
            return ctx

        def fake_apply_rules(_enh: Any, _ctx: Any, _uid: Any, _now: Any) -> GatheredContext:
            return ctx

        def fake_compose(_enh: Any, _ctx: Any, _uid: Any) -> str:
            return "My rendered prompt"

        async def fake_run_llm(_enh: Any, _prompt: str, **_kw: Any) -> tuple[Any, dict]:
            return {"narrative_text": "Morning brief content"}, {"model": "gpt-4o"}

        def fake_shape(_enh: Any, _raw: Any, _meta: Any, _ctx: Any, _prompt: str) -> dict:
            return shaped

        async def fake_dispatch(_enh: Any, _shaped: Any, **_kw: Any) -> dict:
            return shaped

        monkeypatch.setattr(engine_mod, "resolve", fake_resolve)
        monkeypatch.setattr(engine_mod, "gather", fake_gather)
        monkeypatch.setattr(engine_mod, "apply_rules", fake_apply_rules)
        monkeypatch.setattr(engine_mod, "compose", fake_compose)
        monkeypatch.setattr(engine_mod, "run_llm", fake_run_llm)
        monkeypatch.setattr(engine_mod, "shape", fake_shape)
        monkeypatch.setattr(engine_mod, "dispatch", fake_dispatch)

        result = await engine_mod.run_engine(enh.id, user_id="alice", context_key="morning")

        assert "generation_id" in result
        assert "content" in result
        assert result["content"]["narrative_text"] == "Morning brief content"

    @pytest.mark.asyncio
    async def test_run_engine_degrades_gracefully_on_llm_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Spec §5 invariant: no single dependency can 500 the engine.

        LLM timeouts must produce a shaped dict with error_kind + warnings,
        not bubble as an HTTP 500.
        """
        import spec2sphere.dsp_ai.engine as engine_mod

        enh = _make_enhancement()
        ctx = _make_context(dsp_data=[{"x": 1}])

        async def fake_resolve(_eid: str) -> Enhancement:
            return enh

        async def fake_gather(_enh: Any, _uid: Any, _hints: Any) -> GatheredContext:
            return ctx

        def fake_apply_rules(_enh: Any, _ctx: Any, _uid: Any, _now: Any) -> GatheredContext:
            return ctx

        def fake_compose(_enh: Any, _ctx: Any, _uid: Any) -> str:
            return "prompt"

        async def boom_run_llm(_enh: Any, _prompt: str, **_kw: Any) -> tuple[Any, dict]:
            import httpx

            raise httpx.ReadTimeout("LLM endpoint slept")

        captured_shaped: dict[str, Any] = {}

        async def capture_dispatch(_enh: Any, shaped: Any, **_kw: Any) -> dict:
            captured_shaped.update(shaped)
            return shaped

        monkeypatch.setattr(engine_mod, "resolve", fake_resolve)
        monkeypatch.setattr(engine_mod, "gather", fake_gather)
        monkeypatch.setattr(engine_mod, "apply_rules", fake_apply_rules)
        monkeypatch.setattr(engine_mod, "compose", fake_compose)
        monkeypatch.setattr(engine_mod, "run_llm", boom_run_llm)
        monkeypatch.setattr(engine_mod, "dispatch", capture_dispatch)

        # NO exception bubbles. The engine returns a dict.
        result = await engine_mod.run_engine(enh.id, user_id="alice", preview=True)

        assert result["error_kind"] == "llm_timeout"
        assert result["content"] is None
        assert "llm_timeout" in result["quality_warnings"]
        assert captured_shaped["error_kind"] == "llm_timeout"
