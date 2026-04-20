def test_run_scan_task_exists():
    from spec2sphere.tasks.scan_tasks import run_scan

    assert run_scan is not None


def test_run_abap_scan_task_exists():
    from spec2sphere.tasks.scan_tasks import run_abap_scan

    assert run_abap_scan is not None


def test_cdp_scan_routes_to_chrome_queue():
    from spec2sphere.tasks.scan_tasks import run_cdp_scan

    assert run_cdp_scan.queue == "chrome"


def test_run_doc_review_routes_to_llm_queue():
    from spec2sphere.tasks.agent_tasks import run_doc_review

    assert run_doc_review.queue == "llm"


def test_scan_task_returns_run_id():
    from spec2sphere.tasks.scan_tasks import run_scan

    # Call the underlying function directly (bypasses Celery).
    # With a bogus config path the task should return a "skipped" status
    # (permanent failure, no retry) rather than raising.
    result = run_scan.run(scanner_type="dsp_api", config_path="test.yaml", run_id="test-123")
    assert result["run_id"] == "test-123"
    assert result["status"] in ("completed", "skipped")


def test_scheduled_tasks_are_registered_in_celery_app():
    """Every task name referenced in BEAT_SCHEDULE must be importable by the worker.

    The worker uses celery_app.imports to discover task modules. If a scheduled task
    module is missing from imports=(...), the worker throws KeyError at runtime.
    """
    from spec2sphere.tasks.celery_app import celery_app
    from spec2sphere.tasks.schedules import BEAT_SCHEDULE

    # Trigger task autodiscovery (imports the modules listed in celery_app.conf.imports)
    celery_app.loader.import_default_modules()

    registered = celery_app.tasks.keys()
    for schedule_name, entry in BEAT_SCHEDULE.items():
        task_name = entry["task"]
        # dsp_ai.synthesize_topics is defined inline in celery_app.py, not via imports
        if task_name == "dsp_ai.synthesize_topics":
            continue
        assert task_name in registered, (
            f"Scheduled task '{task_name}' (from beat entry '{schedule_name}') "
            f"is not registered in celery_app.tasks. Add its module to celery_app.conf.imports."
        )
