"""Tests for structured JSON extraction helpers."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from sap_doc_agent.llm.structured import extract_json_from_response, generate_json_with_retry


# ---------------------------------------------------------------------------
# extract_json_from_response
# ---------------------------------------------------------------------------


def test_extract_json_bare():
    result = extract_json_from_response('{"a": 1}')
    assert result == {"a": 1}


def test_extract_json_fenced():
    result = extract_json_from_response('```json\n{"a": 1}\n```')
    assert result == {"a": 1}


def test_extract_json_fenced_no_lang():
    result = extract_json_from_response('```\n{"a": 1}\n```')
    assert result == {"a": 1}


def test_extract_json_with_leading_text():
    result = extract_json_from_response('Here is the result:\n{"a": 1}')
    assert result == {"a": 1}


def test_extract_json_with_trailing_text():
    result = extract_json_from_response('{"a": 1}\nSome trailing explanation.')
    assert result == {"a": 1}


def test_extract_json_malformed():
    result = extract_json_from_response("this is not json at all")
    assert result is None


def test_extract_json_malformed_partial():
    result = extract_json_from_response('{"a": missing_quote}')
    assert result is None


def test_extract_json_empty_string():
    result = extract_json_from_response("")
    assert result is None


def test_extract_json_array():
    result = extract_json_from_response('[{"a": 1}, {"b": 2}]')
    assert result == [{"a": 1}, {"b": 2}]


def test_extract_json_nested():
    result = extract_json_from_response('Prefix {"outer": {"inner": [1, 2, 3]}} suffix')
    assert result == {"outer": {"inner": [1, 2, 3]}}


# ---------------------------------------------------------------------------
# generate_json_with_retry
# ---------------------------------------------------------------------------


class _MockProvider:
    def __init__(self, responses: list[Optional[str]]) -> None:
        self._responses = list(responses)
        self._index = 0

    async def generate(self, prompt: str, system: str = "") -> Optional[str]:
        if self._index < len(self._responses):
            resp = self._responses[self._index]
            self._index += 1
            return resp
        return None

    async def generate_json(self, *args: Any, **kwargs: Any) -> Optional[dict]:
        return None

    def is_available(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_generate_json_with_retry_success():
    provider = _MockProvider(['{"status": "done"}'])
    result = await generate_json_with_retry(provider, "do something", schema={"type": "object"})
    assert result == {"status": "done"}


@pytest.mark.asyncio
async def test_generate_json_with_retry_retries():
    """First response is malformed, second is valid JSON."""
    provider = _MockProvider(["not json", '{"status": "done"}'])
    result = await generate_json_with_retry(provider, "do something", schema={"type": "object"}, max_retries=2)
    assert result == {"status": "done"}


@pytest.mark.asyncio
async def test_generate_json_with_retry_all_fail():
    """All responses are malformed; should return None after exhausting retries."""
    provider = _MockProvider(["not json", "still not json", "nope"])
    result = await generate_json_with_retry(provider, "do something", schema={"type": "object"}, max_retries=2)
    assert result is None


@pytest.mark.asyncio
async def test_generate_json_with_retry_none_response():
    """Provider returns None immediately."""
    provider = _MockProvider([None])
    result = await generate_json_with_retry(provider, "do something", schema={"type": "object"})
    assert result is None


@pytest.mark.asyncio
async def test_generate_json_with_retry_fenced():
    """JSON wrapped in markdown fences should be extracted and returned."""
    provider = _MockProvider(['```json\n{"key": "value"}\n```'])
    result = await generate_json_with_retry(provider, "do something", schema={"type": "object"})
    assert result == {"key": "value"}
