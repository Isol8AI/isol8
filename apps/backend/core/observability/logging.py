"""Structured JSON logging with contextvar-based request correlation."""

import contextvars
import json
import logging
import traceback
from datetime import datetime, timezone

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)
container_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("container_id", default=None)

# Fields from LogRecord that are standard/internal and should not be forwarded as extras
_STANDARD_FIELDS = {
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
    """Formats LogRecord as a single JSON line with contextvar fields."""

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": request_id_var.get(),
            "user_id": user_id_var.get(),
            "container_id": container_id_var.get(),
        }

        # Include extra fields
        for key, value in record.__dict__.items():
            if key not in _STANDARD_FIELDS and key not in data:
                try:
                    json.dumps(value)  # only include JSON-serializable extras
                    data[key] = value
                except (TypeError, ValueError):
                    pass

        if record.exc_info and record.exc_info[0] is not None:
            data["exception"] = "".join(traceback.format_exception(*record.exc_info))

        return json.dumps(data)


def configure_logging(level: str = "INFO") -> None:
    """Replace root logger handler with JsonFormatter."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


def bind_request_context(request_id: str, user_id: str | None = None) -> None:
    """Set contextvars for the current async task."""
    request_id_var.set(request_id)
    if user_id is not None:
        user_id_var.set(user_id)
