"""Offline profile smoke tests — Session C Task 1.

Validates that the bundled Ollama sidecar can serve LLM requests when
using the offline profile:

    docker compose -f docker-compose.yml -f docker-compose.offline.yml \\
      --profile offline up

These tests are skipped in CI by default. To run locally:

    docker compose ... up -d
    SKIP_OFFLINE=0 pytest tests/dsp_ai/test_offline_profile.py -v
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("SKIP_OFFLINE") == "1",
    reason="requires docker compose --profile offline up",
)


@pytest.mark.asyncio
async def test_ollama_reachable() -> None:
    """Verify Ollama sidecar is reachable and healthy."""
    endpoint = os.environ.get("LLM_ENDPOINT", "http://localhost:11434/v1")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(
            f"{endpoint}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "say hi"}],
                "max_tokens": 16,
            },
        )

    assert r.status_code == 200, f"Ollama request failed: {r.text}"
    body = r.json()
    assert "choices" in body, f"Invalid response shape: {body}"
    assert len(body["choices"]) > 0
    assert "message" in body["choices"][0]
    assert "content" in body["choices"][0]["message"]
