"""Unit tests for item_enrich dispatch path in dispatch.py."""

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


_GEN_ID = "33333333-3333-3333-3333-333333333333"
_ENH_ID = "44444444-4444-4444-4444-444444444444"


def _make_item_enrich_enh() -> Enhancement:
    return Enhancement(
        id=_ENH_ID,
        version=1,
        status="published",
        config=EnhancementConfig(
            name="column_title_gen",
            kind=EnhancementKind.ITEM_ENRICH,
            mode=EnhancementMode.BATCH,
            bindings=EnhancementBindings(data=DataBinding(dsp_query="SELECT 1")),
            prompt_template="x",
            render_hint=RenderHint.CALLOUT,  # column title gen uses callout but kind=item_enrich
        ),
    )


def _item_enrich_shaped() -> dict:
    return {
        "generation_id": _GEN_ID,
        "content": {
            "enrichments": [
                {
                    "object_type": "Column",
                    "object_id": "sales.amount",
                    "title": "Revenue",
                    "description": "EUR net sales",
                    "tags": ["kpi"],
                    "kpi_suggestions": [],
                }
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
async def test_item_enrich_dispatch_writes_upsert() -> None:
    from spec2sphere.dsp_ai.stages import dispatch as dispatch_mod

    enh = _make_item_enrich_enh()
    shaped = _item_enrich_shaped()
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

    # item_enhancements upsert present
    ie_inserts = [(sql, args) for sql, args in conn.calls if "dsp_ai.item_enhancements" in sql]
    assert len(ie_inserts) == 1, "expected 1 item_enhancements upsert"

    # verify ON CONFLICT ... DO UPDATE is present
    ie_sql = ie_inserts[0][0]
    assert "ON CONFLICT" in ie_sql
    assert "DO UPDATE" in ie_sql

    # verify args: object_type, object_id, user_id
    ie_args = ie_inserts[0][1]
    assert ie_args[0] == "Column"
    assert ie_args[1] == "sales.amount"
    assert ie_args[2] == "alice"  # user_id passed through
    assert ie_args[3] == "Revenue"  # title_suggested

    # must NOT write to rankings or briefings
    assert not any("dsp_ai.rankings" in s for s in sqls)
    assert not any("dsp_ai.briefings" in s for s in sqls)

    assert conn.closed is True


@pytest.mark.asyncio
async def test_item_enrich_uses_global_when_no_user_id() -> None:
    from spec2sphere.dsp_ai.stages import dispatch as dispatch_mod

    enh = _make_item_enrich_enh()
    shaped = _item_enrich_shaped()
    conn, connect = _make_conn()

    with (
        patch.object(dispatch_mod.asyncpg, "connect", connect),
        patch("spec2sphere.dsp_ai.stages.dispatch.emit", new_callable=AsyncMock),
    ):
        await dispatch_mod.dispatch(
            enh,
            shaped,
            mode=EnhancementMode.BATCH,
            user_id=None,
            context_key="morning",
        )

    ie_inserts = [(sql, args) for sql, args in conn.calls if "dsp_ai.item_enhancements" in sql]
    assert len(ie_inserts) == 1
    assert ie_inserts[0][1][2] == "_global"


@pytest.mark.asyncio
async def test_item_enrich_kind_takes_precedence_over_callout_render_hint() -> None:
    """kind=ITEM_ENRICH with render_hint=CALLOUT must write item_enhancements, not briefings."""
    from spec2sphere.dsp_ai.stages import dispatch as dispatch_mod

    # same as _make_item_enrich_enh() — render_hint=CALLOUT but kind=ITEM_ENRICH
    enh = _make_item_enrich_enh()
    shaped = _item_enrich_shaped()
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
    assert any("dsp_ai.item_enhancements" in s for s in sqls)
    assert not any("dsp_ai.briefings" in s for s in sqls)


@pytest.mark.asyncio
async def test_item_enrich_no_write_on_preview() -> None:
    from spec2sphere.dsp_ai.stages import dispatch as dispatch_mod

    enh = _make_item_enrich_enh()
    shaped = _item_enrich_shaped()
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
    assert not any("dsp_ai.item_enhancements" in s for s in sqls)
    assert any("dsp_ai.generations" in s for s in sqls)
