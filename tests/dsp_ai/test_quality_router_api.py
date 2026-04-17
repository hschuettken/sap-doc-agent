"""Contract tests for ``quality_router.resolve_and_call``.

No real LLM calls — respx intercepts the httpx request and returns a
canned OpenAI-compatible completion.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from spec2sphere.llm.quality_router import resolve_and_call


@pytest.mark.asyncio
@respx.mock
async def test_resolve_and_call_parses_structured_json(monkeypatch) -> None:
    monkeypatch.setenv("LLM_ENDPOINT", "http://fake-router/v1")
    monkeypatch.setenv("LLM_API_KEY", "secret")

    route = respx.post("http://fake-router/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true, "n": 42}'}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            },
        )
    )
    out, meta = await resolve_and_call("test_action", "hello", schema={"type": "object"})
    assert out == {"ok": True, "n": 42}
    assert meta["tokens_in"] == 12
    assert meta["tokens_out"] == 7
    assert meta["model"]
    assert meta["quality_level"] in {"Q1", "Q2", "Q3", "Q4", "Q5"}
    assert route.call_count == 1
    sent = route.calls[0].request
    assert sent.headers["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
@respx.mock
async def test_resolve_and_call_returns_raw_text_without_schema(monkeypatch) -> None:
    monkeypatch.setenv("LLM_ENDPOINT", "http://fake-router/v1")
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    respx.post("http://fake-router/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "plain text reply"}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2},
            },
        )
    )
    out, meta = await resolve_and_call("test_action", "hello")
    assert out == "plain text reply"
    assert meta["tokens_in"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_resolve_and_call_wraps_non_json_response_in_raw_key(monkeypatch) -> None:
    """If the LLM ignores response_format and returns prose, don't crash."""
    monkeypatch.setenv("LLM_ENDPOINT", "http://fake-router/v1")

    respx.post("http://fake-router/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "sorry, I can't comply"}}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 6},
            },
        )
    )
    out, _ = await resolve_and_call("test_action", "hi", schema={"type": "object"})
    assert out == {"raw": "sorry, I can't comply"}


@pytest.mark.asyncio
async def test_resolve_and_call_raises_when_endpoint_missing(monkeypatch) -> None:
    monkeypatch.delenv("LLM_ENDPOINT", raising=False)
    with pytest.raises(RuntimeError, match="LLM_ENDPOINT"):
        await resolve_and_call("test_action", "hi")
