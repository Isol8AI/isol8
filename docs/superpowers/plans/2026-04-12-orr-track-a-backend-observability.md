# ORR Track A: Backend Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the observability foundation (EMF metrics, JSON logging, request-id middleware) and instrument all 49 emit sites across the FastAPI backend.

**Architecture:** New `core/observability/` module provides `put_metric()` (EMF emitter), `timing()` (latency context manager), `JsonFormatter` (structured logs), and `RequestContextMiddleware` (request-id injection). Every service/router file gets targeted `put_metric()` calls at the sites listed in the master spec. Runbook stubs created for all 11 page-level alarms.

**Tech Stack:** Python 3.12+, FastAPI, CloudWatch EMF, asyncio contextvars, pytest

**Spec:** `docs/superpowers/specs/2026-04-11-orr-track-a-backend-observability-design.md`
**Master spec:** `docs/superpowers/specs/2026-04-11-operational-readiness-review-design.md` (metric catalog in section 6.3)

---

### Task 1: Create `core/observability/metrics.py` with tests

**Files:**
- Create: `apps/backend/core/observability/__init__.py`
- Create: `apps/backend/core/observability/metrics.py`
- Create: `apps/backend/tests/observability/__init__.py`
- Create: `apps/backend/tests/observability/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/observability/test_metrics.py
import json
import io
import logging
import pytest
from unittest.mock import patch

from core.observability.metrics import put_metric, timing, gauge, NAMESPACE


def test_put_metric_emits_emf_json(capsys):
    """put_metric should emit a single JSON line with _aws.CloudWatchMetrics envelope."""
    put_metric("container.provision", value=1.0, unit="Count", dimensions={"status": "ok"})
    output = capsys.readouterr().out.strip()
    data = json.loads(output)
    assert "_aws" in data
    assert data["_aws"]["CloudWatchMetrics"][0]["Namespace"] == NAMESPACE
    assert data["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Name"] == "container.provision"
    assert data["container.provision"] == 1.0
    assert data["status"] == "ok"


def test_put_metric_auto_injects_env_and_service(capsys):
    """env and service dimensions should be auto-injected."""
    with patch("core.observability.metrics._get_env", return_value="dev"), \
         patch("core.observability.metrics._get_service", return_value="isol8-backend"):
        put_metric("test.metric")
    data = json.loads(capsys.readouterr().out.strip())
    assert data["env"] == "dev"
    assert data["service"] == "isol8-backend"


def test_put_metric_rejects_high_cardinality_dimensions():
    """user_id, container_id, request_id must not be used as metric dimensions."""
    with pytest.raises(ValueError, match="high-cardinality"):
        put_metric("test.metric", dimensions={"user_id": "u123"})
    with pytest.raises(ValueError, match="high-cardinality"):
        put_metric("test.metric", dimensions={"container_id": "c123"})
    with pytest.raises(ValueError, match="high-cardinality"):
        put_metric("test.metric", dimensions={"request_id": "r123"})


def test_timing_context_manager_emits_latency(capsys):
    """timing() should emit a metric with elapsed milliseconds."""
    import time
    with timing("container.lifecycle.latency", {"op": "start"}):
        time.sleep(0.01)  # ~10ms
    data = json.loads(capsys.readouterr().out.strip())
    assert data["_aws"]["CloudWatchMetrics"][0]["Metrics"][0]["Unit"] == "Milliseconds"
    assert data["container.lifecycle.latency"] >= 10  # at least 10ms


def test_gauge_emits_value(capsys):
    """gauge() should emit the given value."""
    gauge("gateway.connection.open", 42)
    data = json.loads(capsys.readouterr().out.strip())
    assert data["gateway.connection.open"] == 42
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/observability/test_metrics.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement metrics.py**

```python
# apps/backend/core/observability/__init__.py
"""Observability module — metrics, logging, and middleware."""

from core.observability.metrics import put_metric, timing, gauge  # noqa: F401
```

```python
# apps/backend/core/observability/metrics.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/observability/test_metrics.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/observability/ apps/backend/tests/observability/
git commit -m "feat(observability): add EMF metric emitter with cardinality guards"
```

---

### Task 2: Create `core/observability/logging.py` with tests

**Files:**
- Create: `apps/backend/core/observability/logging.py`
- Create: `apps/backend/tests/observability/test_logging.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/observability/test_logging.py
import json
import logging
import pytest

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
        record = logging.LogRecord("test", logging.ERROR, "", 0, "fail", (), None, exc_info=True)
        import sys
        record.exc_info = sys.exc_info()
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/observability/test_logging.py -v`
Expected: FAIL (module not found)

- [ ] **Step 3: Implement logging.py**

```python
# apps/backend/core/observability/logging.py
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
    "name", "msg", "args", "created", "relativeCreated", "exc_info", "exc_text",
    "stack_info", "lineno", "funcName", "pathname", "filename", "module",
    "levelno", "levelname", "thread", "threadName", "process", "processName",
    "msecs", "message", "taskName",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd apps/backend && uv run pytest tests/observability/test_logging.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/observability/logging.py apps/backend/tests/observability/test_logging.py
git commit -m "feat(observability): add JSON log formatter with contextvar correlation"
```

---

### Task 3: Create `core/observability/middleware.py` with tests

**Files:**
- Create: `apps/backend/core/observability/middleware.py`
- Create: `apps/backend/tests/observability/test_middleware.py`

- [ ] **Step 1: Write the failing tests**

```python
# apps/backend/tests/observability/test_middleware.py
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.observability.middleware import RequestContextMiddleware, REQUEST_ID_HEADER
from core.observability.logging import request_id_var


def _create_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/test")
    async def test_endpoint():
        return {"request_id": request_id_var.get()}

    return app


def test_middleware_generates_request_id():
    """When no X-Request-ID header, middleware generates one."""
    client = TestClient(_create_app())
    resp = client.get("/test")
    assert resp.status_code == 200
    assert REQUEST_ID_HEADER in resp.headers
    body = resp.json()
    assert body["request_id"] is not None
    assert body["request_id"] == resp.headers[REQUEST_ID_HEADER]


def test_middleware_honors_incoming_request_id():
    """When X-Request-ID is provided, middleware uses it."""
    client = TestClient(_create_app())
    resp = client.get("/test", headers={REQUEST_ID_HEADER: "my-custom-id"})
    assert resp.headers[REQUEST_ID_HEADER] == "my-custom-id"
    assert resp.json()["request_id"] == "my-custom-id"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/observability/test_middleware.py -v`
Expected: FAIL

- [ ] **Step 3: Implement middleware.py**

```python
# apps/backend/core/observability/middleware.py
"""FastAPI middleware for request-id injection and contextvar binding."""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.observability.logging import bind_request_context

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        bind_request_context(request_id)

        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
```

- [ ] **Step 4: Run tests, verify pass. Step 5: Commit.**

```bash
git add apps/backend/core/observability/middleware.py apps/backend/tests/observability/test_middleware.py
git commit -m "feat(observability): add request-id middleware"
```

Update `core/observability/__init__.py` to export middleware:

```python
from core.observability.metrics import put_metric, timing, gauge  # noqa: F401
from core.observability.logging import (  # noqa: F401
    configure_logging,
    bind_request_context,
    request_id_var,
    user_id_var,
    container_id_var,
)
from core.observability.middleware import RequestContextMiddleware  # noqa: F401
```

---

### Task 4: Wire observability into `main.py`

**Files:**
- Modify: `apps/backend/main.py`

- [ ] **Step 1: Read `main.py` to find the current logging setup and middleware registration**

Look for `logging.basicConfig(...)` and the middleware registration order.

- [ ] **Step 2: Replace `logging.basicConfig` with `configure_logging`**

At the top of `main.py`, before the FastAPI app is created:

```python
from core.observability.logging import configure_logging
from core.observability.middleware import RequestContextMiddleware

# Replace: logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
# With:
configure_logging(level="INFO")
```

- [ ] **Step 3: Add RequestContextMiddleware BEFORE other middleware**

After `app = FastAPI(...)`, add:

```python
app.add_middleware(RequestContextMiddleware)
# existing middleware (ProxyHeadersMiddleware, CORSMiddleware) stays below
```

- [ ] **Step 4: Run existing backend tests to verify nothing broke**

Run: `cd apps/backend && uv run pytest tests/ -v --timeout=30`
Expected: All existing tests still pass

- [ ] **Step 5: Commit**

```bash
git add apps/backend/main.py apps/backend/core/observability/__init__.py
git commit -m "feat(observability): wire JSON logging + request-id middleware into main.py"
```

---

### Task 5: Instrument `core/auth.py` — JWT metrics + user_id binding

**Files:**
- Modify: `apps/backend/core/auth.py`

- [ ] **Step 1: Add imports at top of auth.py**

```python
from core.observability.metrics import put_metric
from core.observability.logging import bind_request_context, request_id_var
```

- [ ] **Step 2: Add metrics to `_get_cached_jwks` (~line 21)**

In the success path (~line 39, after `_jwks_cache["data"] = jwks`):
```python
put_metric("auth.jwks.refresh", dimensions={"status": "ok"})
```

In the except branch (~line 41-46):
```python
put_metric("auth.jwks.refresh", dimensions={"status": "error"})
```

- [ ] **Step 3: Add metrics to `get_current_user` (~line 159)**

In the success path (~line 176, after AuthContext is built):
```python
bind_request_context(request_id_var.get() or "", payload["sub"])
```

In each exception handler (~lines 185-198):
```python
# ExpiredSignatureError (line 185):
put_metric("auth.jwt.fail", dimensions={"reason": "expired"})

# InvalidAudienceError/InvalidIssuerError/MissingRequiredClaimError (line 188):
put_metric("auth.jwt.fail", dimensions={"reason": "claims"})

# httpx.HTTPError (line 191):
put_metric("auth.jwt.fail", dimensions={"reason": "jwks_unavailable"})

# Generic Exception (line 196):
put_metric("auth.jwt.fail", dimensions={"reason": "unknown"})
```

- [ ] **Step 4: Add metric to `require_org_admin` (~line 99)**

In the denied path (~line 102, inside the `if` block before `raise`):
```python
put_metric("auth.org_admin.denied")
```

- [ ] **Step 5: Run tests, commit**

```bash
cd apps/backend && uv run pytest tests/ -v --timeout=30
git add apps/backend/core/auth.py
git commit -m "feat(observability): add auth JWT/JWKS metrics + user_id contextvar binding"
```

---

### Task 6: Instrument `core/containers/ecs_manager.py` — container lifecycle

**Files:**
- Modify: `apps/backend/core/containers/ecs_manager.py`

- [ ] **Step 1: Add import**

```python
from core.observability.metrics import put_metric, timing
```

- [ ] **Step 2: Instrument private methods**

Read the file first. Then add to each method:

**`_register_task_definition` (~line 130):** wrap body with `try/except`, emit `put_metric("container.task_def.register", dimensions={"status": "ok"})` on success, `"error"` on except.

**`_create_access_point` (~line 72):** emit `put_metric("container.efs.access_point", dimensions={"op": "create", "status": "ok"})` on success, `"error"` on except.

**`_delete_access_point` (~line 116):** same pattern with `"op": "delete"`.

**`start_user_service` (~line 352):**
```python
put_metric("container.lifecycle.state_change", dimensions={"state": "starting"})
with timing("container.lifecycle.latency", {"op": "start"}):
    # existing start logic
```

**`stop_user_service` (~line 320):**
```python
put_metric("container.lifecycle.state_change", dimensions={"state": "stopping"})
with timing("container.lifecycle.latency", {"op": "stop"}):
    # existing stop logic
```

**`provision_user_container` (~line 702):** emit `put_metric("container.provision", dimensions={"status": "ok"})` at each successful return path. Emit `dimensions={"status": "error"}` at each except/error branch. Wrap the inner `_create_service` call with `timing("container.lifecycle.latency", {"op": "provision"})`.

**Error state detection:** search for `logger.error` calls in status-check paths. At each, add `put_metric("container.error_state")`.

- [ ] **Step 3: Run tests, commit**

```bash
cd apps/backend && uv run pytest tests/ -v --timeout=30
git add apps/backend/core/containers/ecs_manager.py
git commit -m "feat(observability): add container lifecycle metrics to ecs_manager"
```

---

### Task 7: Instrument `core/gateway/connection_pool.py` — gateway metrics

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py`

- [ ] **Step 1: Add import and read the file**

```python
from core.observability.metrics import put_metric, timing, gauge
```

- [ ] **Step 2: Add connection metrics**

**`connect()` (~line 102):** `put_metric("gateway.connection", dimensions={"event": "connect"})`

**`close_user()` (~line 872):** `put_metric("gateway.connection", dimensions={"event": "disconnect"})`

**Health check timeout (~line 180 area):** `put_metric("gateway.health_check.timeout")`

**Frontend prune (search for prune logic):** `put_metric("gateway.frontend.prune")`

**Idle scale-to-zero trigger:** `put_metric("gateway.idle.scale_to_zero")`

**RPC error (~line 485 area):** `put_metric("gateway.rpc.error", dimensions={"method": rpc_method_name})`

**Reconnect attempt:** `put_metric("gateway.reconnect")`

- [ ] **Step 3: Add open-connection gauge (periodic emit)**

Add a periodic task that runs every 30s and emits the current pool size:

```python
import asyncio

async def _emit_connection_gauge(self):
    """Periodically emit the open connection count as a gauge."""
    while True:
        try:
            gauge("gateway.connection.open", len(self._connections))
        except Exception:
            pass
        await asyncio.sleep(30)
```

Start this task in the pool's init or connect method.

- [ ] **Step 4: Add chat metrics (canonical emit site)**

In `_transform_agent_event` (~line 275), when `chat` state is `"final"`:

```python
put_metric("chat.message.count")
# Compute elapsed from when the message was received:
if hasattr(self, '_chat_start_times') and user_id in self._chat_start_times:
    elapsed_ms = (time.time() - self._chat_start_times.pop(user_id)) * 1000
    put_metric("chat.e2e.latency", value=elapsed_ms, unit="Milliseconds")
```

When `chat` state is `"error"`:
```python
put_metric("chat.error", dimensions={"reason": "agent_error"})
```

When `chat` state is `"aborted"`:
```python
put_metric("chat.error", dimensions={"reason": "aborted"})
```

In `_fetch_and_record_usage` (~line 464) on failure:
```python
put_metric("chat.session_usage.fetch.error")
```

- [ ] **Step 5: Run tests, commit**

```bash
cd apps/backend && uv run pytest tests/ -v --timeout=30
git add apps/backend/core/gateway/connection_pool.py
git commit -m "feat(observability): add gateway + chat pipeline metrics"
```

---

### Task 8: Instrument routers — billing, channels, proxy, updates, debug, webhooks

**Files:**
- Modify: `apps/backend/routers/billing.py`
- Modify: `apps/backend/routers/channels.py`
- Modify: `apps/backend/routers/proxy.py`
- Modify: `apps/backend/routers/updates.py`
- Modify: `apps/backend/routers/debug.py`
- Modify: `apps/backend/routers/webhooks.py`
- Modify: `apps/backend/routers/websocket_chat.py`

For each file: read it, add `from core.observability.metrics import put_metric, timing` at the top, then add the metric calls at the sites listed in the Track A spec (sections 4.3, 4.5-4.9, 4.12-4.15).

- [ ] **Step 1: `routers/billing.py`**

At Stripe webhook handler (`handle_stripe_webhook`, ~line 310):
```python
put_metric("stripe.webhook.received", dimensions={"event_type": event.type})
```

At signature failure path:
```python
put_metric("stripe.webhook.sig_fail")
```

Bracket subscription handlers with timing:
```python
with timing("stripe.subscription.latency", {"event": event_type}):
    # existing handler logic
```

At subscription created/updated/deleted/payment_failed:
```python
put_metric("stripe.subscription", dimensions={"event": "created"})  # or updated/deleted/payment_failed
```

- [ ] **Step 2: `routers/channels.py`**

At `get_links_me()` (~line 47):
```python
put_metric("channel.rpc", dimensions={"provider": provider, "status": "ok"})  # or "error" in except
```

At channel configure endpoints:
```python
put_metric("channel.configure", dimensions={"provider": provider, "status": "ok"})
```

- [ ] **Step 3: `routers/proxy.py`**

Wrap upstream call with timing:
```python
with timing("proxy.upstream.latency", {"host": host}):
    response = await httpx_client.request(...)
put_metric("proxy.upstream", dimensions={"host": host, "status": str(response.status_code // 100) + "xx"})
```

Auth fail path: `put_metric("proxy.auth.fail")`

- [ ] **Step 4: `routers/updates.py`**

At `patch_fleet_config()` (~line 169): `put_metric("update.fleet_patch.invoked")`

At `patch_single_config()` (~line 147): `put_metric("update.config_patch.applied", dimensions={"scope": "single"})`

Fleet patch successful application: `put_metric("update.config_patch.applied", dimensions={"scope": "fleet"})`

- [ ] **Step 5: `routers/debug.py`**

At `require_non_production()` (~line 23-26), in the denied path:
```python
put_metric("debug.endpoint.prod_hit", dimensions={"endpoint": "debug"})
```

- [ ] **Step 6: `routers/webhooks.py`**

At webhook entry: `put_metric("webhook.clerk.received", dimensions={"event_type": evt_type})`

At signature failure: `put_metric("webhook.clerk.sig_fail")`

- [ ] **Step 7: `routers/websocket_chat.py`**

At chat error paths in `_process_agent_chat_background` (~line 526):
```python
put_metric("chat.error", dimensions={"reason": "timeout"})  # or "container_unreachable" etc.
```

(Note: `chat.message.count` and `chat.e2e.latency` are emitted in `connection_pool.py`, NOT here.)

- [ ] **Step 8: Run all tests, commit**

```bash
cd apps/backend && uv run pytest tests/ -v --timeout=30
git add apps/backend/routers/
git commit -m "feat(observability): add metrics to all router files"
```

---

### Task 9: Instrument services — billing_service, usage_service, update_service

**Files:**
- Modify: `apps/backend/core/services/billing_service.py`
- Modify: `apps/backend/core/services/usage_service.py`
- Modify: `apps/backend/core/services/update_service.py`

- [ ] **Step 1: `billing_service.py` — wrap all Stripe API calls**

Read the file. For every `stripe.*` call, wrap with timing + error metric:

```python
from core.observability.metrics import put_metric, timing

# Example for Customer.create:
with timing("stripe.api.latency", {"op": "customers.create"}):
    try:
        customer = stripe.Customer.create(...)
    except stripe.error.StripeError as e:
        put_metric("stripe.api.error", dimensions={"op": "customers.create", "error_code": getattr(e, 'code', 'unknown')})
        raise
```

Apply to: `Customer.create` (~line 49), `Customer.delete` (~line 69), `checkout.Session.create` (~line 83), `billing_portal.Session.create` (~line 95).

- [ ] **Step 2: `usage_service.py`**

At `record_usage` (~line 34), missing model pricing:
```python
put_metric("billing.pricing.missing_model")
```

At `check_budget` (~line 128), wrap in try/except and on error:
```python
put_metric("billing.budget_check.error")
```

At Stripe meter event (~line 124-125), on failure:
```python
put_metric("stripe.meter_event.fail")
```

- [ ] **Step 3: `update_service.py`**

At `run_scheduled_worker` loop top:
```python
put_metric("update.scheduled_worker.heartbeat")
```

In the except branch:
```python
put_metric("update.scheduled_worker.error")
```

- [ ] **Step 4: Instrument `workspace.py` file write errors**

At `write_file` (~line 405) and `write_bytes` (~line 432) except branches:
```python
put_metric("workspace.file.write.error")
```

- [ ] **Step 5: Run tests, commit**

```bash
cd apps/backend && uv run pytest tests/ -v --timeout=30
git add apps/backend/core/services/ apps/backend/core/containers/workspace.py
git commit -m "feat(observability): add metrics to services + workspace"
```

---

### Task 10: Create page-level runbook stubs

**Files:**
- Create: `docs/ops/runbooks/P1-container-error-state.md` (and 10 more)

- [ ] **Step 1: Create the runbooks directory and all 11 stubs**

Create each file using the template from the master spec §10. For each alarm:

| File | Alarm | What it means | Customer impact | Immediate action |
|---|---|---|---|---|
| `P1-container-error-state.md` | container.error_state > 0 | A user's OpenClaw container is stuck | User can't chat | Check ECS console for stuck tasks; force-stop and reprovision |
| `P2-stripe-webhook-sig-fail.md` | stripe.webhook.sig_fail > 0 | Stripe webhook signature invalid | Billing events may be lost | Check webhook secret rotation; verify Stripe dashboard |
| `P3-workspace-path-traversal.md` | workspace.path_traversal.attempt > 0 | Path traversal attempt blocked | None (blocked) — security event | Investigate source IP/user; potential attack |
| `P4-update-fleet-patch-invoked.md` | update.fleet_patch.invoked > 0 | Fleet-wide config patch was run | All users' configs changed | Verify the patch was intentional; check audit log |
| `P5-debug-endpoint-prod-hit.md` | debug.endpoint.prod_hit > 0 | Debug endpoint hit in production | Possible unauthorized access | Should be 403'd; investigate how it was reached |
| `P6-billing-pricing-missing-model.md` | billing.pricing.missing_model > 0 | Chat used a model with no pricing | User not billed correctly | Add pricing row for the model; backfill if needed |
| `P7-update-worker-stalled.md` | heartbeat absent 5 min | Background update worker stopped | Pending updates not applied | Check ECS task logs; restart service |
| `P8-dynamodb-throttle-sustained.md` | dynamodb.throttle > 0, 2 consecutive min | DynamoDB throttling requests | Degraded performance | Check table capacity; enable auto-scaling |
| `P9-alb-5xx-rate.md` | ALB 5xx > 5% for 5 min | Backend returning server errors | Users see errors | Check backend logs; recent deploy? rollback if needed |
| `P10-apigw-ws-5xx-rate.md` | API GW WS 5xx > 5% for 5 min | WebSocket API errors | Chat disconnects | Check Lambda authorizer; NLB health |
| `P11-chat-canary-fail.md` | Canary fails 2-of-3 | End-to-end chat is broken | Users can't chat | Full incident: check ALB, API GW, containers, Bedrock |

- [ ] **Step 2: Commit**

```bash
git add docs/ops/runbooks/
git commit -m "docs: add runbook stubs for all 11 page-level alarms"
```

---

### Task 11: Integration test + final verification

**Files:**
- Create: `apps/backend/tests/test_observability_integration.py`

- [ ] **Step 1: Write integration test**

```python
# apps/backend/tests/test_observability_integration.py
import json
from fastapi.testclient import TestClient
from main import app


def test_health_returns_request_id():
    """Health endpoint should return X-Request-ID header."""
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert "X-Request-ID" in resp.headers
    assert len(resp.headers["X-Request-ID"]) > 0
```

- [ ] **Step 2: Run full test suite**

```bash
cd apps/backend && uv run pytest tests/ -v --timeout=30
```

Expected: All tests pass including the new observability tests.

- [ ] **Step 3: Run linting**

```bash
cd apps/backend && uv run ruff check . && uv run ruff format --check .
```

Fix any linting issues.

- [ ] **Step 4: Final commit**

```bash
git add .
git commit -m "test(observability): add integration test, all 49 metrics instrumented"
```

- [ ] **Step 5: Report to lead**

SendMessage to the team lead with:
- Branch name
- Summary of work done
- Test results
- Any metrics that couldn't be instrumented (with reason)
- Any deviations from the spec
