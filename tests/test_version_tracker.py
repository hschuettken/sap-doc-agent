"""Tests for version_tracker module.

DB-dependent async functions (create_scan_run, complete_scan_run, etc.) are
tested for import correctness and signature only.  The pure-logic portions of
diff_versions (field diff assembly) are tested via mock snapshots so no DB
connection is required.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4


# ---------------------------------------------------------------------------
# Import / callable guards
# ---------------------------------------------------------------------------


def test_version_tracker_imports():
    """All public functions import cleanly and are callable."""
    from spec2sphere.core.scanner.version_tracker import (
        complete_scan_run,
        create_scan_run,
        diff_versions,
        get_object_history,
        get_scan_runs,
        snapshot_object,
    )

    assert callable(create_scan_run)
    assert callable(complete_scan_run)
    assert callable(snapshot_object)
    assert callable(get_object_history)
    assert callable(diff_versions)
    assert callable(get_scan_runs)


def test_additional_functions_importable():
    """fail_scan_run and get_object_at_version are also importable."""
    from spec2sphere.core.scanner.version_tracker import (
        fail_scan_run,
        get_object_at_version,
    )

    assert callable(fail_scan_run)
    assert callable(get_object_at_version)


# ---------------------------------------------------------------------------
# Function signature checks (no DB needed)
# ---------------------------------------------------------------------------


def test_create_scan_run_signature():
    """create_scan_run accepts (customer_id, project_id, scanner_type, scan_config)."""
    import inspect

    from spec2sphere.core.scanner.version_tracker import create_scan_run

    sig = inspect.signature(create_scan_run)
    params = list(sig.parameters.keys())
    assert "customer_id" in params
    assert "project_id" in params
    assert "scanner_type" in params
    assert "scan_config" in params


def test_complete_scan_run_signature():
    """complete_scan_run accepts (run_id, stats, change_summary)."""
    import inspect

    from spec2sphere.core.scanner.version_tracker import complete_scan_run

    sig = inspect.signature(complete_scan_run)
    params = list(sig.parameters.keys())
    assert "run_id" in params
    assert "stats" in params
    assert "change_summary" in params


def test_snapshot_object_signature():
    """snapshot_object accepts a connection as first arg plus object/run ids."""
    import inspect

    from spec2sphere.core.scanner.version_tracker import snapshot_object

    sig = inspect.signature(snapshot_object)
    params = list(sig.parameters.keys())
    assert "conn" in params
    assert "landscape_object_id" in params
    assert "scan_run_id" in params
    assert "change_type" in params


def test_diff_versions_signature():
    """diff_versions accepts (landscape_object_id, version_a, version_b)."""
    import inspect

    from spec2sphere.core.scanner.version_tracker import diff_versions

    sig = inspect.signature(diff_versions)
    params = list(sig.parameters.keys())
    assert "landscape_object_id" in params
    assert "version_a" in params
    assert "version_b" in params


def test_get_scan_runs_signature():
    """get_scan_runs accepts (customer_id, project_id, limit)."""
    import inspect

    from spec2sphere.core.scanner.version_tracker import get_scan_runs

    sig = inspect.signature(get_scan_runs)
    params = list(sig.parameters.keys())
    assert "customer_id" in params
    assert "project_id" in params
    assert "limit" in params


# ---------------------------------------------------------------------------
# diff_versions logic via mocked DB calls
# ---------------------------------------------------------------------------


async def _make_diff_result(snap_a: dict, snap_b: dict) -> dict:
    """Run diff_versions with two mocked snapshots, no real DB."""
    from spec2sphere.core.scanner.version_tracker import diff_versions

    obj_id = uuid4()
    mock_a = {"snapshot": snap_a, "version_number": 1}
    mock_b = {"snapshot": snap_b, "version_number": 2}

    with patch(
        "spec2sphere.core.scanner.version_tracker.get_object_at_version",
        new=AsyncMock(side_effect=[mock_a, mock_b]),
    ):
        return await diff_versions(obj_id, 1, 2)


import pytest


@pytest.mark.asyncio
async def test_diff_no_changes():
    """Identical snapshots produce empty diff."""
    snap = {
        "object_name": "SalesView",
        "platform": "dsp",
        "fields": [{"field_name": "AMOUNT", "data_type": "DECIMAL"}],
    }
    result = await _make_diff_result(snap, snap.copy())
    assert result["object_changes"] == {}
    assert result["fields_added"] == []
    assert result["fields_removed"] == []
    assert result["fields_modified"] == []


@pytest.mark.asyncio
async def test_diff_field_added():
    """New field in version B shows up in fields_added (as full field dict)."""
    snap_a = {
        "object_name": "SalesView",
        "platform": "dsp",
        "fields": [{"field_name": "AMOUNT", "data_type": "DECIMAL"}],
    }
    snap_b = {
        "object_name": "SalesView",
        "platform": "dsp",
        "fields": [
            {"field_name": "AMOUNT", "data_type": "DECIMAL"},
            {"field_name": "CURRENCY", "data_type": "CHAR(5)"},
        ],
    }
    result = await _make_diff_result(snap_a, snap_b)
    # fields_added contains full dicts, not just names
    added_names = [f["field_name"] for f in result["fields_added"]]
    assert "CURRENCY" in added_names
    assert result["fields_removed"] == []


@pytest.mark.asyncio
async def test_diff_field_removed():
    """Field absent in version B appears in fields_removed."""
    snap_a = {
        "object_name": "SalesView",
        "platform": "dsp",
        "fields": [
            {"field_name": "AMOUNT", "data_type": "DECIMAL"},
            {"field_name": "LEGACY", "data_type": "VARCHAR"},
        ],
    }
    snap_b = {
        "object_name": "SalesView",
        "platform": "dsp",
        "fields": [{"field_name": "AMOUNT", "data_type": "DECIMAL"}],
    }
    result = await _make_diff_result(snap_a, snap_b)
    assert "LEGACY" in [f["field_name"] for f in result["fields_removed"]]
    assert result["fields_added"] == []


@pytest.mark.asyncio
async def test_diff_field_modified():
    """Changed field attribute appears in fields_modified."""
    snap_a = {
        "object_name": "SalesView",
        "platform": "dsp",
        "fields": [{"field_name": "AMOUNT", "data_type": "DECIMAL", "is_key": False}],
    }
    snap_b = {
        "object_name": "SalesView",
        "platform": "dsp",
        "fields": [{"field_name": "AMOUNT", "data_type": "DECIMAL(17,2)", "is_key": False}],
    }
    result = await _make_diff_result(snap_a, snap_b)
    assert len(result["fields_modified"]) == 1
    mod = result["fields_modified"][0]
    assert mod["field_name"] == "AMOUNT"
    assert "data_type" in mod["changes"]
    assert mod["changes"]["data_type"]["old"] == "DECIMAL"
    assert mod["changes"]["data_type"]["new"] == "DECIMAL(17,2)"


@pytest.mark.asyncio
async def test_diff_object_level_change():
    """Change to object_name at top level shows in object_changes."""
    snap_a = {
        "object_name": "OldName",
        "platform": "dsp",
        "fields": [],
    }
    snap_b = {
        "object_name": "NewName",
        "platform": "dsp",
        "fields": [],
    }
    result = await _make_diff_result(snap_a, snap_b)
    assert "object_name" in result["object_changes"]
    assert result["object_changes"]["object_name"]["old"] == "OldName"
    assert result["object_changes"]["object_name"]["new"] == "NewName"


@pytest.mark.asyncio
async def test_diff_skip_keys_excluded():
    """last_scanned, content_hash, and fields are excluded from object_changes."""
    snap_a = {
        "object_name": "View",
        "platform": "dsp",
        "last_scanned": "2024-01-01T00:00:00",
        "content_hash": "abc123",
        "fields": [],
    }
    snap_b = {
        "object_name": "View",
        "platform": "dsp",
        "last_scanned": "2024-02-01T00:00:00",
        "content_hash": "def456",
        "fields": [],
    }
    result = await _make_diff_result(snap_a, snap_b)
    # These skip keys must NOT appear in object_changes
    assert "last_scanned" not in result["object_changes"]
    assert "content_hash" not in result["object_changes"]
    assert "fields" not in result["object_changes"]


@pytest.mark.asyncio
async def test_diff_missing_version_returns_error():
    """diff_versions returns error dict when a version snapshot is not found."""
    from spec2sphere.core.scanner.version_tracker import diff_versions

    obj_id = uuid4()
    with patch(
        "spec2sphere.core.scanner.version_tracker.get_object_at_version",
        new=AsyncMock(return_value=None),
    ):
        result = await diff_versions(obj_id, 1, 2)
    assert "error" in result
    assert "1" in result["error"]
    assert "2" in result["error"]


@pytest.mark.asyncio
async def test_diff_one_missing_version():
    """Only one version missing: error mentions just that version."""
    from spec2sphere.core.scanner.version_tracker import diff_versions

    obj_id = uuid4()
    snap_a = {"object_name": "V", "platform": "dsp", "fields": []}

    with patch(
        "spec2sphere.core.scanner.version_tracker.get_object_at_version",
        new=AsyncMock(side_effect=[{"snapshot": snap_a}, None]),
    ):
        result = await diff_versions(obj_id, 1, 99)
    assert "error" in result
    assert "99" in result["error"]


# ---------------------------------------------------------------------------
# get_object_history accepts string UUID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_object_history_accepts_string_uuid():
    """get_object_history converts string UUID to UUID without error."""
    from spec2sphere.core.scanner.version_tracker import get_object_history

    obj_id = str(uuid4())
    mock_conn = AsyncMock()
    mock_conn.fetch = AsyncMock(return_value=[])

    with patch("spec2sphere.core.scanner.version_tracker._get_conn", new=AsyncMock(return_value=mock_conn)):
        result = await get_object_history(obj_id, limit=5)
    assert result == []
    # Verify fetch was called — the string was accepted and converted
    mock_conn.fetch.assert_called_once()


# ---------------------------------------------------------------------------
# create_scan_run passes json-serialised scan_config
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_scan_run_serializes_config():
    """create_scan_run calls INSERT with JSON-encoded scan_config."""
    from spec2sphere.core.scanner.version_tracker import create_scan_run

    customer_id = uuid4()
    run_id = uuid4()
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value={"id": run_id})

    with patch("spec2sphere.core.scanner.version_tracker._get_conn", new=AsyncMock(return_value=mock_conn)):
        result = await create_scan_run(
            customer_id=customer_id,
            project_id=None,
            scanner_type="dsp",
            scan_config={"url": "https://example.com", "depth": 3},
        )
    assert result == run_id
    # Verify fetchrow called once (the INSERT RETURNING)
    mock_conn.fetchrow.assert_called_once()
    call_args = mock_conn.fetchrow.call_args
    # Third positional arg is scanner_type, fourth is the JSON-encoded config
    positional = call_args[0]
    assert "dsp" in positional
    import json

    config_arg = next(a for a in positional if isinstance(a, str) and a.startswith("{"))
    parsed = json.loads(config_arg)
    assert parsed["url"] == "https://example.com"
    assert parsed["depth"] == 3


# ---------------------------------------------------------------------------
# complete_scan_run updates status to 'completed'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_complete_scan_run_calls_execute():
    """complete_scan_run calls conn.execute with 'completed' status."""
    from spec2sphere.core.scanner.version_tracker import complete_scan_run

    run_id = uuid4()
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=None)

    with patch("spec2sphere.core.scanner.version_tracker._get_conn", new=AsyncMock(return_value=mock_conn)):
        await complete_scan_run(run_id=run_id, stats={"objects": 10}, change_summary={"new": 3})

    mock_conn.execute.assert_called_once()
    sql_called = mock_conn.execute.call_args[0][0]
    assert "completed" in sql_called
    assert run_id in mock_conn.execute.call_args[0]
