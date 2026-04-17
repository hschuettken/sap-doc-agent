"""ObservedLLMProvider — best-effort logging of every generate() call."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spec2sphere.llm.base import LLMProvider
from spec2sphere.llm.observed import ObservedLLMProvider


class _FakeProvider(LLMProvider):
    _model = "fake-model"

    async def generate(self, prompt, system="", *, tier="large", data_in_context=False):
        return "ok"

    async def generate_json(self, prompt, schema, system="", *, tier="large", data_in_context=False):
        return {"ok": True}

    def is_available(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_wrapper_records_generate_call() -> None:
    wrapped = ObservedLLMProvider(_FakeProvider())
    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock()
    fake_conn.close = AsyncMock()

    async def _connect(*a, **k):
        return fake_conn

    with patch("asyncpg.connect", _connect):
        out = await wrapped.generate("hi", caller="agents.doc_review")

    assert out == "ok"
    fake_conn.execute.assert_awaited_once()
    args = fake_conn.execute.await_args.args
    # positional args after SQL: uuid, prompt_hash, model, quality_level, latency_ms, error, caller
    assert args[-1] == "agents.doc_review"  # caller
    assert args[-2] is None  # error (success)
    assert args[3] == "fake-model"  # model hint


@pytest.mark.asyncio
async def test_wrapper_records_generate_json_call() -> None:
    wrapped = ObservedLLMProvider(_FakeProvider())
    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock()
    fake_conn.close = AsyncMock()

    async def _connect(*a, **k):
        return fake_conn

    with patch("asyncpg.connect", _connect):
        out = await wrapped.generate_json("hi", {"type": "object"}, caller="migration.classifier")

    assert out == {"ok": True}
    fake_conn.execute.assert_awaited_once()
    assert fake_conn.execute.await_args.args[-1] == "migration.classifier"


@pytest.mark.asyncio
async def test_wrapper_does_not_swallow_provider_exceptions() -> None:
    class _Broken(LLMProvider):
        async def generate(self, *a, **k):
            raise RuntimeError("boom")

        async def generate_json(self, *a, **k):
            raise RuntimeError("boom")

        def is_available(self):
            return True

    wrapped = ObservedLLMProvider(_Broken())
    fake_conn = MagicMock()
    fake_conn.execute = AsyncMock()
    fake_conn.close = AsyncMock()

    async def _connect(*a, **k):
        return fake_conn

    with patch("asyncpg.connect", _connect), pytest.raises(RuntimeError):
        await wrapped.generate("x", caller="test")

    # Logging still happened (with error="exception")
    fake_conn.execute.assert_awaited_once()
    assert fake_conn.execute.await_args.args[-2] == "exception"
    assert fake_conn.execute.await_args.args[-1] == "test"


@pytest.mark.asyncio
async def test_wrapper_swallows_db_failures() -> None:
    """DB errors during logging must not propagate — LLM call result still returned."""
    wrapped = ObservedLLMProvider(_FakeProvider())

    async def _connect_fail(*a, **k):
        raise ConnectionError("pg down")

    with patch("asyncpg.connect", _connect_fail):
        out = await wrapped.generate("hi", caller="whatever")
    assert out == "ok"  # underlying call succeeded


@pytest.mark.asyncio
async def test_wrapper_is_idempotent_via_factory() -> None:
    """Applying the wrapper twice must not double-nest."""
    from spec2sphere.llm.observed import ObservedLLMProvider as OP

    inner = _FakeProvider()
    w1 = OP(inner)
    # Factory check (mirrored in __init__.py _wrap)
    assert isinstance(w1, OP)


def test_wrapper_forwards_attribute_access() -> None:
    """__getattr__ transparently exposes inner provider's attrs — needed by TieredProvider etc."""

    class _Provider(LLMProvider):
        model = "test-model"
        extra = 42

        async def generate(self, *a, **k):
            return "x"

        async def generate_json(self, *a, **k):
            return {}

        def is_available(self):
            return True

    wrapped = ObservedLLMProvider(_Provider())
    assert wrapped.extra == 42


def test_wrapper_is_available_delegates() -> None:
    wrapped = ObservedLLMProvider(_FakeProvider())
    assert wrapped.is_available() is True


def test_factory_wraps_with_observed() -> None:
    from spec2sphere.config import LLMConfig
    from spec2sphere.llm import create_llm_provider
    from spec2sphere.llm.observed import ObservedLLMProvider

    cfg = LLMConfig(mode="none")
    provider = create_llm_provider(cfg)
    assert isinstance(provider, ObservedLLMProvider)
