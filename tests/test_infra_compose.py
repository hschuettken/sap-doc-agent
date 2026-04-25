"""Infrastructure audit: docker-compose.yml queue-to-worker coverage.

Every queue that appears in celery_app task_routes or beat schedules MUST
have at least one worker service in docker-compose.yml consuming it.
Missing consumers cause beat tasks to silently pile up and never run.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

COMPOSE_PATH = Path(__file__).parents[1] / "docker-compose.yml"


def _load_compose() -> dict:
    with open(COMPOSE_PATH) as f:
        return yaml.safe_load(f)


def _worker_queues(compose: dict) -> dict[str, set[str]]:
    """Return {service_name: {queue, ...}} for all Celery worker services."""
    result: dict[str, set[str]] = {}
    for svc_name, svc in (compose.get("services") or {}).items():
        cmd = svc.get("command", "")
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        m = re.search(r"-Q\s+([^\s]+)", cmd)
        if m:
            result[svc_name] = set(m.group(1).split(","))
    return result


def _all_consumed_queues(compose: dict) -> set[str]:
    return {q for qs in _worker_queues(compose).values() for q in qs}


class TestWorkerQueueCoverage:
    def test_scan_queue_has_worker(self):
        compose = _load_compose()
        assert "scan" in _all_consumed_queues(compose), "scan queue has no worker"

    def test_llm_queue_has_worker(self):
        compose = _load_compose()
        assert "llm" in _all_consumed_queues(compose), "llm queue has no worker"

    def test_chrome_queue_has_worker(self):
        compose = _load_compose()
        assert "chrome" in _all_consumed_queues(compose), "chrome queue has no worker"

    def test_sac_queue_has_worker(self):
        compose = _load_compose()
        assert "sac" in _all_consumed_queues(compose), "sac queue has no worker"

    def test_ai_batch_queue_has_worker(self):
        """ai-batch beat tasks must not pile up without a consumer."""
        compose = _load_compose()
        assert "ai-batch" in _all_consumed_queues(compose), (
            "ai-batch queue has no worker — dsp-ai batch enhancements will never run"
        )

    def test_worker_has_llm_endpoint_for_ai_batch(self):
        """Worker that consumes ai-batch must have LLM_ENDPOINT configured."""
        compose = _load_compose()
        worker_queues = _worker_queues(compose)
        for svc_name, queues in worker_queues.items():
            if "ai-batch" in queues:
                svc = compose["services"][svc_name]
                env_list = svc.get("environment", [])
                env_keys = set()
                for entry in env_list:
                    if isinstance(entry, str):
                        env_keys.add(entry.split("=")[0])
                assert any(k.startswith("LLM_ENDPOINT") for k in env_keys), (
                    f"Service {svc_name} handles ai-batch but is missing LLM_ENDPOINT"
                )

    def test_worker_has_neo4j_for_ai_batch(self):
        """Worker that consumes ai-batch needs NEO4J_URL for Brain queries."""
        compose = _load_compose()
        worker_queues = _worker_queues(compose)
        for svc_name, queues in worker_queues.items():
            if "ai-batch" in queues:
                svc = compose["services"][svc_name]
                env_list = svc.get("environment", [])
                env_keys = set()
                for entry in env_list:
                    if isinstance(entry, str):
                        env_keys.add(entry.split("=")[0])
                assert any(k.startswith("NEO4J_URL") for k in env_keys), (
                    f"Service {svc_name} handles ai-batch but is missing NEO4J_URL"
                )
