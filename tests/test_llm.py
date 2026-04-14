import httpx
import pytest
import respx
from pathlib import Path

from sap_doc_agent.config import LLMConfig
from sap_doc_agent.llm import create_llm_provider
from sap_doc_agent.llm.base import LLMProvider
from sap_doc_agent.llm.direct import DirectLLMProvider
from sap_doc_agent.llm.noop import NoopLLMProvider
from sap_doc_agent.llm.passthrough import CopilotPassthroughProvider


# --- Noop tests ---


def test_noop_is_llm_provider():
    assert isinstance(NoopLLMProvider(), LLMProvider)


@pytest.mark.asyncio
async def test_noop_generate_returns_none():
    assert await NoopLLMProvider().generate("test") is None


@pytest.mark.asyncio
async def test_noop_generate_json_returns_none():
    assert await NoopLLMProvider().generate_json("test", schema={"type": "object"}) is None


def test_noop_not_available():
    assert NoopLLMProvider().is_available() is False


# --- Direct tests ---


@pytest.fixture
def direct_provider():
    return DirectLLMProvider(base_url="http://test-llm:8070/v1", api_key="test-key", model="test-model")


def test_direct_is_available(direct_provider):
    assert direct_provider.is_available() is True


@pytest.mark.asyncio
@respx.mock
async def test_direct_generate(direct_provider):
    respx.post("http://test-llm:8070/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "This ADSO stores sales data."}}]})
    )
    result = await direct_provider.generate("Describe this ADSO")
    assert result == "This ADSO stores sales data."


@pytest.mark.asyncio
@respx.mock
async def test_direct_generate_json(direct_provider):
    respx.post("http://test-llm:8070/v1/chat/completions").mock(
        return_value=httpx.Response(
            200, json={"choices": [{"message": {"content": '{"quality": "good", "score": 85}'}}]}
        )
    )
    result = await direct_provider.generate_json("Rate this", schema={"type": "object"})
    assert result == {"quality": "good", "score": 85}


@pytest.mark.asyncio
@respx.mock
async def test_direct_generate_json_malformed(direct_provider):
    respx.post("http://test-llm:8070/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
    )
    assert await direct_provider.generate_json("test", schema={"type": "object"}) is None


@pytest.mark.asyncio
@respx.mock
async def test_direct_handles_api_error(direct_provider):
    respx.post("http://test-llm:8070/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )
    assert await direct_provider.generate("test") is None


# --- Passthrough tests ---


@pytest.fixture
def passthrough_provider(tmp_path: Path):
    return CopilotPassthroughProvider(output_dir=tmp_path)


def test_passthrough_not_available(passthrough_provider):
    assert passthrough_provider.is_available() is False


@pytest.mark.asyncio
async def test_passthrough_writes_prompt(passthrough_provider, tmp_path: Path):
    await passthrough_provider.generate("Describe ADSO_SALES")
    prompts = list(tmp_path.glob("prompt_*.md"))
    assert len(prompts) == 1
    assert "Describe ADSO_SALES" in prompts[0].read_text()


@pytest.mark.asyncio
async def test_passthrough_json_includes_schema(passthrough_provider, tmp_path: Path):
    await passthrough_provider.generate_json("Rate this", schema={"properties": {"score": {"type": "integer"}}})
    content = list(tmp_path.glob("prompt_*.md"))[0].read_text()
    assert '"score"' in content


@pytest.mark.asyncio
async def test_passthrough_includes_system(passthrough_provider, tmp_path: Path):
    await passthrough_provider.generate("user prompt", system="You are an SAP expert")
    content = list(tmp_path.glob("prompt_*.md"))[0].read_text()
    assert "You are an SAP expert" in content


# --- Factory tests ---


def test_factory_noop():
    assert isinstance(create_llm_provider(LLMConfig(mode="none")), NoopLLMProvider)


def test_factory_passthrough(tmp_path: Path):
    assert isinstance(
        create_llm_provider(LLMConfig(mode="copilot_passthrough"), output_dir=tmp_path), CopilotPassthroughProvider
    )


def test_factory_direct(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8070/v1")
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    cfg = LLMConfig(
        mode="direct",
        provider="openai_compatible",
        base_url_env="LLM_BASE_URL",
        api_key_env="LLM_API_KEY",
        model="test",
    )
    assert isinstance(create_llm_provider(cfg), DirectLLMProvider)


def test_factory_direct_missing_env():
    cfg = LLMConfig(
        mode="direct", provider="openai_compatible", base_url_env="NONEXISTENT", api_key_env="NONEXISTENT", model="test"
    )
    with pytest.raises(ValueError, match="environment variable"):
        create_llm_provider(cfg)


def test_factory_gemini_via_env(monkeypatch):
    """Factory resolves LLM_PROVIDER=gemini to GeminiProvider."""
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    from sap_doc_agent.llm.gemini import GeminiProvider

    provider = create_llm_provider(LLMConfig())
    assert isinstance(provider, GeminiProvider)
