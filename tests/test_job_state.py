import pytest
from unittest.mock import MagicMock
from sap_doc_agent.tasks.job_state import JobState


@pytest.fixture
def mock_redis():
    r = MagicMock()
    r.get.return_value = None
    r.keys.return_value = []
    return r


def test_register_sets_key(mock_redis):
    js = JobState(mock_redis)
    js.register("task-1", "scan", {"system": "DSP"})
    mock_redis.setex.assert_called_once()
    args = mock_redis.setex.call_args[0]
    assert "task-1" in args[0]


def test_get_returns_none_when_missing(mock_redis):
    js = JobState(mock_redis)
    assert js.get("nonexistent") is None


def test_get_returns_parsed_data(mock_redis):
    import json
    import time

    data = {"task_id": "t1", "job_type": "scan", "params": {}, "status": "queued", "created_at": time.time()}
    mock_redis.get.return_value = json.dumps(data).encode()
    js = JobState(mock_redis)
    result = js.get("t1")
    assert result["task_id"] == "t1"
    assert result["status"] == "queued"


def test_update_status(mock_redis):
    import json
    import time

    data = {"task_id": "t2", "job_type": "scan", "params": {}, "status": "queued", "created_at": time.time()}
    mock_redis.get.return_value = json.dumps(data).encode()
    js = JobState(mock_redis)
    js.update_status("t2", "running")
    mock_redis.setex.assert_called()
