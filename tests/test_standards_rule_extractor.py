import pytest
from unittest.mock import AsyncMock, MagicMock

from spec2sphere.standards.rule_extractor import extract_rules


@pytest.mark.asyncio
async def test_extract_rules_with_noop_llm():
    from spec2sphere.llm.noop import NoopLLMProvider

    result = await extract_rules("Some documentation text", NoopLLMProvider())
    assert isinstance(result, dict)
    assert "sections" in result
    assert "naming_rules" in result


@pytest.mark.asyncio
async def test_extract_rules_returns_structure():
    mock_llm = MagicMock()
    mock_llm.is_available.return_value = True
    mock_llm.generate = AsyncMock(
        return_value='{"sections": ["intro"], "naming_rules": [{"name": "Z prefix"}], "field_requirements": [], "custom_rules": []}'
    )
    result = await extract_rules("Short doc text", mock_llm)
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_extract_rules_large_doc_chunks():
    from spec2sphere.llm.noop import NoopLLMProvider

    large_text = "Rule: " + "x" * 15000
    result = await extract_rules(large_text, NoopLLMProvider())
    assert isinstance(result, dict)
