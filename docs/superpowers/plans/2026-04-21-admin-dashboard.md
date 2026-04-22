# admin.isol8.co — Internal Admin Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read + safe-actions admin surface at `admin.isol8.co` with inline CloudWatch log viewer, PostHog activity, full Clerk/Stripe/DDB/gateway aggregation, every write audited forever, and `/admin/health` answering "is the platform OK right now?"

**Architecture:** Admin surface is a **route group inside `apps/frontend/`** gated by host-based middleware. Cloudflare Access fronts the subdomain. Backend enforces via `Depends(require_platform_admin)` (existing, driven by `PLATFORM_ADMIN_USER_IDS` env var). Server Components by default; Server Actions for writes; ESLint import-boundary rule keeps admin code out of the public bundle.

**Tech Stack:** Next.js 16 App Router + React 19 (existing frontend), FastAPI (backend), AWS CDK (infra), DynamoDB (audit), CloudWatch Logs API (inline viewer), Clerk Backend API, Stripe API, PostHog Persons API, boto3, pytest + vitest + Playwright.

**Spec:** [`docs/superpowers/specs/2026-04-21-admin-dashboard-design.md`](../specs/2026-04-21-admin-dashboard-design.md)

**Tracking issue:** [Isol8AI/isol8#351](https://github.com/Isol8AI/issue/351)

**Scope:** v1 per CEO review (HOLD SCOPE, 2026-04-21). 18 must-fix items from the review are threaded through the tasks below. 8 scope-addition candidates (rate-limit, 2FA, correlation IDs, Slack alerts, two-person rule, per-user notes, stripe webhook log, full CWL search UI) are deferred to Phase 2.

---

## File structure

**New backend files:**
- `apps/backend/core/services/admin_service.py` — composition layer (reads from existing services)
- `apps/backend/core/services/admin_audit.py` — `@audit_admin_action` decorator with fail-closed semantics
- `apps/backend/core/services/cloudwatch_logs.py` — FilterLogEvents wrapper with pagination
- `apps/backend/core/services/cloudwatch_url.py` — Insights URL builder
- `apps/backend/core/services/posthog_admin.py` — Persons API client
- `apps/backend/core/services/system_health.py` — /admin/health aggregator
- `apps/backend/core/services/admin_redact.py` — openclaw.json secret redaction allowlist
- `apps/backend/core/repositories/admin_actions_repo.py` — DDB CRUD
- `apps/backend/core/middleware/admin_metrics.py` — per-endpoint CloudWatch metrics
- `apps/backend/routers/admin.py` — `/api/v1/admin/*` router
- `apps/backend/tests/unit/services/test_admin_service.py`
- `apps/backend/tests/unit/services/test_admin_audit.py`
- `apps/backend/tests/unit/services/test_cloudwatch_logs.py`
- `apps/backend/tests/unit/services/test_cloudwatch_url.py`
- `apps/backend/tests/unit/services/test_posthog_admin.py`
- `apps/backend/tests/unit/services/test_system_health.py`
- `apps/backend/tests/unit/services/test_admin_redact.py`
- `apps/backend/tests/unit/repositories/test_admin_actions_repo.py`
- `apps/backend/tests/unit/routers/test_admin.py`

**Modified backend files:**
- `apps/backend/core/config.py` — add `POSTHOG_HOST`, `POSTHOG_PROJECT_ID`, `POSTHOG_PROJECT_API_KEY`, `ADMIN_UI_ENABLED`, `ADMIN_UI_ENABLED_USER_IDS`, `ADMIN_AUDIT_VIEWS` settings
- `apps/backend/main.py` — register `admin` router + wire `admin_metrics` middleware

**New frontend files:**
- `apps/frontend/src/app/admin/layout.tsx`
- `apps/frontend/src/app/admin/page.tsx`
- `apps/frontend/src/app/admin/not-authorized/page.tsx`
- `apps/frontend/src/app/admin/health/page.tsx`
- `apps/frontend/src/app/admin/users/page.tsx`
- `apps/frontend/src/app/admin/users/[id]/layout.tsx`
- `apps/frontend/src/app/admin/users/[id]/page.tsx`
- `apps/frontend/src/app/admin/users/[id]/agents/page.tsx`
- `apps/frontend/src/app/admin/users/[id]/agents/[agent_id]/page.tsx`
- `apps/frontend/src/app/admin/users/[id]/billing/page.tsx`
- `apps/frontend/src/app/admin/users/[id]/container/page.tsx`
- `apps/frontend/src/app/admin/users/[id]/activity/page.tsx`
- `apps/frontend/src/app/admin/users/[id]/actions/page.tsx`
- `apps/frontend/src/app/admin/_actions/container.ts`
- `apps/frontend/src/app/admin/_actions/billing.ts`
- `apps/frontend/src/app/admin/_actions/account.ts`
- `apps/frontend/src/app/admin/_actions/config.ts`
- `apps/frontend/src/app/admin/_actions/agent.ts`
- `apps/frontend/src/app/admin/_lib/api.ts`
- `apps/frontend/src/app/admin/_lib/redact.ts`
- `apps/frontend/src/components/admin/ConfirmActionDialog.tsx`
- `apps/frontend/src/components/admin/CodeBlock.tsx`
- `apps/frontend/src/components/admin/AuditRow.tsx`
- `apps/frontend/src/components/admin/UserSearchInput.tsx`
- `apps/frontend/src/components/admin/EmptyState.tsx`
- `apps/frontend/src/components/admin/ErrorBanner.tsx`
- `apps/frontend/src/components/admin/LogRow.tsx`
- `apps/frontend/tests/unit/admin/middleware.test.ts`
- `apps/frontend/tests/unit/admin/ConfirmActionDialog.test.tsx`
- `apps/frontend/tests/unit/admin/LogRow.test.tsx`
- `apps/frontend/tests/e2e/admin.spec.ts`

**Modified frontend files:**
- `apps/frontend/src/middleware.ts` — host-based gating of `/admin/*`
- `apps/frontend/.eslintrc.cjs` (or `eslint.config.mjs`) — import-boundary rule
- `apps/frontend/package.json` — add `eslint-plugin-boundaries`

**New infra files:**
- (modify) `apps/infra/lib/stacks/database-stack.ts` — `admin-actions` DDB table
- (modify) `apps/infra/lib/stacks/service-stack.ts` — IAM additions for CloudWatch Logs

**New scripts / docs:**
- `docs/runbooks/admin-cloudflare-access-rollout.md` — CF Access staged rollout
- `docs/runbooks/admin-local-dev.md` — how to run the admin UI locally

---

## Phase A — Infrastructure

### Task 1: Provision the `admin-actions` DynamoDB table

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`

- [ ] **Step 1: Write a snapshot test for the CDK stack**

Extend `apps/infra/tests/database-stack.test.ts` (or wherever stack tests live) with an assertion that the synthesized template includes a DynamoDB table with:
- `TableName: isol8-{env}-admin-actions`
- `KeySchema: [{AttributeName: "admin_user_id", KeyType: "HASH"}, {AttributeName: "timestamp_action_id", KeyType: "RANGE"}]`
- One GSI: `target-timestamp-index` with `target_user_id` as HASH and `timestamp_action_id` as RANGE
- `BillingMode: PAY_PER_REQUEST`
- No TTL specification

- [ ] **Step 2: Add the table to the stack**

In `apps/infra/lib/stacks/database-stack.ts`, next to the other 8 `isol8-{env}-*` tables:

```ts
this.adminActionsTable = new dynamodb.Table(this, 'AdminActionsTable', {
  tableName: `isol8-${props.env}-admin-actions`,
  partitionKey: { name: 'admin_user_id', type: dynamodb.AttributeType.STRING },
  sortKey: { name: 'timestamp_action_id', type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: cdk.RemovalPolicy.RETAIN,
  pointInTimeRecovery: true,
});

this.adminActionsTable.addGlobalSecondaryIndex({
  indexName: 'target-timestamp-index',
  partitionKey: { name: 'target_user_id', type: dynamodb.AttributeType.STRING },
  sortKey: { name: 'timestamp_action_id', type: dynamodb.AttributeType.STRING },
});
```

Grant backend task role read/write:

```ts
this.adminActionsTable.grantReadWriteData(backendTaskRole);
```

Export the table ARN for cross-stack reference if needed.

- [ ] **Step 3: Verify**

Run `cd apps/infra && pnpm synth` — should succeed without errors. Compare diff output against `pnpm diff isol8-dev-database`.

- [ ] **Step 4: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts apps/infra/tests/database-stack.test.ts
git commit -m "$(cat <<'EOF'
feat(infra): admin-actions DDB table

Adds isol8-{env}-admin-actions with PK admin_user_id + SK
timestamp_action_id, plus target-timestamp-index GSI for
"show me all actions against this user" queries. No TTL —
audit rows kept forever per CEO review.

Refs #351

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Extend backend task role with CloudWatch Logs read permissions

**Files:**
- Modify: `apps/infra/lib/stacks/service-stack.ts`

IAM additions so the backend can read its own log group for the inline CloudWatch viewer.

- [ ] **Step 1: Write an IAM assertion test**

In the service-stack test, assert the backend task role has statements allowing `logs:FilterLogEvents`, `logs:StartQuery`, `logs:GetQueryResults`, `logs:GetLogEvents`, `logs:DescribeLogStreams` scoped to the specific log group ARNs (not `*`).

- [ ] **Step 2: Add the policy**

In `apps/infra/lib/stacks/service-stack.ts`, find the `backendTaskRole` and append:

```ts
backendTaskRole.addToPolicy(new iam.PolicyStatement({
  effect: iam.Effect.ALLOW,
  actions: [
    'logs:FilterLogEvents',
    'logs:StartQuery',
    'logs:GetQueryResults',
    'logs:GetLogEvents',
    'logs:DescribeLogStreams',
  ],
  resources: [
    `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/ecs/isol8-${props.env}-backend:*`,
    // add other log groups to surface here (e.g. Lambda authorizer)
  ],
}));
```

Least-privilege — scoped to specific log-group ARNs, never `*`.

- [ ] **Step 3: Verify + commit**

`pnpm synth` passes. Commit:

```
feat(infra): grant backend task role CloudWatch Logs read

Enables the inline admin log viewer to call logs.FilterLogEvents
against /aws/ecs/isol8-{env}-backend. Scoped to specific log-group
ARNs — not '*' — per least-privilege.

Refs #351
```

---

### Task 3: Mint PostHog project API key + wire backend secrets

**Files:**
- (Secrets Manager — manual out-of-band step)
- Modify: `apps/backend/core/config.py`

- [ ] **Step 1: Create PostHog project API key (manual)**

In the PostHog dashboard → Project Settings → Project API Keys → create "isol8-admin-server". Scope: `person:read`, `events:read`, `session_recording:read`.

- [ ] **Step 2: Add to Secrets Manager**

```bash
# Dev
aws secretsmanager update-secret --secret-id isol8/dev/backend-env \
  --secret-string "$(aws secretsmanager get-secret-value --secret-id isol8/dev/backend-env \
    --query SecretString --output text --profile isol8-admin \
    | jq --arg k "$POSTHOG_KEY" '. + {POSTHOG_PROJECT_API_KEY: $k, POSTHOG_PROJECT_ID: "12345", POSTHOG_HOST: "https://app.posthog.com"}')" \
  --profile isol8-admin

# Repeat for isol8/prod/backend-env
```

Also add `PLATFORM_ADMIN_USER_IDS` (if not already populated) with the Isol8 team's Clerk user IDs.

- [ ] **Step 3: Add settings fields**

In `apps/backend/core/config.py`:

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # Admin dashboard
    PLATFORM_ADMIN_USER_IDS: str = ""
    ADMIN_UI_ENABLED: bool = False
    ADMIN_UI_ENABLED_USER_IDS: str = ""  # comma-separated allowlist override
    ADMIN_AUDIT_VIEWS: bool = True  # log read-only /overview calls

    # PostHog (server-side, distinct from NEXT_PUBLIC_POSTHOG_KEY)
    POSTHOG_HOST: str = "https://app.posthog.com"
    POSTHOG_PROJECT_ID: str = ""
    POSTHOG_PROJECT_API_KEY: str = ""

    @property
    def admin_ui_enabled_user_ids(self) -> set[str]:
        raw = self.ADMIN_UI_ENABLED_USER_IDS or ""
        return {u.strip() for u in raw.split(",") if u.strip()}
```

- [ ] **Step 4: Commit**

```
feat(config): admin dashboard + PostHog server-side settings

Adds PLATFORM_ADMIN_USER_IDS (already consumed by
require_platform_admin), ADMIN_UI_ENABLED feature flag,
ADMIN_UI_ENABLED_USER_IDS per-user override, ADMIN_AUDIT_VIEWS
toggle, and three POSTHOG_* server-side settings for the
admin activity tab.

Refs #351
```

---

### Task 4: Register admin.isol8.co DNS + Vercel domain alias

**Files:**
- (Vercel dashboard — manual)
- (Route53 — manual or CDK-managed DNS stack)

Host-based middleware only works if the hostname actually resolves to the existing frontend Vercel project. This is a one-time config step, not code.

- [ ] **Step 1: Add domain to Vercel project**

In Vercel → `isol8-frontend-prod` project → Settings → Domains → Add `admin.isol8.co`. Vercel returns a CNAME target.

Repeat for `isol8-frontend-dev` project with `admin-dev.isol8.co`.

- [ ] **Step 2: Create Route53 records**

If DNS is CDK-managed (check `apps/infra/lib/stacks/*-dns-stack.ts`), add:

```ts
new route53.CnameRecord(this, 'AdminSubdomain', {
  zone: hostedZone,
  recordName: 'admin',
  domainName: 'cname.vercel-dns.com',
});
```

Otherwise do this via the Route53 console.

- [ ] **Step 3: Verify**

```bash
dig admin-dev.isol8.co CNAME
# Expect: cname.vercel-dns.com or Vercel-provided target.
curl -I https://admin-dev.isol8.co
# Expect: 401 or the existing frontend index (not hooked up to admin yet —
# that's Task 13 middleware).
```

- [ ] **Step 4: Commit** (if any code changed; manual-only tasks need no commit)

---

### Task 5: Configure Cloudflare Access policy for `admin-dev.isol8.co` and `admin.isol8.co`

**Files:**
- `docs/runbooks/admin-cloudflare-access-rollout.md` (new)

Cloudflare Access sits in front of Vercel for the admin subdomain. Only SSO-authenticated users from allowlisted domains reach Vercel at all.

- [ ] **Step 1: Configure in Cloudflare dashboard**

Zero Trust → Access → Applications → Add self-hosted app:
- Name: `isol8-admin-dev` (and another for prod)
- Domain: `admin-dev.isol8.co`
- Session duration: 12 hours
- Identity providers: GitHub, Google
- Policy: "Allow team" — include rule: "Emails matching email domain: isol8.co" OR "Email exact match: <list of personal emails>"

- [ ] **Step 2: Write the rollout runbook**

Create `docs/runbooks/admin-cloudflare-access-rollout.md`:

```markdown
# Admin Cloudflare Access rollout

## Testing a new admin user

1. Add their email to the Cloudflare Access policy (Zero Trust → Access → Applications → isol8-admin-{env} → Policies).
2. Add their Clerk user_id to `ADMIN_UI_ENABLED_USER_IDS` in `isol8/{env}/backend-env` Secrets Manager entry.
3. Redeploy backend so the env var propagates.
4. Have the user open `https://admin-{env}.isol8.co/admin` → expect SSO prompt → `/admin/users` loads.

## Troubleshooting

- **SSO succeeds but /admin 403s:** their Clerk user_id isn't in `PLATFORM_ADMIN_USER_IDS`. Add it.
- **SSO succeeds but /admin 404s:** `ADMIN_UI_ENABLED=false` or their user_id isn't in `ADMIN_UI_ENABLED_USER_IDS`.
- **Cloudflare Access redirect loop:** policy is scoped too narrowly. Check the "Policy" tab in CF dashboard.

## Breaking glass

Disable admin entirely: set `PLATFORM_ADMIN_USER_IDS=""` in Secrets Manager → redeploy backend. Every /admin endpoint 403s. UI shows /admin/not-authorized.
```

- [ ] **Step 3: Commit the runbook**

```
docs(runbook): Cloudflare Access rollout for admin subdomain

Refs #351
```

---

## Phase B — Backend foundation

### Task 6: `admin_actions_repo.py` — DDB CRUD

**Files:**
- Create: `apps/backend/core/repositories/admin_actions_repo.py`
- Create: `apps/backend/tests/unit/repositories/test_admin_actions_repo.py`

Thin boto3 wrapper mirroring the `update_repo` style.

- [ ] **Step 1: Write the test**

```python
# apps/backend/tests/unit/repositories/test_admin_actions_repo.py
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from core.repositories.admin_actions_repo import AdminActionsRepo


@pytest.fixture
def repo():
    with patch("core.repositories.admin_actions_repo.boto3") as boto3_mock:
        table_mock = MagicMock()
        boto3_mock.resource.return_value.Table.return_value = table_mock
        r = AdminActionsRepo(table_name="isol8-test-admin-actions")
        yield r, table_mock


@pytest.mark.asyncio
async def test_create_writes_all_fields(repo):
    r, table = repo
    await r.create(
        admin_user_id="user_admin",
        target_user_id="user_target",
        action="container.reprovision",
        payload={"tier": "starter"},
        result="success",
        audit_status="written",
        http_status=200,
        elapsed_ms=240,
        error_message=None,
        user_agent="Mozilla/5.0",
        ip="203.0.113.1",
    )
    args, _ = table.put_item.call_args
    item = args.kwargs["Item"] if args.kwargs else args[0]["Item"]
    assert item["admin_user_id"] == "user_admin"
    assert item["target_user_id"] == "user_target"
    assert item["action"] == "container.reprovision"
    assert item["result"] == "success"
    assert item["audit_status"] == "written"
    # timestamp_action_id is generated — just check the shape
    assert "#" in item["timestamp_action_id"]


@pytest.mark.asyncio
async def test_query_by_target_uses_gsi(repo):
    r, table = repo
    table.query.return_value = {"Items": [], "LastEvaluatedKey": None}
    await r.query_by_target("user_target", limit=20)
    args, _ = table.query.call_args
    assert args.kwargs["IndexName"] == "target-timestamp-index"
    assert args.kwargs["Limit"] == 20
```

- [ ] **Step 2: Implement**

```python
# apps/backend/core/repositories/admin_actions_repo.py
import boto3
import uuid6
from datetime import datetime, timezone
from typing import Optional


class AdminActionsRepo:
    def __init__(self, table_name: str):
        self._table = boto3.resource("dynamodb").Table(table_name)

    async def create(
        self,
        *,
        admin_user_id: str,
        target_user_id: str,
        action: str,
        payload: dict,
        result: str,
        audit_status: str,
        http_status: int,
        elapsed_ms: int,
        error_message: Optional[str],
        user_agent: str,
        ip: str,
    ) -> dict:
        ts = datetime.now(timezone.utc).isoformat()
        action_id = str(uuid6.uuid7())
        item = {
            "admin_user_id": admin_user_id,
            "timestamp_action_id": f"{ts}#{action_id}",
            "target_user_id": target_user_id,
            "action": action,
            "payload": payload,
            "result": result,
            "audit_status": audit_status,
            "http_status": http_status,
            "elapsed_ms": elapsed_ms,
            "user_agent": user_agent,
            "ip": ip,
        }
        if error_message:
            item["error_message"] = error_message
        self._table.put_item(Item=item)
        return item

    async def query_by_target(
        self, target_user_id: str, limit: int = 50, cursor: Optional[str] = None
    ) -> dict:
        kwargs = {
            "IndexName": "target-timestamp-index",
            "KeyConditionExpression": "target_user_id = :t",
            "ExpressionAttributeValues": {":t": target_user_id},
            "Limit": limit,
            "ScanIndexForward": False,  # newest first
        }
        if cursor:
            kwargs["ExclusiveStartKey"] = {"target_user_id": target_user_id, "timestamp_action_id": cursor}
        return self._table.query(**kwargs)

    async def query_by_admin(
        self, admin_user_id: str, limit: int = 50, cursor: Optional[str] = None
    ) -> dict:
        kwargs = {
            "KeyConditionExpression": "admin_user_id = :a",
            "ExpressionAttributeValues": {":a": admin_user_id},
            "Limit": limit,
            "ScanIndexForward": False,
        }
        if cursor:
            kwargs["ExclusiveStartKey"] = {"admin_user_id": admin_user_id, "timestamp_action_id": cursor}
        return self._table.query(**kwargs)
```

- [ ] **Step 3: Run the test** — `uv run pytest tests/unit/repositories/test_admin_actions_repo.py -v` — all green.

- [ ] **Step 4: Commit**

```
feat(backend): admin_actions_repo DDB CRUD

Creates, queries-by-target (GSI), and queries-by-admin for the
isol8-{env}-admin-actions table. Used by admin_audit decorator.

Refs #351
```

---

### Task 7: `admin_audit.py` — `@audit_admin_action` decorator (fail-closed)

**Files:**
- Create: `apps/backend/core/services/admin_audit.py`
- Create: `apps/backend/tests/unit/services/test_admin_audit.py`

**CEO review S1 (critical):** audit writes are synchronous; on DDB failure the action still returns success but with `audit_status: "panic"` + a panic-level structured log alert.

- [ ] **Step 1: Write the test**

Cover these cases:
1. Happy path — handler succeeds, audit row written with `audit_status="written"`, response unchanged.
2. Handler raises — audit row written with `result="error"`, error message captured, original exception re-raised.
3. Audit write fails (DDB outage) — handler result still returned to caller BUT response annotated with `audit_status: "panic"`; panic log emitted; original result preserved.
4. Payload redaction — decorator accepts a `redact_paths` param; those paths are stripped before DDB write.
5. Elapsed ms captured.
6. User-agent + IP captured from request headers.

- [ ] **Step 2: Implement**

```python
# apps/backend/core/services/admin_audit.py
import functools
import logging
import time
from typing import Callable, Optional
from fastapi import Request
from starlette.responses import JSONResponse

from core.auth import AuthContext
from core.repositories.admin_actions_repo import AdminActionsRepo
from core.config import settings

logger = logging.getLogger(__name__)

_repo: Optional[AdminActionsRepo] = None


def _get_repo() -> AdminActionsRepo:
    global _repo
    if _repo is None:
        env = settings.ENVIRONMENT or "dev"
        _repo = AdminActionsRepo(table_name=f"isol8-{env}-admin-actions")
    return _repo


def _extract_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _redact(payload: dict, paths: list[str]) -> dict:
    """Shallow redaction — replaces values at listed keys with '***redacted***'."""
    if not paths:
        return payload
    out = dict(payload)
    for p in paths:
        if p in out:
            out[p] = "***redacted***"
    return out


def audit_admin_action(
    action: str, *, target_param: str = "user_id", redact_paths: Optional[list[str]] = None
) -> Callable:
    """Synchronous, fail-closed audit decorator for admin router handlers.

    Every decorated handler MUST take `auth: AuthContext` and the request's
    target user id as a path param named `target_param` (default "user_id").
    The payload is the handler's request body dict (or the path params + query
    for GET endpoints).

    Audit write is synchronous — if DDB fails, we return audit_status="panic"
    and log at panic level. The primary action still returns to the caller.
    """
    redact_paths = redact_paths or []

    def decorator(handler: Callable) -> Callable:
        @functools.wraps(handler)
        async def wrapped(*args, **kwargs):
            request: Optional[Request] = kwargs.get("request")
            auth: Optional[AuthContext] = kwargs.get("auth")
            if auth is None:
                # find auth in args by duck-typing
                for a in args:
                    if isinstance(a, AuthContext):
                        auth = a
                        break
            if auth is None:
                raise RuntimeError("audit_admin_action requires AuthContext in kwargs or args")

            target_user_id = kwargs.get(target_param, "system")
            # extract request body if available
            payload = {}
            if "body" in kwargs and kwargs["body"] is not None:
                body = kwargs["body"]
                if hasattr(body, "model_dump"):
                    payload = body.model_dump()
                elif isinstance(body, dict):
                    payload = body
            payload = _redact(payload, redact_paths)

            user_agent = request.headers.get("user-agent", "unknown") if request else "unknown"
            ip = _extract_client_ip(request) if request else "unknown"

            started = time.monotonic()
            result = "success"
            http_status = 200
            error_message = None
            handler_result = None
            exc: Optional[Exception] = None

            try:
                handler_result = await handler(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 — re-raised after audit
                exc = e
                result = "error"
                http_status = getattr(e, "status_code", 500)
                error_message = str(e)

            elapsed_ms = int((time.monotonic() - started) * 1000)

            audit_status = "written"
            try:
                await _get_repo().create(
                    admin_user_id=auth.user_id,
                    target_user_id=target_user_id,
                    action=action,
                    payload=payload,
                    result=result,
                    audit_status="written",
                    http_status=http_status,
                    elapsed_ms=elapsed_ms,
                    error_message=error_message,
                    user_agent=user_agent,
                    ip=ip,
                )
            except Exception as audit_exc:  # noqa: BLE001
                audit_status = "panic"
                logger.critical(
                    "ADMIN_AUDIT_PANIC action=%s admin=%s target=%s err=%s payload=%s",
                    action, auth.user_id, target_user_id, audit_exc, payload,
                    extra={
                        "action": action,
                        "admin_user_id": auth.user_id,
                        "target_user_id": target_user_id,
                        "payload": payload,
                        "result": result,
                    },
                )

            if exc is not None:
                raise exc

            # Tag the response with audit_status so UI can warn the operator.
            if isinstance(handler_result, dict):
                return {**handler_result, "audit_status": audit_status}
            elif isinstance(handler_result, JSONResponse):
                return handler_result  # can't mutate easily; accept the tradeoff
            return handler_result

        return wrapped

    return decorator
```

- [ ] **Step 3: Run the test** — all six cases pass.

- [ ] **Step 4: Commit**

```
feat(backend): @audit_admin_action decorator (fail-closed)

Synchronous DDB write before response. On audit-write failure
the primary action is NOT rolled back (can't in general —
Stripe/ECS side effects have already happened) but the response
is annotated audit_status=panic and a CRITICAL log fires so
operators notice the gap. Mirrors CEO review S1.

Refs #351
```

---

### Task 8: `cloudwatch_logs.py` — FilterLogEvents wrapper (pagination)

**Files:**
- Create: `apps/backend/core/services/cloudwatch_logs.py`
- Create: `apps/backend/tests/unit/services/test_cloudwatch_logs.py`

**CEO review E4:** pagination via `nextToken`.

- [ ] **Step 1: Write the test**

```python
@pytest.mark.asyncio
async def test_filter_user_logs_happy_path(boto_mock):
    boto_mock.filter_log_events.return_value = {
        "events": [
            {"timestamp": 1700000000000, "message": '{"user_id":"u1","level":"ERROR","msg":"boom"}'},
        ],
    }
    result = await filter_user_logs(user_id="u1", level="ERROR", hours=24, limit=20)
    assert len(result["events"]) == 1
    assert result["events"][0]["level"] == "ERROR"
    assert result["missing"] is False


@pytest.mark.asyncio
async def test_filter_user_logs_pagination(boto_mock):
    boto_mock.filter_log_events.return_value = {
        "events": [],
        "nextToken": "next-page-token",
    }
    result = await filter_user_logs(user_id="u1", level="ERROR", hours=24, limit=20)
    assert result["cursor"] == "next-page-token"


@pytest.mark.asyncio
async def test_filter_user_logs_handles_malformed_json(boto_mock):
    boto_mock.filter_log_events.return_value = {
        "events": [
            {"timestamp": 1700000000000, "message": "not json"},
        ],
    }
    result = await filter_user_logs(user_id="u1", level="ERROR", hours=24, limit=20)
    assert result["events"][0]["raw_json"] is None
    assert result["events"][0]["message"] == "not json"
```

- [ ] **Step 2: Implement**

```python
# apps/backend/core/services/cloudwatch_logs.py
import boto3
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.config import settings

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client("logs", region_name=settings.AWS_REGION)
    return _client


def _backend_log_group() -> str:
    env = settings.ENVIRONMENT or "dev"
    return f"/aws/ecs/isol8-{env}-backend"


async def filter_user_logs(
    *,
    user_id: str,
    level: str = "ERROR",
    hours: int = 24,
    limit: int = 20,
    cursor: Optional[str] = None,
) -> dict:
    """Return recent structured logs for a specific user.

    Returns {events: [...], cursor: str|None, missing: bool}.
    - events rows include parsed JSON in raw_json (or None if malformed).
    - cursor is the nextToken for pagination; None when no more results.
    - missing=True when the log group does not exist (LocalStack / fresh env).
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)

    kwargs = {
        "logGroupName": _backend_log_group(),
        "startTime": int(start.timestamp() * 1000),
        "endTime": int(end.timestamp() * 1000),
        "filterPattern": f'{{ $.user_id = "{user_id}" && $.level = "{level}" }}',
        "limit": min(limit, 100),
    }
    if cursor:
        kwargs["nextToken"] = cursor

    try:
        response = _get_client().filter_log_events(**kwargs)
    except _get_client().exceptions.ResourceNotFoundException:
        return {"events": [], "cursor": None, "missing": True}
    except Exception as e:
        logger.warning("cloudwatch_logs.filter_user_logs failed: %s", e)
        return {"events": [], "cursor": None, "missing": False, "error": str(e)}

    events = []
    for raw in response.get("events", []):
        parsed = None
        try:
            parsed = json.loads(raw["message"])
        except (ValueError, TypeError):
            pass
        events.append({
            "timestamp": datetime.fromtimestamp(raw["timestamp"] / 1000, tz=timezone.utc).isoformat(),
            "level": (parsed or {}).get("level") if parsed else None,
            "message": (parsed or {}).get("message") if parsed else raw["message"],
            "correlation_id": (parsed or {}).get("correlation_id") if parsed else None,
            "raw_json": parsed,
        })

    return {
        "events": events,
        "cursor": response.get("nextToken"),
        "missing": False,
    }


async def recent_errors_fleet(hours: int = 24, limit: int = 20) -> list[dict]:
    """Cross-user feed used by /admin/health."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    try:
        response = _get_client().filter_log_events(
            logGroupName=_backend_log_group(),
            startTime=int(start.timestamp() * 1000),
            endTime=int(end.timestamp() * 1000),
            filterPattern='{ $.level = "ERROR" }',
            limit=min(limit, 100),
        )
    except _get_client().exceptions.ResourceNotFoundException:
        return []
    except Exception as e:
        logger.warning("cloudwatch_logs.recent_errors_fleet failed: %s", e)
        return []

    out = []
    for raw in response.get("events", []):
        try:
            parsed = json.loads(raw["message"])
        except (ValueError, TypeError):
            parsed = {}
        out.append({
            "timestamp": datetime.fromtimestamp(raw["timestamp"] / 1000, tz=timezone.utc).isoformat(),
            "user_id": parsed.get("user_id"),
            "message": parsed.get("message") or raw["message"],
            "correlation_id": parsed.get("correlation_id"),
        })
    return out
```

- [ ] **Step 3: Run tests + commit**

```
feat(backend): cloudwatch_logs service (inline viewer, pagination)

Wraps logs.FilterLogEvents for per-user error feed (inline admin
log viewer) and fleet-scoped recent errors (/admin/health). Threads
nextToken through as cursor. Handles ResourceNotFoundException for
LocalStack / fresh envs with missing=true.

Refs #351
```

---

### Task 9: `cloudwatch_url.py` — Insights deep-link builder

**Files:**
- Create: `apps/backend/core/services/cloudwatch_url.py`
- Create: `apps/backend/tests/unit/services/test_cloudwatch_url.py`

Pure string assembly. No SDK call.

- [ ] **Step 1: Test**

```python
def test_build_insights_url_has_user_filter():
    url = build_insights_url(user_id="u_test", start=..., end=..., level="ERROR")
    assert "user_id" in url
    assert "u_test" in url
    assert "logs-insights" in url
    assert "filter%20user_id" in url  # URL-encoded filter clause
```

- [ ] **Step 2: Implement** — simple f-string per the URL template in the spec.

- [ ] **Step 3: Commit**

```
feat(backend): cloudwatch_url CWL Insights deep-link builder

Refs #351
```

---

### Task 10: `posthog_admin.py` — Persons API client

**Files:**
- Create: `apps/backend/core/services/posthog_admin.py`
- Create: `apps/backend/tests/unit/services/test_posthog_admin.py`

**CEO review E5:** 404 returns `{events: [], missing: true}`.

- [ ] **Step 1: Test**

```python
@pytest.mark.asyncio
async def test_get_person_events_happy_path(httpx_mock):
    httpx_mock.add_response(json={"results": [{"event": "$pageview", "timestamp": "2026-04-21T00:00:00Z"}]})
    result = await get_person_events(distinct_id="user_test", limit=10)
    assert len(result["events"]) == 1
    assert result["missing"] is False


@pytest.mark.asyncio
async def test_get_person_events_404_missing(httpx_mock):
    httpx_mock.add_response(status_code=404)
    result = await get_person_events(distinct_id="user_missing", limit=10)
    assert result["events"] == []
    assert result["missing"] is True


@pytest.mark.asyncio
async def test_stubbed_when_key_unset(monkeypatch):
    monkeypatch.setattr("core.config.settings.POSTHOG_PROJECT_API_KEY", "")
    result = await get_person_events(distinct_id="u", limit=10)
    assert result["stubbed"] is True
```

- [ ] **Step 2: Implement**

```python
# apps/backend/core/services/posthog_admin.py
import httpx
import logging
from core.config import settings

logger = logging.getLogger(__name__)


async def get_person_events(*, distinct_id: str, limit: int = 100) -> dict:
    if not settings.POSTHOG_PROJECT_API_KEY or not settings.POSTHOG_PROJECT_ID:
        return {"events": [], "stubbed": True, "missing": False}

    url = f"{settings.POSTHOG_HOST}/api/projects/{settings.POSTHOG_PROJECT_ID}/persons/"
    headers = {"Authorization": f"Bearer {settings.POSTHOG_PROJECT_API_KEY}"}
    params = {"distinct_id": distinct_id, "limit": limit}

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers, params=params)
    except httpx.TimeoutException:
        return {"events": [], "stubbed": False, "missing": False, "error": "timeout"}
    except Exception as e:  # noqa: BLE001
        logger.warning("posthog_admin.get_person_events failed: %s", e)
        return {"events": [], "stubbed": False, "missing": False, "error": str(e)}

    if response.status_code == 404:
        return {"events": [], "stubbed": False, "missing": True}
    response.raise_for_status()
    data = response.json()

    events = []
    for p in data.get("results", []):
        for e in p.get("events", [])[:limit]:
            events.append({
                "timestamp": e.get("timestamp"),
                "event": e.get("event"),
                "properties": e.get("properties", {}),
                "session_id": e.get("properties", {}).get("$session_id"),
            })
    return {"events": events, "stubbed": False, "missing": False}


def session_replay_url(session_id: str) -> str:
    return f"{settings.POSTHOG_HOST}/replay/{session_id}"
```

- [ ] **Step 3: Commit**

```
feat(backend): posthog_admin Persons API client

Queries PostHog for a user's recent events + session replay links.
Stubs cleanly (stubbed=true) when POSTHOG_PROJECT_API_KEY is unset,
so local dev works without a real PostHog project. Handles 404
(missing=true) for users who never visited the frontend.

Refs #351
```

---

### Task 11: `admin_redact.py` — openclaw.json secret redaction

**Files:**
- Create: `apps/backend/core/services/admin_redact.py`
- Create: `apps/backend/tests/unit/services/test_admin_redact.py`

**CEO review S3.**

- [ ] **Step 1: Test**

```python
def test_redacts_key_suffixed_fields():
    config = {
        "providers": {"anthropic_api_key": "sk-ant-abc", "webhook_url": "https://x"},
        "ok": "value",
        "nested": {"openai_secret": "sk-openai-def", "normal": 123},
    }
    redacted = redact_openclaw_config(config)
    assert redacted["providers"]["anthropic_api_key"] == "***redacted***"
    assert redacted["providers"]["webhook_url"] == "***redacted***"
    assert redacted["ok"] == "value"
    assert redacted["nested"]["openai_secret"] == "***redacted***"
    assert redacted["nested"]["normal"] == 123
```

- [ ] **Step 2: Implement**

```python
# apps/backend/core/services/admin_redact.py
import re
from typing import Any

_REDACT_PATTERNS = [
    re.compile(r"_key$"),
    re.compile(r"_secret$"),
    re.compile(r"_token$"),
    re.compile(r"_password$"),
    re.compile(r"^webhook_url$"),
    re.compile(r"^api_key$"),
    re.compile(r"^bearer$"),
]


def _should_redact(key: str) -> bool:
    k = key.lower()
    return any(p.search(k) for p in _REDACT_PATTERNS)


def redact_openclaw_config(value: Any) -> Any:
    """Recursively redact secret-like fields. Preserves shape; replaces values only."""
    if isinstance(value, dict):
        return {k: ("***redacted***" if _should_redact(k) else redact_openclaw_config(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_openclaw_config(item) for item in value]
    return value
```

- [ ] **Step 3: Commit**

```
feat(backend): openclaw.json secret redaction allowlist

Recursive redactor for fields matching *_key/_secret/_token/_password,
webhook_url, api_key. Used by admin_service.get_agent_detail before
returning config to the admin UI.

Refs #351
```

---

### Task 12: `system_health.py` — `/admin/health` aggregator

**Files:**
- Create: `apps/backend/core/services/system_health.py`
- Create: `apps/backend/tests/unit/services/test_system_health.py`

Fleet counts (DDB scan grouped), upstream probes with 30s cache (CEO review P2), background-task state.

- [ ] **Step 1: Test**

Cover: (a) returns fleet counts from DDB, (b) probes run in parallel with 2s timeout each, (c) cache TTL 30s, (d) background-task state read from `main.py` lifespan references.

- [ ] **Step 2: Implement**

```python
# apps/backend/core/services/system_health.py
import asyncio
import time
import httpx
import logging
from typing import Any
from core.config import settings
from core.repositories import container_repo
from core.services import cloudwatch_logs

logger = logging.getLogger(__name__)

_PROBE_CACHE_TTL_S = 30
_probe_cache: dict[str, Any] = {"ts": 0, "value": None}

# Set by main.py lifespan to a dict of {task_name: asyncio.Task}
BACKGROUND_TASKS: dict = {}


async def _probe_clerk() -> dict:
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            t = time.monotonic()
            r = await c.get(f"{settings.CLERK_ISSUER}/.well-known/jwks.json")
            return {"status": "ok" if r.status_code == 200 else "degraded", "latency_ms": int((time.monotonic() - t) * 1000)}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def _probe_stripe() -> dict:
    # Lightweight ping: just check the API key's validity via Account.retrieve
    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        t = time.monotonic()
        await asyncio.to_thread(stripe.Account.retrieve)
        return {"status": "ok", "latency_ms": int((time.monotonic() - t) * 1000)}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


async def _probe_ddb() -> dict:
    try:
        t = time.monotonic()
        await asyncio.to_thread(container_repo.count)
        return {"status": "ok", "latency_ms": int((time.monotonic() - t) * 1000)}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def _probes() -> dict:
    if time.monotonic() - _probe_cache["ts"] < _PROBE_CACHE_TTL_S and _probe_cache["value"] is not None:
        return _probe_cache["value"]
    results = await asyncio.gather(_probe_clerk(), _probe_stripe(), _probe_ddb(), return_exceptions=True)
    value = {
        "clerk": results[0] if not isinstance(results[0], Exception) else {"status": "down", "error": str(results[0])},
        "stripe": results[1] if not isinstance(results[1], Exception) else {"status": "down", "error": str(results[1])},
        "ddb": results[2] if not isinstance(results[2], Exception) else {"status": "down", "error": str(results[2])},
    }
    _probe_cache["ts"] = time.monotonic()
    _probe_cache["value"] = value
    return value


async def _fleet_counts() -> dict:
    items = await container_repo.all()
    counts: dict[str, int] = {"running": 0, "provisioning": 0, "stopped": 0, "error": 0}
    for item in items:
        s = item.get("status", "unknown")
        counts[s] = counts.get(s, 0) + 1
    counts["total"] = len(items)
    return counts


def _background_tasks_status() -> dict:
    out = {}
    for name, task in BACKGROUND_TASKS.items():
        if task is None:
            out[name] = {"status": "unregistered"}
        elif task.done():
            exc = task.exception()
            out[name] = {"status": "stopped", "error": str(exc) if exc else None}
        else:
            out[name] = {"status": "running"}
    return out


async def get_system_health() -> dict:
    probes, fleet, recent_errors = await asyncio.gather(
        _probes(),
        _fleet_counts(),
        cloudwatch_logs.recent_errors_fleet(hours=24, limit=10),
    )
    return {
        "upstreams": probes,
        "fleet": fleet,
        "background_tasks": _background_tasks_status(),
        "recent_errors": recent_errors,
    }
```

- [ ] **Step 3: Wire `BACKGROUND_TASKS` in `main.py`**

In `apps/backend/main.py` lifespan:

```python
from core.services import system_health

# After creating each task:
system_health.BACKGROUND_TASKS["idle_checker"] = idle_checker_task
system_health.BACKGROUND_TASKS["scheduled_worker"] = worker_task
system_health.BACKGROUND_TASKS["town_simulation"] = town_task  # if applicable
```

- [ ] **Step 4: Commit**

```
feat(backend): system_health /admin/health aggregator

Probes Clerk/Stripe/DDB upstreams with 30s cache (CEO P2),
scans container fleet by status, reads background-task state
from main.py lifespan, pulls recent fleet errors from CWL.

Refs #351
```

---

### Task 13: `admin_service.py` — composition layer

**Files:**
- Create: `apps/backend/core/services/admin_service.py`
- Create: `apps/backend/tests/unit/services/test_admin_service.py`

**CEO review C1:** compose existing services. **CEO P1:** timeout wrappers on parallel fetches. **CEO S3:** redact config.

- [ ] **Step 1: Test** (many sub-cases — one per endpoint's composition)

- [ ] **Step 2: Implement** — ~300 lines; top-level shape:

```python
# apps/backend/core/services/admin_service.py
import asyncio
import logging
from typing import Any, Optional

from core.services import clerk_sync_service, billing_service
from core.services.admin_redact import redact_openclaw_config
from core.services.cloudwatch_logs import filter_user_logs
from core.services.cloudwatch_url import build_insights_url
from core.services.posthog_admin import get_person_events
from core.gateway.connection_pool import get_gateway_pool
from core.repositories import container_repo, billing_repo, usage_repo
from core.repositories.admin_actions_repo import AdminActionsRepo

logger = logging.getLogger(__name__)

_PARALLEL_TIMEOUT_S = 2.0


async def _with_timeout(awaitable, label: str):
    try:
        return await asyncio.wait_for(awaitable, timeout=_PARALLEL_TIMEOUT_S)
    except asyncio.TimeoutError:
        return {"error": "timeout", "source": label}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e), "source": label}


async def list_users(q: str = "", cursor: Optional[str] = None, limit: int = 50) -> dict:
    # Clerk paginated list + join container status
    clerk_page = await clerk_sync_service.list_users(query=q, limit=limit, offset=cursor)
    user_ids = [u["id"] for u in clerk_page["users"]]
    containers = {c["owner_id"]: c for c in await container_repo.batch_get(user_ids)}
    return {
        "users": [
            {
                "clerk_id": u["id"],
                "email": u.get("email_addresses", [{}])[0].get("email_address"),
                "created_at": u.get("created_at"),
                "last_sign_in_at": u.get("last_sign_in_at"),
                "banned": u.get("banned", False),
                "container_status": (containers.get(u["id"]) or {}).get("status", "none"),
                "plan_tier": (containers.get(u["id"]) or {}).get("plan_tier", "free"),
            }
            for u in clerk_page["users"]
        ],
        "cursor": clerk_page.get("next_cursor"),
    }


async def get_overview(user_id: str) -> dict:
    clerk, stripe_sub, container, billing, usage = await asyncio.gather(
        _with_timeout(clerk_sync_service.get_user(user_id), "clerk"),
        _with_timeout(billing_service.get_subscription_for(user_id), "stripe"),
        _with_timeout(container_repo.get_by_owner(user_id), "ddb_containers"),
        _with_timeout(billing_repo.get_by_owner(user_id), "ddb_billing"),
        _with_timeout(usage_repo.get_counters(user_id), "ddb_usage"),
    )
    return {
        "identity": clerk,
        "billing": {"subscription": stripe_sub, "account": billing},
        "container": container,
        "usage": usage,
    }


async def list_user_agents(user_id: str, cursor: Optional[str] = None, limit: int = 50) -> dict:
    pool = get_gateway_pool()
    container = await container_repo.get_by_owner(user_id)
    if not container or container.get("status") != "running":
        return {"agents": [], "container_status": container.get("status") if container else "none"}
    try:
        result = await asyncio.wait_for(
            pool.call(user_id, "agents.list", {"cursor": cursor, "limit": limit}),
            timeout=3.0,
        )
    except asyncio.TimeoutError:
        return {"agents": [], "container_status": "timeout", "error": "gateway_rpc_timeout"}
    return {"agents": result.get("agents", []), "cursor": result.get("cursor"), "container_status": "running"}


async def get_agent_detail(user_id: str, agent_id: str) -> dict:
    pool = get_gateway_pool()
    try:
        agent, sessions, skills, config = await asyncio.wait_for(
            asyncio.gather(
                pool.call(user_id, "agents.get", {"agent_id": agent_id}),
                pool.call(user_id, "sessions.list", {"agent_id": agent_id, "limit": 20}),
                pool.call(user_id, "skills.list", {"agent_id": agent_id}),
                pool.call(user_id, "config.get", {"agent_id": agent_id}),
            ),
            timeout=3.0,
        )
    except asyncio.TimeoutError:
        return {"error": "gateway_rpc_timeout"}

    return {
        "agent": agent,
        "sessions": sessions.get("sessions", []),
        "skills": skills.get("skills", []),
        "config_redacted": redact_openclaw_config(config),
    }


async def get_logs(user_id: str, level: str, hours: int, limit: int, cursor: Optional[str]) -> dict:
    return await filter_user_logs(
        user_id=user_id, level=level, hours=hours, limit=limit, cursor=cursor
    )


def get_cloudwatch_url(user_id: str, start: str, end: str, level: str) -> str:
    return build_insights_url(user_id=user_id, start=start, end=end, level=level)


async def get_posthog_timeline(user_id: str, limit: int = 100) -> dict:
    return await get_person_events(distinct_id=user_id, limit=limit)


async def get_actions_audit(
    target_user_id: Optional[str] = None,
    admin_user_id: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> dict:
    repo = AdminActionsRepo(table_name=f"isol8-{settings.ENVIRONMENT}-admin-actions")
    if target_user_id:
        page = await repo.query_by_target(target_user_id, limit=limit, cursor=cursor)
    elif admin_user_id:
        page = await repo.query_by_admin(admin_user_id, limit=limit, cursor=cursor)
    else:
        raise ValueError("Provide target_user_id or admin_user_id")
    items = page.get("Items", [])
    if action:
        items = [i for i in items if i.get("action") == action]
    return {"items": items, "cursor": page.get("LastEvaluatedKey", {}).get("timestamp_action_id")}
```

- [ ] **Step 3: Commit**

```
feat(backend): admin_service composition layer

Aggregates Clerk, Stripe, DDB, gateway RPC, CloudWatch, PostHog
via existing services. Parallel reads with 2s timeout wrappers
(CEO P1); gateway RPC with 3s timeout + container-stopped
detection (CEO E2/E3); config redaction (CEO S3); pagination
cursors threaded through (CEO E4/D2).

Refs #351
```

---

## Phase C — Backend router

### Task 14: `routers/admin.py` — `/admin/me` + system health + audit viewer

**Files:**
- Create: `apps/backend/routers/admin.py`
- Create: `apps/backend/tests/unit/routers/test_admin.py`

- [ ] **Step 1: Test — auth gate**

```python
@pytest.mark.asyncio
async def test_admin_me_rejects_non_platform_admin(client):
    # non-admin JWT
    response = await client.get("/api/v1/admin/me", headers=non_admin_headers)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_me_returns_profile_for_admin(client):
    response = await client.get("/api/v1/admin/me", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["is_admin"] is True
```

- [ ] **Step 2: Implement**

```python
# apps/backend/routers/admin.py
from fastapi import APIRouter, Depends, Query, Request
from typing import Optional

from core.auth import AuthContext, get_current_user, require_platform_admin
from core.services import admin_service, system_health as health_svc

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/me")
async def admin_me(auth: AuthContext = Depends(require_platform_admin)):
    return {"user_id": auth.user_id, "email": auth.email, "is_admin": True}


@router.get("/system/health")
async def admin_system_health(auth: AuthContext = Depends(require_platform_admin)):
    return await health_svc.get_system_health()


@router.get("/actions")
async def admin_actions(
    target_user_id: Optional[str] = Query(None),
    admin_user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    cursor: Optional[str] = Query(None),
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.get_actions_audit(
        target_user_id=target_user_id, admin_user_id=admin_user_id,
        action=action, limit=limit, cursor=cursor,
    )
```

- [ ] **Step 3: Commit**

```
feat(backend): admin router — /me, /system/health, /actions

Refs #351
```

---

### Task 15: User directory read endpoints

Add to `routers/admin.py`:

```python
@router.get("/users")
async def admin_list_users(
    q: str = Query(""), plan_tier: Optional[str] = Query(None),
    container_status: Optional[str] = Query(None),
    cursor: Optional[str] = Query(None), limit: int = Query(50, le=200),
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.list_users(q=q, cursor=cursor, limit=limit)


@router.get("/users/{user_id}/overview")
async def admin_user_overview(user_id: str, auth: AuthContext = Depends(require_platform_admin)):
    return await admin_service.get_overview(user_id)
```

Tests assert: Clerk rate-limit path (E1) — when `clerk_sync_service.list_users` raises, fall back to cached list + return 503-like flag in body.

Commit:

```
feat(backend): admin user directory endpoints (with CEO E1 handling)

Refs #351
```

---

### Task 16: Agents read endpoints

Add:

```python
@router.get("/users/{user_id}/agents")
async def admin_user_agents(
    user_id: str, cursor: Optional[str] = Query(None), limit: int = Query(50, le=200),
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.list_user_agents(user_id, cursor=cursor, limit=limit)


@router.get("/users/{user_id}/agents/{agent_id}")
async def admin_agent_detail(
    user_id: str, agent_id: str,
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.get_agent_detail(user_id, agent_id)
```

Tests assert E2 timeout behavior, E3 container-stopped path, S3 redaction. Commit:

```
feat(backend): admin agents endpoints (E2/E3 timeout + stopped; S3 redact)

Refs #351
```

---

### Task 17: PostHog + CloudWatch read endpoints

Add:

```python
@router.get("/users/{user_id}/posthog")
async def admin_user_posthog(
    user_id: str, limit: int = Query(100, le=500),
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.get_posthog_timeline(user_id, limit=limit)


@router.get("/users/{user_id}/logs")
async def admin_user_logs(
    user_id: str, level: str = Query("ERROR"), hours: int = Query(24, le=168),
    limit: int = Query(20, le=100), cursor: Optional[str] = Query(None),
    auth: AuthContext = Depends(require_platform_admin),
):
    return await admin_service.get_logs(user_id, level, hours, limit, cursor)


@router.get("/users/{user_id}/cloudwatch-url")
async def admin_user_cloudwatch_url(
    user_id: str, start: str = Query(...), end: str = Query(...),
    level: str = Query("ERROR"),
    auth: AuthContext = Depends(require_platform_admin),
):
    return {"url": admin_service.get_cloudwatch_url(user_id, start, end, level)}
```

Tests assert E5 (404 → missing=true), E4 (cursor round-trip). Commit:

```
feat(backend): admin posthog + cloudwatch read endpoints (E4/E5)

Refs #351
```

---

### Task 18: Container action endpoints (D1 idempotency)

```python
from core.services.admin_audit import audit_admin_action
from core.services.idempotency import idempotency  # new tiny helper


@router.post("/users/{user_id}/container/reprovision")
@idempotency(header="Idempotency-Key", ttl_s=60)
@audit_admin_action("container.reprovision")
async def admin_container_reprovision(
    user_id: str, request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    await ecs_manager.reprovision_for_user(user_id)
    return {"status": "started", "run_id": _new_run_id()}


# Similar for stop, start, resize
```

Ship a tiny `idempotency` helper in `core/services/idempotency.py` — in-memory dict with TTL for v1. Acceptable since admin-action volume is tiny; revisit if it needs to be distributed.

Tests: (a) idempotency replay returns cached; (b) audit row written per action; (c) navigate-away (D3): response returns immediately, reprovision runs server-side.

Commit:

```
feat(backend): admin container actions + idempotency (D1)

Refs #351
```

---

### Task 19: Billing action endpoints

```python
@router.post("/users/{user_id}/billing/cancel-subscription")
@idempotency(header="Idempotency-Key", ttl_s=60)
@audit_admin_action("billing.cancel_subscription")
async def admin_billing_cancel(
    user_id: str, request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    result = await billing_service.cancel_subscription(user_id)
    return {"status": "ok", "subscription": result}


# pause, issue-credit, mark-invoice-resolved similarly
```

Tests: each action calls the underlying `BillingService` method and writes audit. Commit:

```
feat(backend): admin billing actions

Refs #351
```

---

### Task 20: Account action endpoints

```python
@router.post("/users/{user_id}/account/suspend")
@audit_admin_action("account.suspend")
async def admin_account_suspend(
    user_id: str, request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    await clerk_sync_service.ban_user(user_id)
    return {"status": "banned"}


# reactivate, force-signout, resend-verification similarly
```

Commit:

```
feat(backend): admin account actions

Refs #351
```

---

### Task 21: Config + agent action endpoints

```python
@router.patch("/users/{user_id}/config")
@audit_admin_action("config.patch", redact_paths=["patch"])
async def admin_config_patch(
    user_id: str, request: Request, body: ConfigPatchRequest,
    auth: AuthContext = Depends(require_platform_admin),
):
    # Wraps existing PATCH /container/config/{owner_id}
    await patch_openclaw_config(owner_id=user_id, patch=body.patch)
    return {"status": "patched"}


@router.post("/users/{user_id}/agents/{agent_id}/delete")
@audit_admin_action("agent.delete")
async def admin_agent_delete(
    user_id: str, agent_id: str, request: Request,
    auth: AuthContext = Depends(require_platform_admin),
):
    pool = get_gateway_pool()
    await pool.call(user_id, "agents.delete", {"agent_id": agent_id})
    return {"status": "deleted"}


# clear-sessions similarly
```

Commit:

```
feat(backend): admin config + agent actions

Refs #351
```

---

### Task 22: Register router + admin metrics middleware

**Files:**
- Create: `apps/backend/core/middleware/admin_metrics.py`
- Modify: `apps/backend/main.py`

**CEO review O1:** `admin_api.call_count`, `admin_api.latency_ms`, `admin_api.errors` per endpoint.

- [ ] **Step 1: Middleware**

```python
# apps/backend/core/middleware/admin_metrics.py
import time
from starlette.middleware.base import BaseHTTPMiddleware
from core.observability.metrics import put_metric


class AdminMetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if not request.url.path.startswith("/api/v1/admin/"):
            return await call_next(request)
        started = time.monotonic()
        endpoint = request.url.path
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            put_metric("admin_api.call_count", 1, dimensions={"endpoint": endpoint})
            put_metric("admin_api.latency_ms", elapsed_ms, dimensions={"endpoint": endpoint})
            if status_code >= 500:
                put_metric("admin_api.errors", 1, dimensions={"endpoint": endpoint, "code": str(status_code)})
```

- [ ] **Step 2: Register in `main.py`**

```python
from routers import admin as admin_router
from core.middleware.admin_metrics import AdminMetricsMiddleware

app.add_middleware(AdminMetricsMiddleware)
app.include_router(admin_router.router, prefix="/api/v1")
```

Commit:

```
feat(backend): register admin router + admin_metrics middleware (O1)

Refs #351
```

---

### Task 23: Backend integration test

**Files:**
- Create: `apps/backend/tests/integration/test_admin_flow.py`

End-to-end: sign in as admin JWT → /admin/me 200 → /admin/users list → pick one → /admin/users/{id}/overview → fire container.reprovision → verify audit row via /admin/actions.

Runs against LocalStack DDB. Commit:

```
test(backend): admin flow integration test against LocalStack

Refs #351
```

---

## Phase D — Frontend foundation

### Task 24: Add `eslint-plugin-boundaries` + config (A2)

**Files:**
- Modify: `apps/frontend/package.json`
- Modify: `apps/frontend/eslint.config.mjs`

```bash
cd apps/frontend && pnpm add -D eslint-plugin-boundaries
```

Config:

```js
// apps/frontend/eslint.config.mjs
import boundaries from "eslint-plugin-boundaries";

export default [
  // ...existing config...
  {
    plugins: { boundaries },
    settings: {
      "boundaries/elements": [
        { type: "admin", pattern: "src/app/admin/**" },
        { type: "admin", pattern: "src/components/admin/**" },
        { type: "public", pattern: "src/**", mode: "file" },
      ],
    },
    rules: {
      "boundaries/element-types": [
        "error",
        {
          default: "disallow",
          rules: [
            { from: "public", allow: ["public"] },
            { from: "admin", allow: ["admin", "public"] }, // admin can use shared ui/ but not vice versa
          ],
        },
      ],
    },
  },
];
```

**Specifically:** `src/components/admin/**` must never be imported from outside `src/app/admin/**` or `src/components/admin/**`.

Test: `cd apps/frontend && pnpm lint` passes; attempt to import `@/components/admin/ConfirmActionDialog` from a public component fails lint.

Commit:

```
feat(frontend): eslint-plugin-boundaries for admin import isolation (A2)

Blocks imports from src/components/admin/* into non-admin code.
Keeps admin UI out of the public bundle.

Refs #351
```

---

### Task 25: Host-based middleware (A1)

**Files:**
- Modify: `apps/frontend/src/middleware.ts`
- Create: `apps/frontend/tests/unit/admin/middleware.test.ts`

**CEO A1:** default-to-404 on unknown hosts.

- [ ] **Step 1: Test**

```ts
import { describe, it, expect } from "vitest";

const adminHosts = new Set(["admin.isol8.co", "admin-dev.isol8.co", "admin.localhost:3000"]);

function isAdminHost(host: string): boolean {
  return adminHosts.has(host);
}

describe("middleware host gating", () => {
  it("allows admin.isol8.co on /admin/*", () => {
    expect(isAdminHost("admin.isol8.co")).toBe(true);
  });
  it("blocks isol8.co on /admin/*", () => {
    expect(isAdminHost("isol8.co")).toBe(false);
  });
  it("blocks unknown tunneled host", () => {
    expect(isAdminHost("random.ngrok.io")).toBe(false);
  });
});
```

- [ ] **Step 2: Implement**

```ts
// apps/frontend/src/middleware.ts
import { authMiddleware } from "@clerk/nextjs/server";
import { NextResponse, type NextRequest } from "next/server";

const ADMIN_HOSTS = new Set(
  (process.env.NEXT_PUBLIC_ADMIN_HOSTS || "admin.isol8.co,admin-dev.isol8.co,admin.localhost:3000")
    .split(",").map(h => h.trim())
);

function isAdminHost(host: string | null): boolean {
  return !!host && ADMIN_HOSTS.has(host);
}

export default authMiddleware({
  beforeAuth: (req: NextRequest) => {
    const host = req.headers.get("host");
    const isAdminPath = req.nextUrl.pathname.startsWith("/admin");
    const onAdminHost = isAdminHost(host);

    if (isAdminPath && !onAdminHost) {
      // default-to-404 on unknown hosts hitting /admin
      return new NextResponse(null, { status: 404 });
    }
    if (!isAdminPath && onAdminHost) {
      // admin host hitting non-admin route → redirect to /admin
      return NextResponse.redirect(new URL("/admin", req.url));
    }
  },
  publicRoutes: ["/", "/sign-in(.*)", "/sign-up(.*)"],
});

export const config = {
  matcher: ["/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?)).*)", "/"],
};
```

Also add an E2E Playwright test: `curl -H "Host: admin.isol8.co" localhost:3000/admin/` = 200; `curl -H "Host: isol8.co" localhost:3000/admin/` = 404.

Commit:

```
feat(frontend): host-based admin gating (A1 default-to-404)

Refs #351
```

---

### Task 26: Admin layout + not-authorized + sign-in

**Files:**
- Create: `apps/frontend/src/app/admin/layout.tsx`
- Create: `apps/frontend/src/app/admin/not-authorized/page.tsx`
- Create: `apps/frontend/src/app/admin/page.tsx`

```tsx
// layout.tsx — Server Component
import { redirect } from "next/navigation";
import { auth } from "@clerk/nextjs/server";
import { getAdminMe } from "./_lib/api";

export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const { userId, getToken } = auth();
  if (!userId) redirect("/sign-in");

  const token = await getToken();
  const me = await getAdminMe(token);
  if (!me?.is_admin) redirect("/admin/not-authorized");

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <nav className="border-b border-zinc-800 px-6 py-3 flex gap-6 text-sm">
        <a href="/admin/users" className="hover:underline">Users</a>
        <a href="/admin/health" className="hover:underline">Health</a>
        <span className="ml-auto text-zinc-500">{me.email}</span>
      </nav>
      <main className="p-6">{children}</main>
    </div>
  );
}
```

```tsx
// page.tsx — redirect
import { redirect } from "next/navigation";
export default function AdminIndex() { redirect("/admin/users"); }
```

```tsx
// not-authorized/page.tsx
export default function NotAuthorized() {
  return <div className="p-8">403 — You are not a platform admin.</div>;
}
```

Commit:

```
feat(frontend): admin layout + auth gate + not-authorized page

Refs #351
```

---

### Task 27: Admin API client (server-only)

**Files:**
- Create: `apps/frontend/src/app/admin/_lib/api.ts`

Server-only module — imported from Server Components/Actions. Never bundled into client.

```ts
// apps/frontend/src/app/admin/_lib/api.ts
import "server-only";

const API = process.env.API_URL || "http://localhost:8000";

async function req<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}/api/v1${path}`, {
    ...init,
    headers: { ...init?.headers, Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    cache: "no-store",
  });
  if (!r.ok) {
    const body = await r.text();
    throw new Error(`Admin API ${r.status}: ${body}`);
  }
  return r.json();
}

export async function getAdminMe(token: string | null) {
  if (!token) return null;
  try { return await req<{user_id: string; email: string; is_admin: boolean}>("/admin/me", token); }
  catch { return null; }
}

export async function listUsers(token: string, q: string = "", cursor?: string) {
  return req<{users: any[]; cursor?: string}>(
    `/admin/users?q=${encodeURIComponent(q)}${cursor ? `&cursor=${cursor}` : ""}`, token);
}

export async function getOverview(token: string, userId: string) {
  return req<any>(`/admin/users/${userId}/overview`, token);
}

export async function listAgents(token: string, userId: string, cursor?: string) {
  return req<any>(`/admin/users/${userId}/agents${cursor ? `?cursor=${cursor}` : ""}`, token);
}

export async function getAgentDetail(token: string, userId: string, agentId: string) {
  return req<any>(`/admin/users/${userId}/agents/${agentId}`, token);
}

export async function getPosthog(token: string, userId: string) {
  return req<any>(`/admin/users/${userId}/posthog`, token);
}

export async function getLogs(token: string, userId: string, opts: {level?: string; hours?: number; limit?: number; cursor?: string} = {}) {
  const qs = new URLSearchParams({
    level: opts.level || "ERROR",
    hours: String(opts.hours || 24),
    limit: String(opts.limit || 20),
    ...(opts.cursor ? { cursor: opts.cursor } : {}),
  });
  return req<any>(`/admin/users/${userId}/logs?${qs}`, token);
}

export async function getCloudwatchUrl(token: string, userId: string, start: string, end: string, level: string) {
  const qs = new URLSearchParams({ start, end, level });
  return req<{url: string}>(`/admin/users/${userId}/cloudwatch-url?${qs}`, token);
}

export async function getSystemHealth(token: string) {
  return req<any>("/admin/system/health", token);
}

export async function getActions(token: string, params: {target_user_id?: string; admin_user_id?: string; limit?: number; cursor?: string}) {
  const qs = new URLSearchParams(Object.entries(params).filter(([,v]) => v != null).map(([k,v]) => [k, String(v)]));
  return req<any>(`/admin/actions?${qs}`, token);
}
```

Commit:

```
feat(frontend): admin API client (server-only)

Refs #351
```

---

### Task 28: `ConfirmActionDialog` (S5 — 3-attempt lockout)

**Files:**
- Create: `apps/frontend/src/components/admin/ConfirmActionDialog.tsx`
- Create: `apps/frontend/tests/unit/admin/ConfirmActionDialog.test.tsx`

**CEO S5:** 3 wrong confirmations → locked, requires reload.

- [ ] **Step 1: Test**

```tsx
describe("ConfirmActionDialog", () => {
  it("locks after 3 wrong attempts", async () => {
    render(<ConfirmActionDialog confirmText="user@example.com" onConfirm={jest.fn()} actionLabel="Cancel sub">Body</ConfirmActionDialog>);
    const input = screen.getByRole("textbox");
    for (let i = 0; i < 3; i++) {
      fireEvent.change(input, { target: { value: "wrong" } });
      fireEvent.click(screen.getByText(/confirm/i));
    }
    expect(screen.getByText(/locked/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirm/i })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Implement**

```tsx
// apps/frontend/src/components/admin/ConfirmActionDialog.tsx
"use client";
import { useState } from "react";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Input } from "@/components/ui/input";

interface Props {
  confirmText: string;
  actionLabel: string;
  onConfirm: () => Promise<void> | void;
  children: React.ReactNode;
}

export function ConfirmActionDialog({ confirmText, actionLabel, onConfirm, children }: Props) {
  const [typed, setTyped] = useState("");
  const [attempts, setAttempts] = useState(0);
  const [busy, setBusy] = useState(false);
  const locked = attempts >= 3;
  const matches = typed === confirmText;

  return (
    <AlertDialog>
      <AlertDialogTrigger asChild>{children}</AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Confirm {actionLabel}</AlertDialogTitle>
          <AlertDialogDescription>
            {locked
              ? "Dialog locked after 3 wrong attempts. Reload the page to try again."
              : `Type ${confirmText} below to confirm.`}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <Input value={typed} onChange={e => setTyped(e.target.value)} disabled={locked || busy} aria-label="Confirmation input" />
        <AlertDialogFooter>
          <AlertDialogCancel disabled={busy}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            disabled={!matches || locked || busy}
            onClick={async () => {
              if (!matches) {
                setAttempts(a => a + 1);
                return;
              }
              setBusy(true);
              try { await onConfirm(); } finally { setBusy(false); }
            }}
            aria-busy={busy}
          >
            {busy ? "Working…" : `Confirm ${actionLabel}`}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
```

- [ ] **Step 3: Commit**

```
feat(frontend): ConfirmActionDialog with 3-attempt lockout (S5)

Refs #351
```

---

### Task 29: Shared admin components

**Files:**
- Create: `apps/frontend/src/components/admin/CodeBlock.tsx` (syntax-highlighted JSON)
- Create: `apps/frontend/src/components/admin/AuditRow.tsx`
- Create: `apps/frontend/src/components/admin/UserSearchInput.tsx`
- Create: `apps/frontend/src/components/admin/EmptyState.tsx` (U1)
- Create: `apps/frontend/src/components/admin/ErrorBanner.tsx`
- Create: `apps/frontend/src/components/admin/LogRow.tsx`

Each ~30-80 lines. `LogRow` has an expandable full-JSON view. `EmptyState` accepts `icon`, `title`, `body`, `action` props and renders a consistent first-run / empty-state block.

Commit:

```
feat(frontend): shared admin components (CodeBlock, LogRow, EmptyState, etc.)

Refs #351
```

---

## Phase E — Frontend pages

### Task 30: `/admin/health` page

**Files:**
- Create: `apps/frontend/src/app/admin/health/page.tsx`

Server Component fetching `/admin/system/health`. Renders:
- Top row: 3 status chips (Clerk / Stripe / DDB) — green/yellow/red
- Fleet tiles: running / provisioning / stopped / error counts
- Recent errors table (linked per-user)
- Background tasks panel
- Recent admin actions feed (last 20)

Commit:

```
feat(frontend): /admin/health platform dashboard

Refs #351
```

---

### Task 31: `/admin/users` directory

**Files:**
- Create: `apps/frontend/src/app/admin/users/page.tsx`

Server Component with search query + pagination. Uses `UserSearchInput` (client component) for the search box. `EmptyState` on day-1 zero-users case. Table columns: email / Clerk ID / plan / container status / signup / [view].

Commit:

```
feat(frontend): /admin/users directory (U1 empty state)

Refs #351
```

---

### Task 32: `/admin/users/[id]` layout (U2 — 6 tabs or sidebar)

**Files:**
- Create: `apps/frontend/src/app/admin/users/[id]/layout.tsx`

6 tabs (Overview / Agents / Billing / Container / Activity / Actions). On ≤1200px, collapse to left sidebar navigation.

Commit:

```
feat(frontend): user detail layout with tab/sidebar switch (U2)

Refs #351
```

---

### Task 33: `/admin/users/[id]/page.tsx` (Overview)

Server Component. Pulls `/admin/users/{id}/overview`. Renders identity card + billing card + container card + usage summary. Handles partial failures (each source shows its own error banner via `ErrorBanner`).

Commit:

```
feat(frontend): user Overview tab

Refs #351
```

---

### Task 34: Agents list page

**Files:**
- Create: `apps/frontend/src/app/admin/users/[id]/agents/page.tsx`

Server Component. Pulls `/admin/users/{id}/agents`. If `container_status !== "running"`, renders "Container is stopped — [Start container]" (E3). Paginated (D2). Each row links to `/admin/users/{id}/agents/{agent_id}`.

Commit:

```
feat(frontend): agents list page (E3 stopped, D2 pagination)

Refs #351
```

---

### Task 35: Agent detail page

**Files:**
- Create: `apps/frontend/src/app/admin/users/[id]/agents/[agent_id]/page.tsx`

Server Component. Pulls `/admin/users/{user_id}/agents/{agent_id}`. Renders:
- Header: agent name, model, tier, last active
- Skills list (name, version, source)
- **Config:** `<CodeBlock>` rendering `config_redacted` (secrets already masked server-side)
- Recent sessions table
- Actions footer: Delete agent (ConfirmActionDialog), Clear sessions (ConfirmActionDialog)

Commit:

```
feat(frontend): full agent detail page with redacted config display

Refs #351
```

---

### Task 36: Billing / Container / Activity / Actions tabs

Four pages, each ~60-100 lines. Billing and Container have inline action buttons (Server Action on click → ConfirmActionDialog → action fires). Activity renders the PostHog timeline. Actions renders the audit row table filtered by `target_user_id=this user`.

Commit:

```
feat(frontend): billing / container / activity / actions tabs

Refs #351
```

---

### Task 37: Server Actions for all writes

**Files:**
- Create: `apps/frontend/src/app/admin/_actions/{container,billing,account,config,agent}.ts`

Each file exports `"use server"` functions that call the backend via the admin API client. They generate an idempotency key per invocation and include it in the fetch. Return `{status, audit_status, run_id?}` to the caller component.

```ts
// apps/frontend/src/app/admin/_actions/container.ts
"use server";
import { auth } from "@clerk/nextjs/server";
import { randomUUID } from "crypto";

const API = process.env.API_URL!;

export async function reprovisionContainer(userId: string) {
  const { getToken } = auth();
  const token = await getToken();
  const res = await fetch(`${API}/api/v1/admin/users/${userId}/container/reprovision`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${token}`,
      "Content-Type": "application/json",
      "Idempotency-Key": randomUUID(),
    },
  });
  return res.json();
}

// stopContainer, startContainer, resizeContainer similarly
```

Commit:

```
feat(frontend): admin Server Actions for writes

Refs #351
```

---

## Phase F — Rollout + E2E

### Task 38: Local dev runbook

**Files:**
- Create: `docs/runbooks/admin-local-dev.md`

Covers `apps/backend/.env.local` setup (`PLATFORM_ADMIN_USER_IDS`, `POSTHOG_*`), `NEXT_PUBLIC_ADMIN_HOSTS=admin.localhost:3000`, visiting `http://admin.localhost:3000/admin` in Chrome, LocalStack DDB table auto-creation, PostHog stub behavior, CloudWatch LocalStack notes.

Commit:

```
docs(runbook): admin local dev setup

Refs #351
```

---

### Task 39: E2E test

**Files:**
- Create: `apps/frontend/tests/e2e/admin.spec.ts`

Playwright test: sign in as platform admin via Clerk admin API → set `NEXT_PUBLIC_ADMIN_HOSTS` to include the test host → navigate `/admin/users` → find test user → click → verify Overview loads → click Actions tab → verify empty audit list → trigger `container.stop` via Server Action UI → confirm dialog → audit row appears.

Commit:

```
test(e2e): admin dashboard golden-path spec

Refs #351
```

---

### Task 40: Rollout sequence

1. Merge this PR with all tests green.
2. Deploy backend with `ADMIN_UI_ENABLED=false`, `PLATFORM_ADMIN_USER_IDS` populated.
3. Deploy frontend (admin routes present but middleware gates).
4. Add CF Access policy for `admin-dev.isol8.co`, verify SSO works.
5. Set `ADMIN_UI_ENABLED_USER_IDS=<your_clerk_id>` in dev. Access `/admin`, verify full flow.
6. Repeat for prod (`admin.isol8.co`).
7. Expand `ADMIN_UI_ENABLED_USER_IDS` to the rest of the team.

**Rollback:** set `PLATFORM_ADMIN_USER_IDS=""` → every endpoint 403s. DNS remains; UI shows not-authorized.

---

## Verification checklist

Before merge:

- [ ] All unit tests pass: `pnpm test` + `cd apps/backend && uv run pytest`
- [ ] ESLint boundary rule enforced: `pnpm lint` passes; attempting to import an admin component from a public file fails
- [ ] Integration test passes against LocalStack: `uv run pytest tests/integration/test_admin_flow.py -v`
- [ ] E2E test passes: `pnpm --filter @isol8/frontend test:e2e -- admin.spec.ts`
- [ ] Manual check: non-admin JWT → `/admin/me` 403
- [ ] Manual check: Cloudflare Access SSO gate triggers on `admin-dev.isol8.co`
- [ ] Manual check: fire `container.reprovision` → audit row visible in Actions tab with correct admin + target + timestamp
- [ ] Manual check: deliberately break DDB connectivity → fire action → response returns with `audit_status: "panic"`; CloudWatch log shows CRITICAL panic entry
- [ ] Manual check: visit `admin.localhost:3000/admin` locally → full read flow works with LocalStack

After merge:

- [ ] Dev deploy + CF Access policy + per-user rollout
- [ ] 48h dev soak
- [ ] Prod deploy + CF Access policy + per-user rollout
- [ ] Add dashboard panel: `admin_api.call_count` by endpoint + admin_user_id

---

## CEO review fix map (all 18 threaded through tasks)

| # | Issue | Task(s) |
|---|---|---|
| A1 | Middleware default-to-404 | Task 25 |
| A2 | Pinned ESLint rule | Task 24 |
| A3 | Drop Stripe webhook queue | Task 12 (omitted from system_health) |
| E1 | Clerk rate-limit / cache | Task 15 |
| E2 | OpenClaw RPC timeout | Task 13, 16 |
| E3 | Container stopped | Task 13, 34 |
| E4 | CWL pagination | Task 8, 17 |
| E5 | PostHog 404 | Task 10, 17 |
| S1 | Audit fail-closed | Task 7 |
| S3 | openclaw.json redaction | Task 11, 13, 35 |
| S5 | ConfirmActionDialog lockout | Task 28 |
| D1 | Idempotency-Key | Task 18, 19, 37 |
| D2 | Agents pagination | Task 16, 34 |
| D3 | Navigate-away behavior | Task 18 (run_id returned), 37 |
| C1 | admin_service composes | Task 13 |
| P1 | Timeout wrappers | Task 13 |
| P2 | 30s health cache | Task 12 |
| O1 | admin_api metrics | Task 22 |
| R1 | ADMIN_UI_ENABLED feature flag | Task 3, 25 |
| R2 | Cloudflare Access runbook | Task 5 |
| U1 | Empty states | Task 29, 31 |
| U2 | Tab compression | Task 32 |
