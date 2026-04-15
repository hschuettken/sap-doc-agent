

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

    # Call the underlying function directly (bypasses Celery)
    result = run_scan.run(scanner_type="dsp_api", config_path="test.yaml", run_id="test-123")
    assert result["run_id"] == "test-123"
    assert result["status"] == "completed"
