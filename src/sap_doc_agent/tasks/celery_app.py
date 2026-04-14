import os
from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("sapdoc", broker=REDIS_URL, backend=REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_routes={
        "sap_doc_agent.tasks.scan_tasks.*": {"queue": "scan"},
        "sap_doc_agent.tasks.agent_tasks.*": {"queue": "llm"},
        "sap_doc_agent.tasks.scan_tasks.run_cdp_scan": {"queue": "chrome"},
        "sap_doc_agent.tasks.chain_tasks.build_chains": {"queue": "scan"},
        "sap_doc_agent.tasks.chain_tasks.analyze_single_chain": {"queue": "llm"},
        "sap_doc_agent.tasks.migration_tasks.*": {"queue": "llm"},
    },
    worker_prefetch_multiplier=1,
)

WORKER_CONCURRENCY_SCAN = int(os.environ.get("WORKER_CONCURRENCY_SCAN", "4"))
WORKER_CONCURRENCY_LLM = int(os.environ.get("WORKER_CONCURRENCY_LLM", "2"))
WORKER_CONCURRENCY_CHROME = int(os.environ.get("WORKER_CONCURRENCY_CHROME", "1"))

# Load beat schedules (nightly QA, weekly report)
from sap_doc_agent.tasks.schedules import BEAT_SCHEDULE  # noqa: E402

celery_app.conf.beat_schedule = BEAT_SCHEDULE
