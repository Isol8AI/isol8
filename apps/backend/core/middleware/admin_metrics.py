"""AdminMetricsMiddleware — emit admin_api.* CloudWatch metrics for /admin/* requests.

Per CEO review O1 (#351): every request under /api/v1/admin/* emits two
metrics (call_count + latency_ms), tagged with the endpoint path and the
admin's Clerk user_id. 5xx responses additionally emit admin_api.errors
tagged with endpoint + status code.

Non-admin paths pass through with zero metric emission. Metric emission
errors are swallowed — a metrics outage must not double-fail the request.

Note on cardinality: `endpoint` uses the FastAPI route pattern when
available (e.g. /api/v1/admin/users/{user_id}/agents) so {user_id} doesn't
explode the dimension space. Falls back to raw path if the route hasn't
been matched yet.
"""

import logging
import time
from typing import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.observability.metrics import put_metric

logger = logging.getLogger(__name__)

_ADMIN_PREFIX = "/api/v1/admin/"


def _endpoint_label(request: Request) -> str:
    """Prefer the matched route template to bound dimension cardinality."""
    route = request.scope.get("route")
    if route is not None and hasattr(route, "path"):
        return route.path
    return request.url.path


def _admin_user_id(request: Request) -> str:
    """Pull the admin's user_id from request.state if a prior dependency set it.

    Defaults to "unknown" since the metric runs at middleware time —
    earlier than the auth dependency that would set state.
    """
    return getattr(request.state, "admin_user_id", None) or "unknown"


class AdminMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not request.url.path.startswith(_ADMIN_PREFIX):
            return await call_next(request)

        started = time.monotonic()
        status_code = 500
        response: Response | None = None
        exc: BaseException | None = None

        try:
            response = await call_next(request)
            status_code = response.status_code
        except BaseException as e:  # noqa: BLE001 — re-raised after metrics
            exc = e

        elapsed_ms = (time.monotonic() - started) * 1000.0
        endpoint = _endpoint_label(request)
        admin_user_id = _admin_user_id(request)
        base_dims = {"endpoint": endpoint, "admin_user_id": admin_user_id}

        try:
            put_metric("admin_api.call_count", value=1, unit="Count", dimensions=base_dims)
            put_metric("admin_api.latency_ms", value=elapsed_ms, unit="Milliseconds", dimensions=base_dims)
            if status_code >= 500:
                put_metric(
                    "admin_api.errors",
                    value=1,
                    unit="Count",
                    dimensions={"endpoint": endpoint, "code": str(status_code)},
                )
        except Exception as metric_exc:  # noqa: BLE001 — never break the request on metric failure
            logger.warning("admin_metrics emission failed: %s", metric_exc)

        if exc is not None:
            raise exc
        return response  # type: ignore[return-value]
