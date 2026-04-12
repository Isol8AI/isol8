# ORR Track C: Backend Security Fixes + Docs Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement 15 backend security fixes from #190 §3, build a DynamoDB throttle wrapper, add Clerk webhook idempotency, and clean up CLAUDE.md.

**Architecture:** Each security fix is a targeted change to an existing file. The DynamoDB throttle wrapper (`dynamodb_helper.py`) wraps all boto3 calls with metric emission and retry. The webhook dedup table is shared between Stripe and Clerk with a prefixed partition key.

**Tech Stack:** Python 3.12+, FastAPI, boto3, asyncio, DynamoDB, PyJWT, Fernet encryption, pytest

**Spec:** `docs/superpowers/specs/2026-04-11-orr-track-c-backend-security-design.md`
**Master spec:** `docs/superpowers/specs/2026-04-11-operational-readiness-review-design.md`

**Cross-track dependency:** This track imports `from core.observability.metrics import put_metric`. Track A creates this module. If Track A hasn't landed yet, create a minimal stub at `core/observability/metrics.py` that defines `put_metric` as a no-op, and rebase onto Track A's branch before merging.

---

### Task 1: CRITICAL — Fleet patch rate limit + audit + confirmation header (§3 Item 1)

**Files:**
- Modify: `apps/backend/routers/updates.py`

- [ ] **Step 1: Read `routers/updates.py` — understand `patch_fleet_config()` (~line 169)**

- [ ] **Step 2: Write the failing test**

```python
# apps/backend/tests/test_security_updates.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from main import app


@pytest.fixture
def admin_client():
    """Client with a mocked org admin auth context."""
    # Mock get_current_user to return an admin AuthContext
    ...


def test_fleet_patch_requires_confirmation_header(admin_client):
    """PATCH /container/config without X-Confirm-Fleet-Patch header returns 400."""
    resp = admin_client.patch("/api/v1/container/config", json={"test": "value"})
    assert resp.status_code == 400
    assert "X-Confirm-Fleet-Patch" in resp.json()["detail"]


def test_fleet_patch_with_header_succeeds(admin_client):
    """PATCH /container/config with confirmation header succeeds."""
    resp = admin_client.patch(
        "/api/v1/container/config",
        json={"test": "value"},
        headers={"X-Confirm-Fleet-Patch": "yes-i-am-sure"},
    )
    assert resp.status_code in (200, 204)
```

- [ ] **Step 3: Implement the fixes in `patch_fleet_config()`**

```python
# At the top of patch_fleet_config:
confirm = request.headers.get("X-Confirm-Fleet-Patch")
if confirm != "yes-i-am-sure":
    raise HTTPException(400, "Fleet patch requires X-Confirm-Fleet-Patch: yes-i-am-sure header")

# After validation passes:
import hashlib, json as json_mod
logger.warning(
    "Fleet config patch invoked",
    extra={
        "action": "fleet_patch",
        "actor_id": auth.user_id,
        "payload_hash": hashlib.sha256(json_mod.dumps(body, sort_keys=True).encode()).hexdigest(),
    },
)

# Emit metric (from Track A's module)
from core.observability.metrics import put_metric
put_metric("update.fleet_patch.invoked")

# SNS notification (if ALERT_PAGE_TOPIC_ARN is set)
import boto3, os
topic_arn = os.getenv("ALERT_PAGE_TOPIC_ARN")
if topic_arn:
    sns = boto3.client("sns")
    sns.publish(
        TopicArn=topic_arn,
        Subject="Fleet Config Patch Invoked",
        Message=f"Fleet config patch by {auth.user_id}",
    )
```

- [ ] **Step 4: Run tests, commit**

```bash
cd apps/backend && uv run pytest tests/test_security_updates.py -v
git add apps/backend/routers/updates.py apps/backend/tests/test_security_updates.py
git commit -m "security: fleet patch requires confirmation header + audit log + SNS alert"
```

---

### Task 2: CRITICAL — Cross-tenant config patch check (§3 Item 2)

**Files:**
- Modify: `apps/backend/routers/updates.py`

- [ ] **Step 1: Write failing test**

```python
def test_single_patch_blocks_cross_tenant(admin_client_org_a):
    """Admin from org A cannot patch a user in org B."""
    resp = admin_client_org_a.patch(
        "/api/v1/container/config/user-in-org-b",
        json={"test": "value"},
    )
    assert resp.status_code == 403
```

- [ ] **Step 2: Add tenant scoping to `patch_single_config()` (~line 147)**

```python
# After require_org_admin check:
target_container = await container_repo.get_by_owner(owner_id)
if target_container and auth.org_id:
    # Verify the target belongs to the caller's org
    target_user = await user_repo.get(owner_id)
    if not target_user or target_user.get("org_id") != auth.org_id:
        raise HTTPException(403, "Cannot patch user outside your organization")
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -am "security: add cross-tenant check on single-user config patch"
```

---

### Task 3: CRITICAL — Debug endpoint allow-list (§3 Item 3)

**Files:**
- Modify: `apps/backend/routers/debug.py`

- [ ] **Step 1: Write failing test**

```python
def test_debug_endpoints_blocked_in_prod(monkeypatch):
    """Debug endpoints return 403 when ENVIRONMENT=prod."""
    monkeypatch.setattr("core.config.settings.ENVIRONMENT", "prod")
    client = TestClient(app)
    resp = client.post("/api/v1/debug/provision")
    assert resp.status_code == 403
```

- [ ] **Step 2: Fix `require_non_production()`**

```python
PROD_ENVIRONMENTS = {"prod", "production", "staging"}

def require_non_production():
    env = (settings.ENVIRONMENT or "").lower().strip()
    if env in PROD_ENVIRONMENTS:
        put_metric("debug.endpoint.prod_hit", dimensions={"endpoint": "debug"})
        raise HTTPException(403, "Debug endpoints disabled in production")
```

- [ ] **Step 3: Run tests, commit**

---

### Task 4: CRITICAL — Path traversal fix (§3 Item 4)

**Files:**
- Modify: `apps/backend/core/containers/workspace.py`

- [ ] **Step 1: Write failing test**

```python
# apps/backend/tests/test_security_workspace.py
import pytest
from core.containers.workspace import WorkspaceManager

@pytest.mark.parametrize("malicious_path", [
    "../../../etc/passwd",
    "../../other-user/secrets",
    "alice_evil/foo",  # when user is 'alice'
    "/absolute/path",
    "normal/../../../escape",
])
def test_path_traversal_blocked(malicious_path):
    """Path traversal attempts should raise."""
    ws = WorkspaceManager(base_path="/tmp/test-efs")
    with pytest.raises(Exception):  # HTTPException or ValueError
        ws._resolve_user_file("alice", malicious_path)
```

- [ ] **Step 2: Fix `_resolve_user_file` (~line 114)**

```python
# Replace startswith check with:
try:
    resolved.relative_to(user_dir)
except ValueError:
    put_metric("workspace.path_traversal.attempt")
    raise HTTPException(403, "Path traversal blocked")
```

- [ ] **Step 3: Run tests, commit**

---

### Task 5: CRITICAL — Proxy budget enforcement (§3 Item 5)

**Files:**
- Modify: `apps/backend/routers/proxy.py`

- [ ] **Step 1: Read `proxy.py`, find `_authenticate_and_check_budget` (~line 35)**

- [ ] **Step 2: Re-wire the budget check for free tier**

```python
if auth_context.tier == "free":
    budget = await check_budget(resolve_owner_id(auth_context))
    if not budget["allowed"]:
        put_metric("proxy.budget_check.fail")
        raise HTTPException(429, "Free tier proxy budget exceeded")
```

- [ ] **Step 3: Write test, run, commit**

---

### Task 6: CRITICAL — Stripe webhook idempotency + dedup table (§3 Item 6)

**Files:**
- Modify: `apps/backend/routers/billing.py`
- Modify: `apps/infra/lib/stacks/database-stack.ts` (new DynamoDB table)

- [ ] **Step 1: Add dedup table to CDK**

In `database-stack.ts`, add:

```typescript
const webhookDedupTable = new dynamodb.Table(this, "WebhookEventDedup", {
  tableName: `isol8-${envName}-webhook-event-dedup`,
  partitionKey: { name: "event_id", type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  timeToLiveAttribute: "ttl",
  removalPolicy: cdk.RemovalPolicy.DESTROY,
});
```

Export the table name as a stack output.

- [ ] **Step 2: Add idempotency check to Stripe webhook handler**

```python
import time
from botocore.exceptions import ClientError

DEDUP_TABLE = os.getenv("WEBHOOK_DEDUP_TABLE", "isol8-dev-webhook-event-dedup")

async def _check_dedup(event_id: str) -> bool:
    """Returns True if this is a duplicate (already processed)."""
    table = dynamodb.Table(DEDUP_TABLE)
    try:
        table.put_item(
            Item={
                "event_id": f"stripe:{event_id}",
                "ttl": int(time.time()) + 30 * 86400,
            },
            ConditionExpression="attribute_not_exists(event_id)",
        )
        return False  # New event
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return True  # Duplicate
        raise

# In handle_stripe_webhook, after signature verification:
if await asyncio.to_thread(_check_dedup, event.id):
    put_metric("stripe.webhook.duplicate")
    return Response(status_code=200)
```

- [ ] **Step 3: Write test**

```python
def test_stripe_webhook_idempotent():
    """Replaying the same webhook should return 200 without re-processing."""
    # First call processes normally
    # Second call returns 200 with "duplicate" metric
```

- [ ] **Step 4: Commit**

```bash
git commit -am "security: add Stripe webhook idempotency with DynamoDB dedup"
```

---

### Task 7: Clerk webhook idempotency

**Files:**
- Modify: `apps/backend/routers/webhooks.py`

- [ ] **Step 1: Add the same dedup pattern to `handle_clerk_webhook`**

Reuse the same `webhook-event-dedup` table with `clerk:{event_id}` prefix.

```python
# After Svix signature verification:
if await asyncio.to_thread(_check_dedup_clerk, evt.id):
    put_metric("webhook.clerk.duplicate")
    return Response(status_code=200)
```

- [ ] **Step 2: Write test, commit**

---

### Task 8: HIGH — JWKS stale fallback cap + TTL lower (§3 Items 7-8)

**Files:**
- Modify: `apps/backend/core/auth.py`

- [ ] **Step 1: Lower TTL from 1h to 5m**

```python
# Line 18: change
JWKS_CACHE_TTL = timedelta(minutes=5)  # was: hours=1
```

- [ ] **Step 2: Cap stale fallback at 15 minutes**

In `_get_cached_jwks`, replace the stale fallback:

```python
except httpx.HTTPError as e:
    if _jwks_cache["data"]:
        staleness = (now - _jwks_cache["expires_at"]).total_seconds() + JWKS_CACHE_TTL.total_seconds()
        if staleness < 15 * 60:  # 15 min max stale
            logger.warning(f"JWKS fetch failed, using stale cache (age {staleness:.0f}s): {e}")
            put_metric("auth.jwks.refresh", dimensions={"status": "error"})
            return _jwks_cache["data"]
    put_metric("auth.jwks.refresh", dimensions={"status": "error"})
    raise  # Fail closed
```

- [ ] **Step 3: Add PyJWT leeway (§3 Item 17)**

In `_decode_token`, add `leeway=30` to `jwt.decode()`:

```python
return jwt.decode(
    token, public_key, algorithms=["RS256"],
    audience=settings.CLERK_AUDIENCE,
    issuer=settings.CLERK_ISSUER,
    leeway=30,  # tolerate 30s clock skew
)
```

- [ ] **Step 4: Write tests**

```python
def test_jwks_stale_fallback_capped():
    """Stale JWKS cache should be served up to 15 min, then fail closed."""

def test_jwt_leeway_tolerates_skew():
    """Token with iat 25s in the future should validate."""
```

- [ ] **Step 5: Commit**

```bash
git commit -am "security: cap JWKS stale fallback + lower TTL + add JWT leeway"
```

---

### Task 9: HIGH — Gateway token encryption (§3 Item 9)

**Files:**
- Modify: `apps/backend/core/services/key_service.py`
- Modify: `apps/backend/core/containers/config_store.py`
- Create: `apps/backend/scripts/backfill_gateway_token_encryption.py`

- [ ] **Step 1: Add encrypt/decrypt functions to key_service.py**

```python
def encrypt_gateway_token(token: str) -> str:
    """Encrypt gateway token using Fernet."""
    return f"enc:{_fernet.encrypt(token.encode()).decode()}"

def decrypt_gateway_token(blob: str) -> str:
    """Decrypt gateway token."""
    if not blob.startswith("enc:"):
        return blob  # plaintext (pre-migration)
    return _fernet.decrypt(blob[4:].encode()).decode()
```

- [ ] **Step 2: Migrate write/read paths in config_store.py**

- [ ] **Step 3: Create backfill script (idempotent)**

- [ ] **Step 4: Write tests, commit**

---

### Task 10: HIGH — WS Origin validation (§3 Item 12)

**Files:**
- Modify: `apps/infra/lambda/websocket-authorizer/index.py` (Python, NOT TypeScript)

- [ ] **Step 1: Read the current Lambda code**

- [ ] **Step 2: Add Origin allow-list check at the top of the handler**

```python
ALLOWED_ORIGINS = [
    'https://app.isol8.co',
    'https://dev.isol8.co',
    'https://app-dev.isol8.co',
    'http://localhost:3000',
]

origin = event.get('headers', {}).get('Origin') or event.get('headers', {}).get('origin')
if not origin or origin not in ALLOWED_ORIGINS:
    return generate_policy('user', 'Deny', event['methodArn'])
```

- [ ] **Step 3: Commit**

---

### Task 11: HIGH — Control UI session hijack fix + BYOK audit (§3 Items 11, 13)

**Files:**
- Modify: `apps/backend/routers/control_ui_proxy.py`
- Modify: `apps/backend/core/services/key_service.py`

- [ ] **Step 1: Fix control UI proxy — strip Referer, rate-limit session lookup**

- [ ] **Step 2: Add BYOK per-decrypt audit log**

```python
logger.info(
    "BYOK key decrypted",
    extra={"action": "byok_decrypt", "actor_id": user_id, "key_id": key_id},
)
```

- [ ] **Step 3: Create key rotation runbook**

Create `docs/ops/runbooks/byok-key-rotation.md`.

- [ ] **Step 4: Commit**

---

### Task 12: MEDIUM — Remaining fixes (§3 Items 15-16)

**Files:**
- Modify: `apps/backend/core/containers/workspace.py` (mcporter umask)
- Modify: `apps/backend/main.py` (health rate limit)

- [ ] **Step 1: Fix mcporter file permissions (~line 160)**

```python
import os
os.chmod(path, 0o600)
```

- [ ] **Step 2: Add health endpoint rate limiter**

Simple in-memory token bucket (100 req/min/IP):

```python
from collections import defaultdict
import time

_health_buckets: dict[str, list] = defaultdict(list)

@app.get("/health")
async def health(request: Request):
    ip = request.client.host
    now = time.time()
    _health_buckets[ip] = [t for t in _health_buckets[ip] if now - t < 60]
    if len(_health_buckets[ip]) >= 100:
        raise HTTPException(429, "Rate limited")
    _health_buckets[ip].append(now)
    # ... existing health logic
```

- [ ] **Step 3: Commit**

---

### Task 13: DynamoDB throttle wrapper

**Files:**
- Create: `apps/backend/core/services/dynamodb_helper.py`
- Create: `apps/backend/tests/test_dynamodb_helper.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/test_dynamodb_helper.py
import pytest
from unittest.mock import patch, MagicMock
from botocore.exceptions import ClientError

from core.services.dynamodb_helper import call_with_metrics


@pytest.mark.asyncio
async def test_throttle_retry_and_metric():
    """Throttle exception should be retried + emit dynamodb.throttle metric."""
    error = ClientError(
        {"Error": {"Code": "ProvisionedThroughputExceededException", "Message": ""}},
        "GetItem",
    )
    fn = MagicMock(side_effect=[error, {"Item": {"id": "1"}}])
    with patch("core.services.dynamodb_helper.put_metric") as mock_metric:
        result = await call_with_metrics("test-table", "get", fn)
    assert result == {"Item": {"id": "1"}}
    mock_metric.assert_called_with(
        "dynamodb.throttle", dimensions={"table": "test-table", "op": "get"}
    )


@pytest.mark.asyncio
async def test_non_throttle_error_emits_error_metric():
    """Non-throttle ClientError should emit dynamodb.error and re-raise."""
    error = ClientError(
        {"Error": {"Code": "ValidationException", "Message": "bad"}},
        "PutItem",
    )
    fn = MagicMock(side_effect=error)
    with patch("core.services.dynamodb_helper.put_metric") as mock_metric:
        with pytest.raises(ClientError):
            await call_with_metrics("test-table", "put", fn)
    mock_metric.assert_called_with(
        "dynamodb.error",
        dimensions={"table": "test-table", "op": "put", "error_code": "ValidationException"},
    )
```

- [ ] **Step 2: Implement the wrapper**

Use the code from Track C spec §5 (with `asyncio.to_thread` for sync boto3 calls).

- [ ] **Step 3: Run tests, commit**

---

### Task 14: Migrate repo files to DynamoDB wrapper

**Files:**
- Modify: `apps/backend/core/repositories/user_repo.py`
- Modify: `apps/backend/core/repositories/container_repo.py`
- Modify: `apps/backend/core/repositories/billing_repo.py`
- Modify: `apps/backend/core/repositories/api_key_repo.py` (verify exact name)
- Modify: `apps/backend/core/repositories/usage_repo.py`
- Modify: `apps/backend/core/repositories/update_repo.py`
- Modify: `apps/backend/core/repositories/channel_link_repo.py`
- Modify: `apps/backend/core/services/connection_service.py`

- [ ] **Step 1: Migrate one repo at a time**

For each repo file, replace direct `table.get_item(...)` calls with `await call_with_metrics(table.name, "get", table.get_item, ...)`. Run tests after each file.

Start with `user_repo.py` (simplest), then work through the list.

- [ ] **Step 2: Run full test suite after all migrations**

```bash
cd apps/backend && uv run pytest tests/ -v --timeout=60
```

- [ ] **Step 3: Commit**

```bash
git commit -am "feat: migrate all DynamoDB calls to throttle-aware wrapper"
```

---

### Task 15: CLAUDE.md cleanup

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Read CLAUDE.md and fix stale claims**

1. Backend infrastructure: "EC2" → "ECS Fargate"
2. Database: remove Supabase/Postgres/RDS references → "DynamoDB (8 tables, see database-stack.ts)"
3. Terraform: delete section → "Infrastructure: AWS CDK in `apps/infra/`"
4. Verify OpenClaw image pin is current
5. Add fleet-patch admin warning to Critical Rules
6. Verify desktop app says "Tauri (not Electron)"

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md — Fargate not EC2, CDK not Terraform, DynamoDB not Supabase"
```

---

### Task 16: Final test suite + lint

- [ ] **Step 1: Run full test suite**

```bash
cd apps/backend && uv run pytest tests/ -v --timeout=60
```

- [ ] **Step 2: Run linting**

```bash
cd apps/backend && uv run ruff check . && uv run ruff format --check .
```

- [ ] **Step 3: Fix any issues, commit**

- [ ] **Step 4: Report to lead**

SendMessage to the team lead with branch name, summary, test results, any deviations from spec.
