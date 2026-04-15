import json
import logging

from spec2sphere.logging import JSONFormatter


def test_json_formatter_output():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0, msg="test message", args=(), exc_info=None
    )
    output = formatter.format(record)
    data = json.loads(output)
    assert data["message"] == "test message"
    assert data["level"] == "INFO"
    assert "timestamp" in data
    assert "logger" in data


def test_json_formatter_with_correlation_id():
    formatter = JSONFormatter()
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname="", lineno=0, msg="msg", args=(), exc_info=None
    )
    record.correlation_id = "abc-123"
    output = formatter.format(record)
    data = json.loads(output)
    assert data["correlation_id"] == "abc-123"
