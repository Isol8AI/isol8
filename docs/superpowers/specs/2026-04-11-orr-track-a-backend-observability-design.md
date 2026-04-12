# ORR Track A — Backend Observability Design

**Status:** Draft
**Date:** 2026-04-11
**Master spec:** [2026-04-11-operational-readiness-review-design.md](./2026-04-11-operational-readiness-review-design.md)
**Parent issue:** Isol8AI/isol8#190
**Branch:** `worktree-track-a-backend-obs` (when teammate runs)

---

## 1. Goal

Add the backend observability foundation (metrics emitter, JSON logging, request-id middleware) and instrument all 49 emit sites listed in the master spec §6. Produce runbook stubs for all 11 page-level alarms. **Does not touch CDK or frontend.**

The success criterion: after this track ships, every metric name in the master spec §6.3 catalog appears in CloudWatch within 1 hour of normal dev traffic, and every backend log line carries a structured `request_id` and `user_id` field.

## 2. Reads (do not duplicate)

- [Master spec §6](./2026-04-11-operational-readiness-review-design.md#6-metric-taxonomy) for the full metric catalog (49 metrics)
- [Master spec §11](./2026-04-11-operational-readiness-review-design.md#11-test-strategy) for the test strategy
- AWS EMF spec: <https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format.html>

**Do not redefine metric names or dimensions in this spec.** They are frozen in the master.

## 3. Architecture

### 3.1 New module: `apps/backend/core/observability/`

Three files:

```
apps/backend/core/observability/
├── __init__.py        # public API exports
├── metrics.py         # EMF emitter
├── logging.py         # JSON formatter + contextvar binding
└── middleware.py      # FastAPI request-id middleware
```

### 3.2 `metrics.py` API

```python
# core/observability/metrics.py

from contextlib import contextmanager
from typing import Iterator

NAMESPACE = "Isol8"  # CloudWatch metrics namespace

def put_metric(
    name: str,
    value: float = 1.0,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
) -> None:
    """
    Emit one metric via EMF (writes a JSON line to stdout that CloudWatch parses).

    Args:
        name: Metric name from the master spec catalog (e.g., "container.provision")
        value: Metric value (default 1.0 for counters)
        unit: CloudWatch unit ("Count", "Milliseconds", "Bytes", etc.)
        dimensions: Bounded-cardinality key/value pairs.
                    `env` and `service` are auto-injected from settings.

    Cardinality discipline: never pass user_id, container_id, or request_id
    here. Those go in structured log context, not metric dimensions.
    """

@contextmanager
def timing(name: str, dimensions: dict[str, str] | None = None) -> Iterator[None]:
    """
    Context manager that emits a `.latency` metric with elapsed milliseconds.

    Usage:
        with timing("container.lifecycle.latency", {"op": "start"}):
            await ecs.start_task(...)
    """

def gauge(name: str, value: float, dimensions: dict[str, str] | None = None) -> None:
    """Emit a gauge value (alias for put_metric with no value default)."""
```

EMF format (one log line per `put_metric` call):

```json
{
  "_aws": {
    "Timestamp": 1712840400000,
    "CloudWatchMetrics": [{
      "Namespace": "Isol8",
      "Dimensions": [["env", "service", "status"]],
      "Metrics": [{"Name": "container.provision", "Unit": "Count"}]
    }]
  },
  "env": "prod",
  "service": "isol8-backend",
  "status": "ok",
  "container.provision": 1
}
```

CloudWatch automatically extracts the metric from any log line containing `_aws.CloudWatchMetrics`.

### 3.3 `logging.py` API

```python
# core/observability/logging.py

import logging
import contextvars

# Contextvars (propagate across asyncio await boundaries)
request_id_var: contextvars.ContextVar[str | None]
user_id_var: contextvars.ContextVar[str | None]
container_id_var: contextvars.ContextVar[str | None]

class JsonFormatter(logging.Formatter):
    """
    Formats LogRecord as a single JSON line with:
      - timestamp (ISO 8601)
      - level
      - logger name
      - message
      - request_id (from contextvar)
      - user_id (from contextvar)
      - container_id (from contextvar)
      - any `extra={}` fields passed to the log call
      - exception info if exc_info=True
    """

def configure_logging(level: str = "INFO") -> None:
    """
    Replace stdlib root logger handler with one that uses JsonFormatter.
    Called once at startup from main.py.
    """

def bind_request_context(request_id: str, user_id: str | None = None) -> None:
    """Set contextvars for the current async task."""
```

### 3.4 `middleware.py` API

```python
# core/observability/middleware.py

import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

class RequestContextMiddleware(BaseHTTPMiddleware):
    """
    For every request:
      1. Read X-Request-ID from incoming headers, or generate a new uuid4
      2. Bind request_id contextvar
      3. Process the request
      4. Add X-Request-ID to the response headers
      5. Emit a metric counting requests by route + status (optional)
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        ...
```

### 3.5 Wiring in `main.py`

```python
# apps/backend/main.py — additions

from core.observability.logging import configure_logging
from core.observability.middleware import RequestContextMiddleware

# At top of file, before app = FastAPI(...)
configure_logging(level=settings.LOG_LEVEL)

# After app creation, before other middleware
app.add_middleware(RequestContextMiddleware)
```

The user_id contextvar is set inside `core/auth.py:get_current_user()` after JWT validation succeeds — this is the only place that knows the user_id.

## 4. Instrumentation work — file by file

For each file below, I list the metric emit sites the teammate must add. Line numbers are approximate (current as of 2026-04-11) — match by surrounding code, not by exact line.

### 4.1 `core/containers/ecs_manager.py`

**Note:** methods in this file are private (underscore-prefixed). Line numbers verified 2026-04-11.

| Site | What to add |
|---|---|
| `_register_task_definition` (~line 130) | `put_metric("container.task_def.register", dimensions={"status": "ok"})` on success; `error` in except branch |
| `_create_access_point` (~line 72) | `put_metric("container.efs.access_point", dimensions={"op": "create", "status": "ok"})` on success; `error` in except |
| `_delete_access_point` (~line 116) | Same pattern with `op=delete` |
| `provision_user_container` (~line 702) | This method is ~160 lines and handles multiple scenarios (no service, service stopped, running, error). Do NOT wrap the entire method in a single `timing`. Instead: emit `container.provision{status=ok}` at the successful return paths and `{status=error}` at each except/error branch. Add `timing("container.lifecycle.latency", {"op": "provision"})` around the inner `_create_service` call specifically. |
| `start_user_service` (~line 352) | Emit `container.lifecycle.state_change{state=starting}`; bracket with `timing` |
| `stop_user_service` (~line 320) | Emit `container.lifecycle.state_change{state=stopping}`; bracket with `timing` |
| Error/stuck state detection (search for `logger.error` calls in status-check paths) | `put_metric("container.error_state")` whenever a stuck/failed state is detected |

### 4.2 `core/gateway/connection_pool.py`

| Site | What to add |
|---|---|
| `connect()` (~line 109) | `put_metric("gateway.connection", dimensions={"event": "connect"})` |
| `close_user()` (~line 872) | `put_metric("gateway.connection", dimensions={"event": "disconnect"})` |
| Health check timeout (~line 180) | `put_metric("gateway.health_check.timeout")` |
| Frontend prune (~lines 78, 282) | `put_metric("gateway.frontend.prune")` per pruned connection |
| Idle scale-to-zero trigger (~line 717) | `put_metric("gateway.idle.scale_to_zero")` |
| RPC error (~line 485) | `put_metric("gateway.rpc.error", dimensions={"method": rpc_method_name})` |
| Reconnect attempt (add new) | `put_metric("gateway.reconnect")` in the reconnect loop |
| **New: open-connection gauge** | Add a periodic task (every 30s) that emits `gauge("gateway.connection.open", count)` from the pool size |

### 4.3 `routers/websocket_chat.py`

| Site | What to add |
|---|---|
| Chat error path (in `_process_agent_chat_background`, ~line 526, exception handlers) | `put_metric("chat.error", dimensions={"reason": <reason>})` — reason from a bounded enum. Note: `chat.message.count` and `chat.e2e.latency` are emitted in `connection_pool.py:_transform_agent_event` (§4.4), NOT here. |

### 4.4 `core/gateway/connection_pool.py` (chat-specific sites)

**Canonical emit decision:** emit `chat.message.count` and `chat.e2e.latency` in `_transform_agent_event` (~line 275) when `chat` state is `"final"`. This is the single source-of-truth for "a chat completed." The router (`websocket_chat.py`) calls `_safe_record_usage` for billing but does NOT emit the chat metric — that avoids double-counting.

| Site | What to add |
|---|---|
| `_transform_agent_event` chat=final (~line 275) | **Canonical site.** Emit `chat.message.count` and `chat.e2e.latency` (compute elapsed from message start timestamp). |
| `_fetch_and_record_usage` (~line 464) on failure | `put_metric("chat.session_usage.fetch.error")` |
| Bedrock throttle propagation | `put_metric("chat.bedrock.throttle")` when an upstream event signals throttle |

### 4.5 `routers/channels.py`

| Site | What to add |
|---|---|
| `get_links_me()` (~line 47) — channel RPC entry | `put_metric("channel.rpc", dimensions={"provider": <provider>, "status": <ok|error>})` |
| Channel configure endpoints (search for `configure` or `PATCH` handlers) | `put_metric("channel.configure", dimensions={"provider": ..., "status": ...})` |
| Inbound webhook (when implemented) | `put_metric("channel.webhook.inbound", dimensions={"provider": ...})` |

### 4.6 `routers/billing.py`

| Site | What to add |
|---|---|
| Stripe webhook entry (~line 304) | `put_metric("stripe.webhook.received", dimensions={"event_type": event.type})`; bracket whole handler with `timing("stripe.subscription.latency", {"event": event.type})` |
| Signature failure | `put_metric("stripe.webhook.sig_fail")` (kept separate from `received` for the dedicated alarm) |
| Idempotency dedup hit (added by Track C, this metric is referenced from there) | `put_metric("stripe.webhook.duplicate")` |
| Subscription created/updated/deleted/payment_failed handlers (~lines 323, 357) | `put_metric("stripe.subscription", dimensions={"event": event_name})` |

### 4.7 `core/services/billing_service.py` (Stripe outbound calls)

For every method that calls `stripe.*.create` / `.update` / etc., wrap with:

```python
with timing("stripe.api.latency", {"op": "customers.create"}):
    try:
        result = stripe.Customer.create(...)
    except stripe.error.StripeError as e:
        put_metric("stripe.api.error", dimensions={"op": "customers.create", "error_code": e.code})
        raise
```

Apply to: `customers.create`, `customers.update`, `checkout.session.create`, `billing_portal.session.create`, `subscriptions.update`, `meter_event.create`, `prices.list`, `products.list` — every Stripe method called from `billing_service.py`. Use the dotted method name as the `op` dimension.

### 4.8 `core/services/usage_service.py`

| Site | What to add |
|---|---|
| `record_usage` (~line 23) on missing model pricing (~line 34) | `put_metric("billing.pricing.missing_model")` |
| `check_budget` (~line 128) on error (any exception in budget check logic) | `put_metric("billing.budget_check.error")` |
| Stripe meter event call (~line 116-123) on failure (~line 124-125 except branch) | `put_metric("stripe.meter_event.fail")` |

### 4.9 `routers/webhooks.py` (Clerk webhook)

| Site | What to add |
|---|---|
| Webhook entry | `put_metric("webhook.clerk.received", dimensions={"event_type": evt.type})` |
| Signature failure | `put_metric("webhook.clerk.sig_fail")` |
| Idempotency dedup hit (added by Track C, metric referenced from there) | `put_metric("webhook.clerk.duplicate")` |

### 4.10 `core/auth.py`

| Site | What to add |
|---|---|
| `get_current_user` (~line 159) exception handlers (~lines 185-198): `ExpiredSignatureError`, `InvalidAudienceError`, `InvalidIssuerError`, `MissingRequiredClaimError`, `HTTPError`, generic `Exception` | `put_metric("auth.jwt.fail", dimensions={"reason": <reason>})` — reason from bounded enum (expired, claims, jwks_unavailable, format, unknown) |
| `_get_cached_jwks` (~line 21): success path (~line 39) and except branch (~line 41-46) | `put_metric("auth.jwks.refresh", dimensions={"status": "ok" or "error"})` |
| `require_org_admin` (~line 99): denied path (~line 102) | `put_metric("auth.org_admin.denied")` |
| `get_current_user` success path (~line 176, after AuthContext is built) | Bind `user_id` contextvar via `bind_request_context(request_id_var.get(), payload["sub"])` |

### 4.11 `core/containers/workspace.py`

| Site | What to add |
|---|---|
| File write error — both `write_file` (~line 405) and `write_bytes` (~line 432) except branches | `put_metric("workspace.file.write.error")` |
| Path traversal metric — **owned by Track C, NOT this track.** Track C rewrites the detection logic in `_resolve_user_file` (~line 114) and emits the metric inline. Track A does nothing here. |

### 4.12 `routers/proxy.py`

| Site | What to add |
|---|---|
| Outbound upstream call | Wrap with `timing("proxy.upstream.latency", {"host": host})`; emit `proxy.upstream{host, status}` |
| Auth fail | `put_metric("proxy.auth.fail")` |
| Budget check fail (Track C re-wires; metric emitted here) | `put_metric("proxy.budget_check.fail")` |

### 4.13 `core/services/update_service.py`

| Site | What to add |
|---|---|
| `run_scheduled_worker` loop top (~line 220) | `put_metric("update.scheduled_worker.heartbeat")` once per iteration |
| Loop except branch | `put_metric("update.scheduled_worker.error")` (do not swallow without metric) |

### 4.14 `routers/updates.py`

| Site | What to add |
|---|---|
| `PATCH /container/config` fleet endpoint (~line 163) | `put_metric("update.fleet_patch.invoked")` (Track C also adds rate-limit + audit log) |
| `PATCH /container/config/{owner_id}` (~line 142) | `put_metric("update.config_patch.applied", dimensions={"scope": "single"})` |
| Fleet patch successful application | `put_metric("update.config_patch.applied", dimensions={"scope": "fleet"})` |

### 4.15 `routers/debug.py`

| Site | What to add |
|---|---|
| Every debug endpoint, on entry, AFTER the env check (Track C adds the check) | `put_metric("debug.endpoint.prod_hit", dimensions={"endpoint": endpoint_name})` ONLY if env is somehow prod (defensive — should never fire) |

### 4.16 DynamoDB throttle metrics

Track C builds the wrapper (`core/services/dynamodb_helper.py`) and emits `dynamodb.throttle` and `dynamodb.error` from inside it. Track A does NOT need to do anything for these metrics — they're listed in §6.3 of the master spec for completeness, but emission is Track C's responsibility because the wrapper is part of the security/reliability story (catching ThrottlingException that previously went unhandled).

## 5. Runbook stubs

Track A creates one stub per page-level alarm (11 files) at `docs/ops/runbooks/`. Use the template in master spec §10. Filename format: `{ID}-{slug}.md`, e.g.:

- `P1-container-error-state.md`
- `P2-stripe-webhook-sig-fail.md`
- `P3-workspace-path-traversal.md`
- `P4-update-fleet-patch-invoked.md`
- `P5-debug-endpoint-prod-hit.md`
- `P6-billing-pricing-missing-model.md`
- `P7-update-worker-stalled.md`
- `P8-dynamodb-throttle-sustained.md`
- `P9-alb-5xx-rate.md`
- `P10-apigw-ws-5xx-rate.md`
- `P11-chat-canary-fail.md`

For each, fill in the "What it means", "Customer impact", and "Immediate actions" sections with the best knowledge available at the time of writing. Leave "Known false positives" blank.

## 6. Test strategy

### Unit tests

Create `apps/backend/tests/observability/`:

- `test_metrics.py`
  - `put_metric` emits well-formed EMF JSON to stdout
  - Auto-injects `env` and `service` dimensions
  - Rejects high-cardinality dimensions (raise ValueError if user_id, container_id, or request_id passed as a dimension key — fail loud during dev)
  - `timing` context manager records elapsed ms
  - `gauge` works
- `test_logging.py`
  - `JsonFormatter` produces single-line JSON
  - Includes contextvar fields
  - Includes `extra={}` fields
  - Handles exceptions
- `test_middleware.py`
  - Generates a request_id when none provided
  - Honors incoming X-Request-ID
  - Adds X-Request-ID to response headers
  - Binds contextvars across the request lifecycle

### Integration test

Add to existing `apps/backend/tests/`:

- `test_observability_integration.py`
  - Spin up the FastAPI app
  - Hit `/health`
  - Assert response has X-Request-ID header
  - Capture the log output, parse as JSON, assert request_id is present
  - Assert at least one EMF line was emitted

### Smoke test (post-deploy)

After deploying to dev:

```bash
# 1. Generate traffic
curl -X GET https://api-dev.isol8.co/health

# 2. Check CloudWatch for metric appearance
aws cloudwatch list-metrics --namespace Isol8 --profile isol8-admin --region us-east-1 | jq '.Metrics[].MetricName' | sort -u
```

Should see the `Isol8` namespace populated. Full coverage requires real chat traffic — kick a manual chat session via the dev frontend and verify `chat.message.count` appears.

## 7. Files affected (summary)

**New files:**
- `apps/backend/core/observability/__init__.py`
- `apps/backend/core/observability/metrics.py`
- `apps/backend/core/observability/logging.py`
- `apps/backend/core/observability/middleware.py`
- `apps/backend/tests/observability/test_metrics.py`
- `apps/backend/tests/observability/test_logging.py`
- `apps/backend/tests/observability/test_middleware.py`
- `apps/backend/tests/test_observability_integration.py`
- `docs/ops/runbooks/P1-container-error-state.md` (and 10 more)

**Modified files:**
- `apps/backend/main.py` — wire middleware and configure_logging
- `apps/backend/core/auth.py` — bind user_id contextvar; emit auth metrics
- `apps/backend/core/containers/ecs_manager.py` — container metrics
- `apps/backend/core/gateway/connection_pool.py` — gateway metrics
- `apps/backend/routers/websocket_chat.py` — chat metrics
- `apps/backend/routers/billing.py` — Stripe webhook metrics
- `apps/backend/routers/channels.py` — channel metrics
- `apps/backend/routers/proxy.py` — proxy metrics
- `apps/backend/routers/updates.py` — update metrics
- `apps/backend/routers/debug.py` — debug metric (defensive)
- `apps/backend/routers/webhooks.py` — Clerk webhook metrics
- `apps/backend/core/services/billing_service.py` — Stripe outbound metrics
- `apps/backend/core/services/usage_service.py` — billing metrics
- `apps/backend/core/services/update_service.py` — worker heartbeat
- `apps/backend/core/containers/workspace.py` — workspace metrics

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Metric explosion (too many dimensions) blows up CloudWatch cost | `put_metric` validates dimensions against a hard cardinality cap; raises in dev, logs+drops in prod |
| EMF JSON pollutes existing log readability | `JsonFormatter` is the universal output format — humans read it via `jq`; CloudWatch parses it natively |
| Missing emit site causes a quiet metric (Track B alarm has no data → "Insufficient data" state) | Smoke test in §6 lists CloudWatch metrics post-deploy; cross-check against §6.3 catalog |
| Track A and Track C both edit the same router files | Track A's edits are additive imports + emit calls. Conflicts at merge are textual, not semantic. Resolve at PR time. |
| `user_id` accidentally passed as a metric dimension | `put_metric` raises ValueError on a denylist of high-cardinality keys |

## 9. Definition of done

- [ ] All 49 metrics from master spec §6.3 emit at the documented sites
- [ ] All 11 runbook stubs exist
- [ ] `JsonFormatter` is the active log formatter (no plain `logging.basicConfig` calls remain)
- [ ] `RequestContextMiddleware` is registered before all routers
- [ ] Every request gets a `request_id` (in logs and response header)
- [ ] `user_id` is bound to logs after `get_current_user` succeeds
- [ ] Unit tests pass
- [ ] Integration test passes
- [ ] Branch builds cleanly under `turbo run lint` and `turbo run test --filter=@isol8/backend`
- [ ] Smoke test post-deploy: `Isol8` namespace appears in CloudWatch

## 10. Open questions for the lead

- None at design time. Anything that comes up mid-implementation gets surfaced via SendMessage to the lead.
