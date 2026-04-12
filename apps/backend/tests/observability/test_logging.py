import json
import logging
import sys

from core.observability.logging import (
    JsonFormatter,
    configure_logging,
    bind_request_context,
    request_id_var,
    user_id_var,
    container_id_var,
)


def test_json_formatter_outputs_single_line():
    """Log output should be a single parseable JSON line."""
    formatter = JsonFormatter()
    record = logging.LogRecord("test", logging.INFO, "", 0, "hello world", (), None)
    output = formatter.format(record)
    data = json.loads(output)
    assert data["message"] == "hello world"
    assert data["level"] == "INFO"
    assert "timestamp" in data


def test_json_formatter_includes_contextvars():
    """request_id and user_id from contextvars should appear in output."""
    formatter = JsonFormatter()
    token_r = request_id_var.set("req-123")
    token_u = user_id_var.set("user-456")
    try:
        record = logging.LogRecord("test", logging.INFO, "", 0, "test", (), None)
        data = json.loads(formatter.format(record))
        assert data["request_id"] == "req-123"
        assert data["user_id"] == "user-456"
    finally:
        request_id_var.reset(token_r)
        user_id_var.reset(token_u)


def test_json_formatter_includes_extra_fields():
    """Extra fields passed via log call should appear in output."""
    formatter = JsonFormatter()
    record = logging.LogRecord("test", logging.INFO, "", 0, "test", (), None)
    record.action = "fleet_patch"
    data = json.loads(formatter.format(record))
    assert data["action"] == "fleet_patch"


def test_json_formatter_handles_exceptions():
    """Exception info should be included when present."""
    formatter = JsonFormatter()
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
        record = logging.LogRecord("test", logging.ERROR, "", 0, "fail", (), exc_info)
    data = json.loads(formatter.format(record))
    assert "exception" in data
    assert "ValueError" in data["exception"]


def test_bind_request_context():
    """bind_request_context should set contextvars."""
    bind_request_context("req-abc", "user-xyz")
    assert request_id_var.get() == "req-abc"
    assert user_id_var.get() == "user-xyz"
    # cleanup
    request_id_var.set(None)
    user_id_var.set(None)
