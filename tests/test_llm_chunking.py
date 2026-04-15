"""Tests for text chunking utilities."""

from __future__ import annotations

from typing import Any, Optional

import pytest

from spec2sphere.llm.chunking import chunk_and_aggregate, chunk_text


# ---------------------------------------------------------------------------
# Helper mock provider
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


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------


def test_chunk_text_single_small():
    """Text smaller than max_tokens should return a single chunk."""
    text = "This is a short text."
    chunks = chunk_text(text, max_tokens=1000)
    assert len(chunks) == 1
    assert "short text" in chunks[0]


def test_chunk_text_splits_by_size():
    """A 2000-word text with max_tokens=100 should produce multiple chunks."""
    words = ["word"] * 2000
    text = " ".join(words)
    # max_tokens=100 → max_words ≈ 76
    chunks = chunk_text(text, max_tokens=100, overlap=0)
    assert len(chunks) > 5


def test_chunk_text_overlap():
    """Verify that consecutive chunks share overlap words."""
    # Create text with distinct sections separated by paragraphs
    # so chunking falls into paragraph mode
    sections = [" ".join([f"word{i}_{j}" for j in range(30)]) for i in range(20)]
    text = "\n\n".join(sections)
    overlap = 10
    chunks = chunk_text(text, max_tokens=50, overlap=overlap)

    if len(chunks) > 1:
        # The last `overlap` words of chunk[0] should appear at the start of chunk[1]
        tail_words = chunks[0].split()[-overlap:]
        head_words = chunks[1].split()[:overlap]
        # At least some words should overlap
        assert any(w in head_words for w in tail_words), (
            f"Expected overlap but found none: tail={tail_words[:3]}, head={head_words[:3]}"
        )


def test_chunk_text_abap_boundaries():
    """ABAP boundary keywords should be used as split points."""
    text = (
        "Some preamble text.\n"
        "FORM process_data.\n"
        "  DATA: lv_value TYPE i.\n"
        "  lv_value = 42.\n"
        "ENDFORM.\n"
        "FORM another_routine.\n"
        "  WRITE 'hello'.\n"
        "ENDFORM.\n"
    )
    # Very small tokens so it must split
    chunks = chunk_text(text, max_tokens=20, overlap=0)
    assert len(chunks) >= 2


def test_chunk_text_empty():
    chunks = chunk_text("", max_tokens=100)
    assert chunks == []


def test_chunk_text_single_word():
    chunks = chunk_text("hello", max_tokens=100)
    assert chunks == ["hello"]


def test_chunk_text_all_words_fit():
    text = " ".join(["word"] * 50)
    chunks = chunk_text(text, max_tokens=200, overlap=0)
    assert len(chunks) == 1


# ---------------------------------------------------------------------------
# chunk_and_aggregate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chunk_and_aggregate_single_chunk():
    """Single chunk returns that chunk's result directly."""
    provider = _MockProvider(['{"items": [1, 2]}'])
    result = await chunk_and_aggregate(
        provider,
        prompt_template="Summarize: {chunk}",
        chunks=["some text"],
        schema={"type": "object"},
    )
    assert result == {"items": [1, 2]}


@pytest.mark.asyncio
async def test_chunk_and_aggregate_merges():
    """Two chunks returning dicts with lists should have lists concatenated."""
    provider = _MockProvider(['{"items": [1, 2], "title": "first"}', '{"items": [3, 4], "title": "second"}'])
    result = await chunk_and_aggregate(
        provider,
        prompt_template="Summarize: {chunk}",
        chunks=["chunk one", "chunk two"],
        schema={"type": "object"},
    )
    assert result is not None
    # Lists should be concatenated
    assert sorted(result["items"]) == [1, 2, 3, 4]
    # Scalar: first wins
    assert result["title"] == "first"


@pytest.mark.asyncio
async def test_chunk_and_aggregate_all_fail():
    """If all chunks return None, result is None."""
    provider = _MockProvider([None, None])
    result = await chunk_and_aggregate(
        provider,
        prompt_template="Summarize: {chunk}",
        chunks=["chunk one", "chunk two"],
        schema={"type": "object"},
    )
    assert result is None


@pytest.mark.asyncio
async def test_chunk_and_aggregate_partial_results():
    """If some chunks fail, the successful ones are merged."""
    provider = _MockProvider([None, '{"items": [5, 6]}'])
    result = await chunk_and_aggregate(
        provider,
        prompt_template="Summarize: {chunk}",
        chunks=["chunk one", "chunk two"],
        schema={"type": "object"},
    )
    assert result == {"items": [5, 6]}


@pytest.mark.asyncio
async def test_chunk_and_aggregate_uses_template():
    """The {chunk} placeholder in prompt_template should be replaced."""
    received_prompts: list[str] = []

    class _CapturingProvider:
        async def generate(self, prompt: str, system: str = "") -> Optional[str]:
            received_prompts.append(prompt)
            return '{"ok": true}'

        async def generate_json(self, *args: Any, **kwargs: Any) -> Optional[dict]:
            return None

        def is_available(self) -> bool:
            return True

    provider = _CapturingProvider()
    await chunk_and_aggregate(
        provider,
        prompt_template="Process this: {chunk}",
        chunks=["my chunk content"],
        schema={"type": "object"},
    )
    assert len(received_prompts) >= 1
    assert "my chunk content" in received_prompts[0]
