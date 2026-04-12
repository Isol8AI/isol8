"""Structured JSON logging with contextvar-based request correlation.

Replaces the default plaintext log format with single-line JSON. Every
log line automatically includes request_id and user_id from contextvars,
so you can trace a request across all log entries without passing IDs
around explicitly.

Usage:
    from core.observability.logging import configure_logging, bind_request_context

    # At startup (replaces logging.basicConfig):
    configure_logging(level="INFO")

    # Per-request (called by middleware or auth):
    bind_request_context(request_id="abc-123", user_id="user_456")

    # Then any logger.info("...") call includes request_id + user_id automatically.
"""

import contextvars
import json
import logging
import traceback
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)

# Standard LogRecord attributes we don't want to forward as extras
_SKIP_FIELDS = {
    "name",
    "msg",
    "args",
    "created",
    "relativeCreated",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "pathname",
    "filename",
    "module",
    "levelno",
    "levelname",
    "thread",
    "threadName",
    "process",
    "processName",
    "msecs",
    "message",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Formats each LogRecord as a single JSON line.

    Includes:
      - timestamp, level, logger name, message
      - request_id and user_id from contextvars (if set)
      - any extra={} fields passed to the log call
      - exception traceback (if present)
    """

    def format(self, record: logging.LogRecord) -> str:
        data: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
        }

        # Forward any extra fields the caller passed
        for key, value in record.__dict__.items():
            if key not in _SKIP_FIELDS and key not in data:
                try:
                    json.dumps(value)  # only include JSON-serializable values
                    data[key] = value
                except (TypeError, ValueError):
                    pass

        if record.exc_info and record.exc_info[0] is not None:
            data["exception"] = "".join(traceback.format_exception(*record.exc_info))

        return json.dumps(data)


def configure_logging(level: str = "INFO") -> None:
    """Replace the root logger's handlers with a single JsonFormatter handler.

    Call this once at startup, BEFORE any other logging calls.
    Replaces: logging.basicConfig(level=..., format="%(asctime)s ...")
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def bind_request_context(request_id: str, user_id: str | None = None) -> None:
    """Set contextvars for the current async task.

    Called by the request-id middleware (sets request_id) and by
    get_current_user in auth.py (sets user_id after JWT validation).
    """
    request_id_var.set(request_id)
    if user_id is not None:
        user_id_var.set(user_id)
