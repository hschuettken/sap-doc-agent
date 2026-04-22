"""Offline profile tests.

Integration tests that require docker compose --profile offline up.
Skipped when SKIP_OFFLINE=1 or LLM_ENDPOINT is not pointing to Ollama.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.offline


def _require_offline():
    if os.environ.get("SKIP_OFFLINE", "1") == "1":
        pytest.skip("SKIP_OFFLINE=1 — requires 'docker compose --profile offline up'")


class TestOfflineProfileFiles:
    """Validate offline compose file is well-formed."""

    def test_docker_compose_offline_exists(self):
        from pathlib import Path

        p = Path(__file__).parent.parent.parent / "docker-compose.offline.yml"
        assert p.exists(), "docker-compose.offline.yml not found"

    def test_ollama_entrypoint_exists(self):
        from pathlib import Path

        p = Path(__file__).parent.parent.parent / "ops" / "ollama-entrypoint.sh"
        assert p.exists(), "ops/ollama-entrypoint.sh not found"
        assert os.access(str(p), os.X_OK), "ollama-entrypoint.sh is not executable"

    def test_offline_compose_references_ollama_service(self):
        from pathlib import Path
        import yaml

        p = Path(__file__).parent.parent.parent / "docker-compose.offline.yml"
        with open(p) as fh:
            doc = yaml.safe_load(fh)
        assert "ollama" in doc.get("services", {}), "ollama service missing from offline compose"

    def test_offline_compose_overrides_llm_endpoint(self):
        from pathlib import Path
        import yaml

        p = Path(__file__).parent.parent.parent / "docker-compose.offline.yml"
        with open(p) as fh:
            doc = yaml.safe_load(fh)
        dsp_ai_env = doc.get("services", {}).get("dsp-ai", {}).get("environment", {})
        env_map = {}
        if isinstance(dsp_ai_env, list):
            for item in dsp_ai_env:
                if "=" in item:
                    k, v = item.split("=", 1)
                    env_map[k] = v
        elif isinstance(dsp_ai_env, dict):
            env_map = dsp_ai_env
        assert "LLM_ENDPOINT" in env_map, "LLM_ENDPOINT not overridden in offline dsp-ai service"
        assert "ollama" in env_map["LLM_ENDPOINT"], "LLM_ENDPOINT should point to ollama"


@pytest.mark.asyncio
async def test_ollama_reachable_in_offline_mode():
    """Requires docker compose --profile offline up."""
    _require_offline()
    import httpx

    endpoint = os.environ.get("LLM_ENDPOINT", "http://localhost:11434/v1")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post(
            f"{endpoint}/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": "say hi"}]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "choices" in body
