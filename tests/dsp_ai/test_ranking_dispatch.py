"""Unit tests for ranking dispatch path in dispatch.py."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from spec2sphere.dsp_ai.config import (
    DataBinding,
    Enhancement,
    EnhancementBindings,
    EnhancementConfig,
    EnhancementKind,
    EnhancementMode,
    RenderHint,
)


_GEN_ID = "11111111-1111-1111-1111-111111111111"
_ENH_ID = "22222222-2222-2222-2222-222222222222"


def _make_ranking_enh() -> Enhancement:
    return Enhancement(
        id=_ENH_ID,
        version=1,
        status="published",
        config=EnhancementConfig(
            name="top_items",
            kind=EnhancementKind.RANKING,
            mode=EnhancementMode.BATCH,
            bindings=EnhancementBindings(data=DataBinding(dsp_query="SELECT 1")),
            prompt_template="x",
            render_hint=RenderHint.RANKED_LIST,
        ),
    )


def _ranking_shaped() -> dict:
    return {
        "generation_id": _GEN_ID,
        "content": {
            "items": [
                {"item_id": "x", "score": 0.9, "reason": "r1"},
                {"item_id": "y", "score": 0.8, "reason": "r2"},
            ]
        },
        "quality_warnings": [],
        "provenance": {
            "prompt_hash": "h",
            "input_ids": [],
            "model": "m",
            "quality_level": "Q2",
            "latency_ms": 1,
            "tokens_in": 1,
            "tokens_out": 1,
            "cost_usd": 0.0,
        },
    }


class _FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.closed = False

    async def execute(self, sql: str, *args) -> None:
        self.calls.append((sql, args))

    async def close(self) -> None:
        self.closed = True


def _make_conn() -> tuple[_FakeConn, AsyncMock]:
    conn = _FakeConn()

    async def _connect(*_a, **_kw):
        return conn

    return conn, _connect


@pytest.mark.asyncio
async def test_ranking_dispatch_writes_delete_then_inserts() -> None:
    from spec2sphere.dsp_ai.stages import dispatch as dispatch_mod

    enh = _make_ranking_enh()
    shaped = _ranking_shaped()
    conn, connect = _make_conn()

    with (
        patch.object(dispatch_mod.asyncpg, "connect", connect),
        patch("spec2sphere.dsp_ai.stages.dispatch.emit", new_callable=AsyncMock),
    ):
        result = await dispatch_mod.dispatch(
            enh,
            shaped,
            mode=EnhancementMode.BATCH,
            user_id="alice",
            context_key="morning",
        )

    assert result is shaped

    sqls = [sql.strip() for sql, _args in conn.calls]

    # generations INSERT always first
    assert any("dsp_ai.generations" in s for s in sqls)

    # DELETE before ranking INSERTs
    delete_idx = next(i for i, s in enumerate(sqls) if "DELETE FROM dsp_ai.rankings" in s)
    insert_idxs = [i for i, s in enumerate(sqls) if "INSERT INTO dsp_ai.rankings" in s]

    assert len(insert_idxs) == 2, "expected 2 ranking inserts for 2 items"
    assert all(idx > delete_idx for idx in insert_idxs), "INSERTs must follow DELETE"

    # verify args: first insert has rank=1, item_id="x"
    first_insert_args = conn.calls[insert_idxs[0]][1]
    assert first_insert_args[3] == "x"  # item_id
    assert first_insert_args[4] == 1  # rank
    assert first_insert_args[5] == 0.9  # score

    # second insert has rank=2, item_id="y"
    second_insert_args = conn.calls[insert_idxs[1]][1]
    assert second_insert_args[3] == "y"
    assert second_insert_args[4] == 2

    assert conn.closed is True


@pytest.mark.asyncio
async def test_ranking_dispatch_no_write_on_preview() -> None:
    from spec2sphere.dsp_ai.stages import dispatch as dispatch_mod

    enh = _make_ranking_enh()
    shaped = _ranking_shaped()
    conn, connect = _make_conn()

    with (
        patch.object(dispatch_mod.asyncpg, "connect", connect),
        patch("spec2sphere.dsp_ai.stages.dispatch.emit", new_callable=AsyncMock),
    ):
        await dispatch_mod.dispatch(
            enh,
            shaped,
            mode=EnhancementMode.BATCH,
            user_id="alice",
            context_key="morning",
            preview=True,
        )

    sqls = [sql.strip() for sql, _args in conn.calls]
    assert not any("dsp_ai.rankings" in s for s in sqls), "preview must skip ranking writes"
    # generations insert should still happen
    assert any("dsp_ai.generations" in s for s in sqls)


@pytest.mark.asyncio
async def test_action_button_render_hint_skips_ranking_write() -> None:
    """BUTTON render hint (action) must not write to rankings or briefings."""
    from spec2sphere.dsp_ai.stages import dispatch as dispatch_mod

    enh = Enhancement(
        id=_ENH_ID,
        version=1,
        status="published",
        config=EnhancementConfig(
            name="action_enh",
            kind=EnhancementKind.ACTION,
            mode=EnhancementMode.BATCH,
            bindings=EnhancementBindings(data=DataBinding(dsp_query="SELECT 1")),
            prompt_template="x",
            render_hint=RenderHint.BUTTON,
        ),
    )
    shaped = _ranking_shaped()
    conn, connect = _make_conn()

    with (
        patch.object(dispatch_mod.asyncpg, "connect", connect),
        patch("spec2sphere.dsp_ai.stages.dispatch.emit", new_callable=AsyncMock),
    ):
        await dispatch_mod.dispatch(
            enh,
            shaped,
            mode=EnhancementMode.BATCH,
            user_id="alice",
            context_key="morning",
        )

    sqls = [sql.strip() for sql, _args in conn.calls]
    assert not any("dsp_ai.rankings" in s for s in sqls)
    assert not any("dsp_ai.briefings" in s for s in sqls)
    assert not any("dsp_ai.item_enhancements" in s for s in sqls)
    # but generations + emit still happen
    assert any("dsp_ai.generations" in s for s in sqls)
