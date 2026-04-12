"""CloudWatch Embedded Metric Format (EMF) emitter.

Emits metrics as JSON log lines with _aws.CloudWatchMetrics envelope.
CloudWatch automatically extracts metrics from the log stream.
"""

import json
import sys
import time
from contextlib import contextmanager
from typing import Iterator

from core.config import settings

NAMESPACE = "Isol8"

# Dimensions that must NOT be used as metric dimensions (high cardinality).
_DENIED_DIMENSIONS = {"user_id", "container_id", "request_id", "owner_id"}


def _get_env() -> str:
    return (settings.ENVIRONMENT or "dev").lower()


def _get_service() -> str:
    return "isol8-backend"


def put_metric(
    name: str,
    value: float = 1.0,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
) -> None:
    """Emit one metric via EMF."""
    dims = dimensions or {}

    # Cardinality guard
    bad_keys = _DENIED_DIMENSIONS & set(dims.keys())
    if bad_keys:
        raise ValueError(
            f"high-cardinality dimension(s) {bad_keys} must not be used as metric dimensions; "
            "put them in structured log fields instead"
        )

    # Auto-inject standard dimensions
    all_dims = {"env": _get_env(), "service": _get_service(), **dims}
    dim_keys = list(all_dims.keys())

    emf = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": NAMESPACE,
                    "Dimensions": [dim_keys],
                    "Metrics": [{"Name": name, "Unit": unit}],
                }
            ],
        },
        name: value,
        **all_dims,
    }
    print(json.dumps(emf), file=sys.stdout, flush=True)


@contextmanager
def timing(name: str, dimensions: dict[str, str] | None = None) -> Iterator[None]:
    """Context manager that emits a latency metric with elapsed milliseconds."""
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000
        put_metric(name, value=elapsed_ms, unit="Milliseconds", dimensions=dimensions)


def gauge(name: str, value: float, dimensions: dict[str, str] | None = None) -> None:
    """Emit a gauge value."""
    put_metric(name, value=value, unit="Count", dimensions=dimensions)
