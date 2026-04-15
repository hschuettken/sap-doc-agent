"""Tests for all new LLM provider adapters."""

from __future__ import annotations


import httpx
import pytest
import respx

from spec2sphere.llm.base import LLMProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OPENAI_RESPONSE = {"choices": [{"message": {"content": "hello from LLM"}}]}
_OPENAI_JSON_RESPONSE = {"choices": [{"message": {"content": '{"result": "ok"}'}}]}
_ANTHROPIC_RESPONSE = {"content": [{"text": "hello from anthropic"}]}
_ANTHROPIC_JSON_RESPONSE = {"content": [{"text": '{"result": "ok"}'}]}


# ---------------------------------------------------------------------------
# RouterLLMProvider
# ---------------------------------------------------------------------------


@pytest.fixture
def router_provider(monkeypatch):
    monkeypatch.setenv("LLM_ROUTER_URL", "http://router-test:8070/v1")
    monkeypatch.setenv("LLM_ROUTER_API_KEY", "router-key")
    monkeypatch.setenv("LLM_ROUTER_MODEL", "default")
    from spec2sphere.llm.router import RouterLLMProvider

    return RouterLLMProvider()


def test_router_is_available(router_provider):
    assert router_provider.is_available() is True


def test_router_is_llm_provider(router_provider):
    assert isinstance(router_provider, LLMProvider)


@pytest.mark.asyncio
@respx.mock
async def test_router_generate(router_provider):
    respx.post("http://router-test:8070/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
    )
    result = await router_provider.generate("test prompt")
    assert result == "hello from LLM"


@pytest.mark.asyncio
@respx.mock
async def test_router_generate_json(router_provider):
    respx.post("http://router-test:8070/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_JSON_RESPONSE)
    )
    result = await router_provider.generate_json("test", schema={"type": "object"})
    assert result == {"result": "ok"}


@pytest.mark.asyncio
@respx.mock
async def test_router_handles_error(router_provider):
    respx.post("http://router-test:8070/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="Server Error")
    )
    result = await router_provider.generate("test")
    assert result is None


# ---------------------------------------------------------------------------
# OpenAIProvider
# ---------------------------------------------------------------------------


@pytest.fixture
def openai_provider(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o")
    from spec2sphere.llm.openai import OpenAIProvider

    return OpenAIProvider()


def test_openai_is_available(openai_provider):
    assert openai_provider.is_available() is True


def test_openai_is_llm_provider(openai_provider):
    assert isinstance(openai_provider, LLMProvider)


@pytest.mark.asyncio
@respx.mock
async def test_openai_generate(openai_provider):
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
    )
    result = await openai_provider.generate("test prompt")
    assert result == "hello from LLM"


@pytest.mark.asyncio
@respx.mock
async def test_openai_generate_json(openai_provider):
    respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_JSON_RESPONSE)
    )
    result = await openai_provider.generate_json("test", schema={"type": "object"})
    assert result == {"result": "ok"}


@pytest.mark.asyncio
@respx.mock
async def test_openai_handles_error(openai_provider):
    respx.post("https://api.openai.com/v1/chat/completions").mock(return_value=httpx.Response(500, text="Server Error"))
    result = await openai_provider.generate("test")
    assert result is None


# ---------------------------------------------------------------------------
# AzureOpenAIProvider
# ---------------------------------------------------------------------------


@pytest.fixture
def azure_provider(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "azure-key-123")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://myresource.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4-deployment")
    from spec2sphere.llm.azure_openai import AzureOpenAIProvider

    return AzureOpenAIProvider()


def test_azure_is_available(azure_provider):
    assert azure_provider.is_available() is True


def test_azure_is_llm_provider(azure_provider):
    assert isinstance(azure_provider, LLMProvider)


@pytest.mark.asyncio
@respx.mock
async def test_azure_generate(azure_provider):
    route = respx.post("https://myresource.openai.azure.com/openai/deployments/gpt-4-deployment/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
    )
    result = await azure_provider.generate("test prompt")
    assert result == "hello from LLM"
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_azure_generate_json(azure_provider):
    respx.post("https://myresource.openai.azure.com/openai/deployments/gpt-4-deployment/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_JSON_RESPONSE)
    )
    result = await azure_provider.generate_json("test", schema={"type": "object"})
    assert result == {"result": "ok"}


@pytest.mark.asyncio
@respx.mock
async def test_azure_handles_error(azure_provider):
    respx.post("https://myresource.openai.azure.com/openai/deployments/gpt-4-deployment/chat/completions").mock(
        return_value=httpx.Response(500, text="Server Error")
    )
    result = await azure_provider.generate("test")
    assert result is None


@pytest.mark.asyncio
@respx.mock
async def test_azure_uses_api_key_header_not_bearer(azure_provider):
    """Azure must use 'api-key' header, NOT 'Authorization: Bearer'."""
    captured_request: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        captured_request.append(request)
        return httpx.Response(200, json=_OPENAI_RESPONSE)

    respx.post("https://myresource.openai.azure.com/openai/deployments/gpt-4-deployment/chat/completions").mock(
        side_effect=capture
    )

    await azure_provider.generate("test")
    assert len(captured_request) == 1
    req = captured_request[0]
    assert "api-key" in req.headers
    assert req.headers["api-key"] == "azure-key-123"
    # Must NOT have Bearer authorization
    assert "authorization" not in req.headers or not req.headers.get("authorization", "").startswith("Bearer")


# ---------------------------------------------------------------------------
# VLLMProvider
# ---------------------------------------------------------------------------


@pytest.fixture
def vllm_provider(monkeypatch):
    monkeypatch.setenv("VLLM_BASE_URL", "http://vllm-server:8000")
    monkeypatch.setenv("VLLM_MODEL", "mistral-7b")
    monkeypatch.setenv("VLLM_API_KEY", "vllm-key")
    from spec2sphere.llm.vllm import VLLMProvider

    return VLLMProvider()


def test_vllm_is_available(vllm_provider):
    assert vllm_provider.is_available() is True


def test_vllm_is_llm_provider(vllm_provider):
    assert isinstance(vllm_provider, LLMProvider)


@pytest.mark.asyncio
@respx.mock
async def test_vllm_generate(vllm_provider):
    respx.post("http://vllm-server:8000/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
    )
    result = await vllm_provider.generate("test prompt")
    assert result == "hello from LLM"


@pytest.mark.asyncio
@respx.mock
async def test_vllm_generate_json(vllm_provider):
    respx.post("http://vllm-server:8000/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_JSON_RESPONSE)
    )
    result = await vllm_provider.generate_json("test", schema={"type": "object"})
    assert result == {"result": "ok"}


@pytest.mark.asyncio
@respx.mock
async def test_vllm_handles_error(vllm_provider):
    respx.post("http://vllm-server:8000/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="Server Error")
    )
    result = await vllm_provider.generate("test")
    assert result is None


# ---------------------------------------------------------------------------
# OllamaProvider
# ---------------------------------------------------------------------------


@pytest.fixture
def ollama_provider(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama-server:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:14b")
    from spec2sphere.llm.ollama import OllamaProvider

    return OllamaProvider()


def test_ollama_is_available(ollama_provider):
    assert ollama_provider.is_available() is True


def test_ollama_is_llm_provider(ollama_provider):
    assert isinstance(ollama_provider, LLMProvider)


@pytest.mark.asyncio
@respx.mock
async def test_ollama_generate(ollama_provider):
    respx.post("http://ollama-server:11434/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
    )
    result = await ollama_provider.generate("test prompt")
    assert result == "hello from LLM"


@pytest.mark.asyncio
@respx.mock
async def test_ollama_generate_json(ollama_provider):
    respx.post("http://ollama-server:11434/v1/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_JSON_RESPONSE)
    )
    result = await ollama_provider.generate_json("test", schema={"type": "object"})
    assert result == {"result": "ok"}


@pytest.mark.asyncio
@respx.mock
async def test_ollama_handles_error(ollama_provider):
    respx.post("http://ollama-server:11434/v1/chat/completions").mock(
        return_value=httpx.Response(500, text="Server Error")
    )
    result = await ollama_provider.generate("test")
    assert result is None


# ---------------------------------------------------------------------------
# AnthropicProvider
# ---------------------------------------------------------------------------


@pytest.fixture
def anthropic_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthro-key-123")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-6")
    from spec2sphere.llm.anthropic import AnthropicProvider

    return AnthropicProvider()


def test_anthropic_is_available(anthropic_provider):
    assert anthropic_provider.is_available() is True


def test_anthropic_is_llm_provider(anthropic_provider):
    assert isinstance(anthropic_provider, LLMProvider)


def test_anthropic_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from spec2sphere.llm.anthropic import AnthropicProvider

    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider()


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_generate(anthropic_provider):
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(200, json=_ANTHROPIC_RESPONSE))
    result = await anthropic_provider.generate("test prompt")
    assert result == "hello from anthropic"


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_generate_json(anthropic_provider):
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=_ANTHROPIC_JSON_RESPONSE)
    )
    result = await anthropic_provider.generate_json("test", schema={"type": "object"})
    assert result == {"result": "ok"}


@pytest.mark.asyncio
@respx.mock
async def test_anthropic_handles_error(anthropic_provider):
    respx.post("https://api.anthropic.com/v1/messages").mock(return_value=httpx.Response(500, text="Server Error"))
    result = await anthropic_provider.generate("test")
    assert result is None


# ---------------------------------------------------------------------------
# GeminiProvider
# ---------------------------------------------------------------------------


@pytest.fixture
def gemini_provider(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key-123")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    from spec2sphere.llm.gemini import GeminiProvider

    return GeminiProvider()


def test_gemini_is_available(gemini_provider):
    assert gemini_provider.is_available() is True


def test_gemini_is_llm_provider(gemini_provider):
    assert isinstance(gemini_provider, LLMProvider)


def test_gemini_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from spec2sphere.llm.gemini import GeminiProvider

    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        GeminiProvider()


@pytest.mark.asyncio
@respx.mock
async def test_gemini_generate(gemini_provider):
    respx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_RESPONSE)
    )
    result = await gemini_provider.generate("test prompt")
    assert result == "hello from LLM"


@pytest.mark.asyncio
@respx.mock
async def test_gemini_generate_json(gemini_provider):
    respx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions").mock(
        return_value=httpx.Response(200, json=_OPENAI_JSON_RESPONSE)
    )
    result = await gemini_provider.generate_json("test", schema={"type": "object"})
    assert result == {"result": "ok"}


@pytest.mark.asyncio
@respx.mock
async def test_gemini_handles_error(gemini_provider):
    respx.post("https://generativelanguage.googleapis.com/v1beta/openai/chat/completions").mock(
        return_value=httpx.Response(500, text="Server Error")
    )
    result = await gemini_provider.generate("test")
    assert result is None
