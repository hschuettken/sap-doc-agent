"""Tests for migration Celery tasks."""

from sap_doc_agent.tasks.migration_tasks import (
    classify_chain_task,
    design_target_task,
    generate_sql_task,
    interpret_chain_task,
    reconcile_brs_task,
)


def test_migration_tasks_route_to_llm_queue():
    assert interpret_chain_task.queue == "llm"
    assert reconcile_brs_task.queue == "llm"
    assert classify_chain_task.queue == "llm"
    assert design_target_task.queue == "llm"
    assert generate_sql_task.queue == "llm"


def test_migration_tasks_have_retry_config():
    assert interpret_chain_task.max_retries == 2
    assert reconcile_brs_task.max_retries == 2
    assert classify_chain_task.max_retries == 2
    assert design_target_task.max_retries == 2
    assert generate_sql_task.max_retries == 2


def test_migration_tasks_are_bound():
    """Tasks should be bound (self as first arg) for retry support."""
    # Celery bound tasks have __self__ after decoration
    assert interpret_chain_task.name.startswith("sap_doc_agent.tasks.migration_tasks.")
    assert reconcile_brs_task.name.startswith("sap_doc_agent.tasks.migration_tasks.")
    assert classify_chain_task.name.startswith("sap_doc_agent.tasks.migration_tasks.")
    assert design_target_task.name.startswith("sap_doc_agent.tasks.migration_tasks.")
    assert generate_sql_task.name.startswith("sap_doc_agent.tasks.migration_tasks.")


def test_celery_routing_includes_migration():
    from sap_doc_agent.tasks.celery_app import celery_app

    routes = celery_app.conf.task_routes
    assert "sap_doc_agent.tasks.migration_tasks.*" in routes
    assert routes["sap_doc_agent.tasks.migration_tasks.*"] == {"queue": "llm"}
