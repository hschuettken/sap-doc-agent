"""Tests for chain Celery tasks."""

from pathlib import Path


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sample_bw_scan"


def test_chain_tasks_route_to_correct_queues():
    from spec2sphere.tasks.chain_tasks import build_chains, analyze_single_chain

    assert build_chains.queue == "scan"
    assert analyze_single_chain.queue == "llm"


def test_build_chains_task_returns_chain_ids(tmp_path):
    """Run build_chains against fixture, writing output to tmp_path."""
    import shutil

    # Copy fixture to tmp_path so we can write chains/ there
    fixture_copy = tmp_path / "scan_output"
    shutil.copytree(FIXTURE_DIR, fixture_copy)

    from spec2sphere.tasks.chain_tasks import build_chains

    result = build_chains.run(
        output_dir=str(fixture_copy),
        scan_id="test-scan-001",
    )
    assert result["status"] == "completed"
    assert result["chain_count"] == 3
    assert len(result["chain_ids"]) == 3

    # Verify chain files were written
    chains_dir = fixture_copy / "chains"
    assert chains_dir.exists()
    for chain_id in result["chain_ids"]:
        assert (chains_dir / f"{chain_id}.md").exists()
        assert (chains_dir / f"{chain_id}.json").exists()


def test_build_chains_task_skips_if_no_graph(tmp_path):
    from spec2sphere.tasks.chain_tasks import build_chains

    result = build_chains.run(
        output_dir=str(tmp_path),
        scan_id="no-graph",
    )
    assert result["status"] == "skipped"
    assert "no graph.json" in result["reason"]


def test_build_chains_fan_out_dispatches_analysis(tmp_path):
    """build_chains should attempt to dispatch analyze_single_chain per chain."""
    import shutil
    from unittest.mock import patch

    fixture_copy = tmp_path / "scan_output"
    shutil.copytree(FIXTURE_DIR, fixture_copy)

    from spec2sphere.tasks.chain_tasks import build_chains

    with patch("spec2sphere.tasks.chain_tasks.analyze_single_chain") as mock_analyze:
        mock_analyze.apply_async.return_value = None
        result = build_chains.run(
            output_dir=str(fixture_copy),
            scan_id="fan-out-test",
        )
    assert result["analysis_dispatched"] == 3
    assert mock_analyze.apply_async.call_count == 3


def test_build_chains_fan_out_graceful_on_broker_error(tmp_path):
    """If Celery broker is unavailable, fan-out is skipped gracefully."""
    import shutil
    from unittest.mock import patch

    fixture_copy = tmp_path / "scan_output"
    shutil.copytree(FIXTURE_DIR, fixture_copy)

    from spec2sphere.tasks.chain_tasks import build_chains

    with patch("spec2sphere.tasks.chain_tasks.analyze_single_chain") as mock_analyze:
        mock_analyze.apply_async.side_effect = ConnectionError("no broker")
        result = build_chains.run(
            output_dir=str(fixture_copy),
            scan_id="no-broker",
        )
    assert result["status"] == "completed"
    assert result["analysis_dispatched"] == 0
    assert result["chain_count"] == 3  # chains still built
