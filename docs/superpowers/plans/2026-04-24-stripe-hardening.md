# Stripe Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close 5 Stripe-integration gaps identified in the §8.4 audit (webhook dedup, idempotency keys on writes, Customer email sync, Stripe Tax, Customer Portal lockdown) so the backend is hardened for the upcoming flat-fee pivot.

**Architecture:** Backend-only changes plus one CDK env-var wiring. Reuses the already-provisioned (but unwired) `isol8-{env}-webhook-event-dedup` DDB table. Stripe Tax + Portal config are dashboard-side toggles documented at the end of the plan. Each task is independent; can ship to dev and prod incrementally.

**Tech Stack:** Python 3.13 (FastAPI / uvicorn), boto3 DynamoDB, `stripe` Python SDK, AWS CDK v2 (TypeScript), pytest with `moto` and `pytest-mock`.

---

## File Structure

**New files:**
- `apps/backend/core/services/webhook_dedup.py` — single-purpose DDB conditional-PutItem helper for "have we processed this Stripe `event.id` before?"
- `apps/backend/tests/unit/services/test_webhook_dedup.py` — unit tests using moto-mocked DDB.
- `apps/backend/tests/unit/routers/test_billing_webhook_dedup.py` — integration test for the dedup check inside the Stripe webhook handler.

**Modified files:**
- `apps/infra/lib/stacks/service-stack.ts` — pass `WEBHOOK_DEDUP_TABLE` env var to the backend Fargate task and grant it `dynamodb:PutItem` on the table.
- `apps/backend/core/config.py` — add `WEBHOOK_DEDUP_TABLE` setting.
- `apps/backend/routers/billing.py` — call dedup helper at the top of `handle_stripe_webhook`; add `automatic_tax` block to the existing checkout-session create.
- `apps/backend/core/services/billing_service.py` — add `idempotency_key` kwargs to every `stripe.X.create / .modify / .delete / .pay` call (~14 sites).
- `apps/backend/core/services/clerk_admin.py` — already wraps Clerk admin API; no change needed but referenced.
- `apps/backend/routers/webhooks.py` — extend the existing Clerk `user.updated` handler to push the new email to Stripe Customer (when one exists).

**No file deletions.**

**No new DDB tables** (the table already exists in CDK as `webhookDedupTable`).

---

## Task 1: Wire `WEBHOOK_DEDUP_TABLE` env var from CDK to backend

**Files:**
- Modify: `apps/infra/lib/stacks/service-stack.ts` — add env var to backend task definition; grant write permission on `webhookDedupTable`.
- Modify: `apps/backend/core/config.py` — add `WEBHOOK_DEDUP_TABLE: str = ""` setting.

- [ ] **Step 1: Find the backend task-definition block in service-stack.ts**

Run: `grep -n 'environment:' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/infra/lib/stacks/service-stack.ts | head -5`

You're looking for the `taskDefinition.addContainer` block that sets `environment` keys (USERS_TABLE, BILLING_TABLE, etc).

- [ ] **Step 2: Add the env var to the backend container**

In the `environment` object passed to `taskDefinition.addContainer({...})`, add (alphabetical with siblings):

```ts
WEBHOOK_DEDUP_TABLE: props.databaseStack.webhookDedupTable.tableName,
```

- [ ] **Step 3: Grant the backend role write permission on the table**

Find the block where `props.databaseStack.usersTable.grantReadWriteData(taskRole)` and similar grants happen. Add:

```ts
props.databaseStack.webhookDedupTable.grantWriteData(taskRole);
```

(Write-only is correct — the dedup helper uses conditional PutItem with `attribute_not_exists`. It never reads; the conditional failure IS the "already-seen" signal.)

- [ ] **Step 4: Add the env var to backend Settings**

Edit `apps/backend/core/config.py` — find the Settings class and add:

```python
WEBHOOK_DEDUP_TABLE: str = ""
```

(Place it alphabetically near `WS_CONNECTIONS_TABLE`.)

- [ ] **Step 5: Verify CDK synth still passes**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/infra && pnpm cdk synth isol8-dev > /dev/null && echo OK`
Expected: prints `OK`. (If it fails, the only common cause is a typo in the env-var name — check Step 2.)

- [ ] **Step 6: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/infra/lib/stacks/service-stack.ts apps/backend/core/config.py
git commit -m "$(cat <<'EOF'
infra: wire WEBHOOK_DEDUP_TABLE env var to backend Fargate task

The webhookDedupTable was provisioned in database-stack.ts months ago
but never wired to the backend. Pass the table name via env var and
grant the backend task role PutItem permission. Setting added to
core/config.py for downstream use.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `webhook_dedup.py` service with conditional-PutItem helper

**Files:**
- Create: `apps/backend/core/services/webhook_dedup.py`
- Test: `apps/backend/tests/unit/services/test_webhook_dedup.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/services/test_webhook_dedup.py`:

```python
"""Unit tests for the Stripe webhook event-dedup helper."""

import time
import boto3
import pytest
from moto import mock_aws

from core.services.webhook_dedup import (
    WebhookDedupResult,
    record_event_or_skip,
)


@pytest.fixture
def dedup_table():
    """Create a moto-mocked WEBHOOK_DEDUP_TABLE matching the CDK schema."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-webhook-event-dedup",
            KeySchema=[{"AttributeName": "event_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "event_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield "test-webhook-event-dedup"


@pytest.mark.asyncio
async def test_first_call_records_event(dedup_table, monkeypatch):
    """First call for a new event_id returns RECORDED."""
    monkeypatch.setenv("WEBHOOK_DEDUP_TABLE", dedup_table)
    result = await record_event_or_skip("evt_abc123", source="stripe")
    assert result is WebhookDedupResult.RECORDED


@pytest.mark.asyncio
async def test_second_call_skips_event(dedup_table, monkeypatch):
    """Second call for the same event_id returns ALREADY_SEEN."""
    monkeypatch.setenv("WEBHOOK_DEDUP_TABLE", dedup_table)
    first = await record_event_or_skip("evt_abc123", source="stripe")
    second = await record_event_or_skip("evt_abc123", source="stripe")
    assert first is WebhookDedupResult.RECORDED
    assert second is WebhookDedupResult.ALREADY_SEEN


@pytest.mark.asyncio
async def test_different_sources_share_namespace(dedup_table, monkeypatch):
    """event_id is global; the same id from different sources still dedupes.

    This is intentional — Stripe and Clerk event_id formats don't collide
    (Stripe uses evt_*, Clerk uses uuid). The `source` field is for
    debugging only.
    """
    monkeypatch.setenv("WEBHOOK_DEDUP_TABLE", dedup_table)
    first = await record_event_or_skip("shared_id", source="stripe")
    second = await record_event_or_skip("shared_id", source="clerk")
    assert first is WebhookDedupResult.RECORDED
    assert second is WebhookDedupResult.ALREADY_SEEN


@pytest.mark.asyncio
async def test_recorded_item_has_30day_ttl(dedup_table, monkeypatch):
    """Items expire 30 days after creation via the table's TTL attribute."""
    monkeypatch.setenv("WEBHOOK_DEDUP_TABLE", dedup_table)
    before = int(time.time())
    await record_event_or_skip("evt_ttl", source="stripe")
    after = int(time.time())

    client = boto3.client("dynamodb", region_name="us-east-1")
    item = client.get_item(
        TableName=dedup_table, Key={"event_id": {"S": "evt_ttl"}}
    )["Item"]
    ttl = int(item["ttl"]["N"])
    # 30 days = 2_592_000 seconds. Allow ±5s for clock jitter.
    assert before + 2_592_000 - 5 <= ttl <= after + 2_592_000 + 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_webhook_dedup.py -v`
Expected: 4 failures, all `ImportError` / `ModuleNotFoundError` for `core.services.webhook_dedup`.

- [ ] **Step 3: Implement the helper**

Create `apps/backend/core/services/webhook_dedup.py`:

```python
"""Idempotency helper for inbound webhooks (Stripe primarily, Clerk also).

Reuses the existing `isol8-{env}-webhook-event-dedup` DynamoDB table provisioned
by the database stack. Items have a 30-day TTL so the table never grows
unboundedly.

Pattern (per spec §8.4):
    result = await record_event_or_skip(event.id, source="stripe")
    if result is WebhookDedupResult.ALREADY_SEEN:
        return Response(status_code=200)  # silently ack the replay
    # ... process the event ...

Why a separate module: the dedup primitive is dead-simple (one conditional
PutItem) and used by ≥2 callers. Keeping it out of the routers means the
idempotency contract is testable in isolation.
"""

from __future__ import annotations

import enum
import time

import boto3
from botocore.exceptions import ClientError

from core.config import settings


_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days


class WebhookDedupResult(str, enum.Enum):
    RECORDED = "recorded"
    ALREADY_SEEN = "already_seen"


def _table():
    """Returns the boto3 Table resource. Created lazily so tests can monkeypatch
    the env var before the first call."""
    return boto3.resource("dynamodb", region_name=settings.AWS_REGION).Table(
        settings.WEBHOOK_DEDUP_TABLE
    )


async def record_event_or_skip(event_id: str, *, source: str) -> WebhookDedupResult:
    """Conditionally record a webhook event_id.

    Returns RECORDED on the first call for a given event_id. Returns
    ALREADY_SEEN on every subsequent call. Backed by DynamoDB conditional
    PutItem (`attribute_not_exists(event_id)`).

    Args:
        event_id: provider-issued event id (Stripe `evt_*`, Clerk uuid).
        source: free-form tag stored alongside the row for debugging.
            Does NOT affect dedup keying — event_id is the sole key.
    """
    now = int(time.time())
    try:
        _table().put_item(
            Item={
                "event_id": event_id,
                "source": source,
                "recorded_at": now,
                "ttl": now + _TTL_SECONDS,
            },
            ConditionExpression="attribute_not_exists(event_id)",
        )
        return WebhookDedupResult.RECORDED
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return WebhookDedupResult.ALREADY_SEEN
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_webhook_dedup.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/services/webhook_dedup.py apps/backend/tests/unit/services/test_webhook_dedup.py
git commit -m "$(cat <<'EOF'
feat(backend): add webhook_dedup helper backed by webhookDedupTable

Single-purpose conditional-PutItem against the existing
isol8-{env}-webhook-event-dedup table. Returns RECORDED first time, then
ALREADY_SEEN. 30-day TTL so the table self-cleans. Used by the Stripe
webhook handler in the next task; pattern reusable for Clerk webhooks
later.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Wire dedup check into the Stripe webhook handler

**Files:**
- Modify: `apps/backend/routers/billing.py:330-410` (the `handle_stripe_webhook` function).
- Test: `apps/backend/tests/unit/routers/test_billing_webhook_dedup.py`

- [ ] **Step 1: Write the failing integration test**

Create `apps/backend/tests/unit/routers/test_billing_webhook_dedup.py`:

```python
"""Integration test: replayed Stripe webhooks are no-ops thanks to dedup."""

import json
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def dedup_table_and_settings(monkeypatch):
    """Provision a moto-mocked dedup table and point the Settings at it."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-webhook-event-dedup",
            KeySchema=[{"AttributeName": "event_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "event_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("WEBHOOK_DEDUP_TABLE", "test-webhook-event-dedup")
        yield


@pytest.mark.asyncio
async def test_replayed_stripe_webhook_processed_once(
    dedup_table_and_settings, async_client, monkeypatch
):
    """Same event.id POSTed twice => underlying handler runs once."""

    fake_event = {
        "id": "evt_replay_test_1",
        "type": "customer.subscription.updated",
        "data": {"object": {"customer": "cus_x", "id": "sub_x", "status": "active"}},
    }

    # Bypass Stripe signature verification — we're testing dedup, not auth.
    monkeypatch.setattr(
        "stripe.Webhook.construct_event",
        lambda body, sig, secret: fake_event,
    )

    # Spy on the underlying repo write that the handler triggers.
    with patch(
        "core.repositories.billing_repo.update_subscription_status",
        new=AsyncMock(),
    ) as mock_write:
        body = json.dumps(fake_event)
        first = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=body,
            headers={"stripe-signature": "ignored"},
        )
        second = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=body,
            headers={"stripe-signature": "ignored"},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert mock_write.await_count == 1, (
        f"Expected 1 underlying write, got {mock_write.await_count}"
    )
```

(Note: this test assumes there's an `async_client` fixture in `conftest.py`. If not present, the test will error with a fixture-not-found message — see Step 2.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_billing_webhook_dedup.py -v`
Expected: FAIL — `mock_write.await_count == 2`, not 1, because the dedup check isn't wired yet (or fixture-not-found if `async_client` is missing — fix that by reusing the same fixture pattern from `tests/unit/routers/test_billing.py`).

- [ ] **Step 3: Add the dedup check to the handler**

Edit `apps/backend/routers/billing.py`. Find the `handle_stripe_webhook` function (around line 330). At the very top, immediately after the `event = stripe.Webhook.construct_event(...)` line and before any event-type branching, add:

```python
    from core.services.webhook_dedup import (
        WebhookDedupResult,
        record_event_or_skip,
    )

    dedup = await record_event_or_skip(event["id"], source="stripe")
    if dedup is WebhookDedupResult.ALREADY_SEEN:
        put_metric("stripe.webhook.dedup_skipped", dimensions={"event_type": event["type"]})
        return Response(status_code=200)
```

(The import is local to the function on purpose — keeps the router import-graph clean and the dedup module's boto3 client out of the cold-start path until first use.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_billing_webhook_dedup.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full billing test suite to confirm no regression**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_billing.py tests/unit/routers/test_billing_webhook_dedup.py -v`
Expected: all pass. If any preexisting tests fail, the dedup helper is being invoked when those tests don't expect it — they probably need to set the `WEBHOOK_DEDUP_TABLE` env var to a moto-mocked table too. Add the `dedup_table_and_settings` fixture to those tests' setup.

- [ ] **Step 6: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/routers/billing.py apps/backend/tests/unit/routers/test_billing_webhook_dedup.py
git commit -m "$(cat <<'EOF'
fix(billing): dedupe Stripe webhook events by event.id

Stripe replays webhooks on any non-2xx response and on its own at-least-once
delivery insurance. The handler previously had no dedup, so a replayed
payment_intent.succeeded would credit a balance twice (once the credit
ledger lands). Now the handler checks the existing webhookDedupTable and
silently 200s on a replay.

Adds a stripe.webhook.dedup_skipped CloudWatch metric so we can see how
often Stripe replays in practice.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Add `idempotency_key` to every Stripe write in `billing_service.py`

**Files:**
- Modify: `apps/backend/core/services/billing_service.py` (~14 sites identified by `grep -n 'stripe\.'`).
- Test: `apps/backend/tests/unit/services/test_billing_idempotency.py` (new)

**Why:** today, retried Stripe API calls (network blip, FastAPI request retry, our own self-heal logic in lines 105-115) can double-create a Customer or double-charge a card. Stripe's `idempotency_key` request header — passed via the `idempotency_key=` kwarg on every `stripe.X.create/modify/delete` call — collapses retries to a single side-effect on Stripe's side.

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/services/test_billing_idempotency.py`:

```python
"""Confirm every Stripe write in billing_service passes an idempotency_key."""

from unittest.mock import patch

import pytest
import stripe

from core.services import billing_service


@pytest.mark.asyncio
async def test_create_customer_passes_idempotency_key():
    """billing_service.create_billing_account passes idempotency_key=
    to stripe.Customer.create, derived from the owner_id."""
    with patch.object(
        stripe.Customer, "create", return_value=type("C", (), {"id": "cus_test"})()
    ) as mock_create, patch(
        "core.repositories.billing_repo.create_billing_account",
        return_value={"owner_id": "u_1", "stripe_customer_id": "cus_test"},
    ):
        await billing_service.create_billing_account(
            owner_id="u_1", email="x@y.com"
        )

    _, kwargs = mock_create.call_args
    assert kwargs.get("idempotency_key") == "create_customer:u_1", (
        f"Expected idempotency_key='create_customer:u_1', got {kwargs.get('idempotency_key')!r}"
    )
```

(One test for the most-called write. The same pattern extends to the other 13 sites; we add their tests after wiring the keys.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_billing_idempotency.py -v`
Expected: FAIL with `Expected idempotency_key='create_customer:u_1', got None`.

- [ ] **Step 3: Find all Stripe write sites**

Run: `grep -n 'stripe\.\(Customer\|Subscription\|checkout\|billing_portal\|Invoice\)\.' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/core/services/billing_service.py | grep -v '\.retrieve('`
Expected output: list of ~14 line numbers. Each is a write that needs `idempotency_key=`.

- [ ] **Step 4: Add `idempotency_key` to each write**

For each site identified in Step 3, add an `idempotency_key=` kwarg derived from the operation name + a stable id. Conventions:

| Operation | Key shape |
|---|---|
| `stripe.Customer.create(...)` | `f"create_customer:{owner_id}"` |
| `stripe.Customer.delete(customer_id)` | `f"delete_customer:{customer_id}"` |
| `stripe.checkout.Session.create(...)` | `f"checkout:{owner_id}:{int(time.time() // 300)}"` (5-min bucket — re-checkout in same 5 min returns same session) |
| `stripe.billing_portal.Session.create(...)` | `f"portal:{owner_id}:{int(time.time() // 300)}"` |
| `stripe.Subscription.modify(sub_id, ...)` | `f"sub_modify:{sub_id}:<short-op-name>"` (e.g. `:add_metered`, `:cancel`, `:pause`) |
| `stripe.Subscription.delete(sub_id)` | `f"sub_cancel:{sub_id}"` |
| `stripe.Customer.create_balance_transaction(...)` | `f"balance_tx:{customer_id}:<reason>"` |
| `stripe.Invoice.pay(invoice_id, ...)` | `f"invoice_pay:{invoice_id}"` |

Concrete example for the customer-create site (around line 72):

Before:
```python
with timing("stripe.api.latency", {"op": "customers.create"}):
    customer = stripe.Customer.create(
        email=email,
        metadata={"owner_id": owner_id},
    )
```

After:
```python
with timing("stripe.api.latency", {"op": "customers.create"}):
    customer = stripe.Customer.create(
        email=email,
        metadata={"owner_id": owner_id},
        idempotency_key=f"create_customer:{owner_id}",
    )
```

Apply the same pattern to every other write. **Import `time` at the top of the file if not already imported** (you'll need it for the time-bucketed keys). For non-async callers wrap nothing — `idempotency_key` is just a kwarg, not a context manager.

- [ ] **Step 5: Run the single test to verify it passes**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_billing_idempotency.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full billing service test suite**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/ tests/unit/routers/test_billing.py -v`
Expected: all pass. If any tests now fail because they assert on the exact arg list of a Stripe call, update those assertions to use partial-matching (`call_args.kwargs["customer"]` instead of `call_args == call(...)`).

- [ ] **Step 7: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/services/billing_service.py apps/backend/tests/unit/services/test_billing_idempotency.py
git commit -m "$(cat <<'EOF'
fix(billing): pass idempotency_key on every Stripe write

Stripe write calls in billing_service.py previously had no
idempotency_key — a retried HTTP call could double-create customers,
double-cancel subscriptions, etc. Now every create/modify/delete/pay
passes a deterministic key derived from operation + stable id (owner_id,
subscription_id, etc). Time-bucketed for checkout / portal sessions
(5-min window) so user-initiated retries re-use the same session.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Sync Clerk email changes to Stripe Customer

**Files:**
- Modify: `apps/backend/routers/webhooks.py` — extend the existing `user.updated` Clerk webhook handler.
- Test: `apps/backend/tests/unit/routers/test_webhooks_clerk_email_sync.py` (new)

**Why:** today, when a user changes their email in Clerk (settings UI), the Stripe Customer's `email` stays stale. Receipts, invoices, and trial-end notifications then go to the wrong address. The fix is one extra `stripe.Customer.modify` call inside the existing Clerk webhook path.

- [ ] **Step 1: Read the existing Clerk webhook handler**

Run: `grep -n 'user.updated\|user\\.updated\|user_updated' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/routers/webhooks.py`
Note the line number of the handler branch and read 30 lines around it. You're looking for the place where the handler currently updates the DDB user row on `user.updated`.

- [ ] **Step 2: Write the failing test**

Create `apps/backend/tests/unit/routers/test_webhooks_clerk_email_sync.py`:

```python
"""When Clerk fires user.updated with a new email, push it to Stripe Customer."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_user_updated_with_new_email_pushes_to_stripe(async_client, monkeypatch):
    # Existing user has a stripe_customer_id on file.
    fake_account = {
        "owner_id": "u_1",
        "stripe_customer_id": "cus_existing",
    }

    payload = {
        "type": "user.updated",
        "data": {
            "id": "u_1",
            "email_addresses": [
                {"id": "ea_1", "email_address": "new@example.com"}
            ],
            "primary_email_address_id": "ea_1",
        },
    }

    # Bypass Clerk signature verification.
    monkeypatch.setattr(
        "svix.webhooks.Webhook.verify",
        lambda self, body, headers: payload,
    )

    with patch(
        "core.repositories.billing_repo.get_by_owner_id",
        new=AsyncMock(return_value=fake_account),
    ), patch(
        "core.repositories.user_repo.update_user", new=AsyncMock()
    ), patch(
        "stripe.Customer.modify"
    ) as mock_stripe_modify:
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers={
                "svix-id": "msg_test",
                "svix-timestamp": "1234567890",
                "svix-signature": "ignored",
            },
        )

    assert resp.status_code == 200
    mock_stripe_modify.assert_called_once_with(
        "cus_existing",
        email="new@example.com",
        idempotency_key="customer_email_sync:u_1:new@example.com",
    )


@pytest.mark.asyncio
async def test_user_updated_without_stripe_customer_skips_sync(async_client, monkeypatch):
    """If the user has no Stripe customer yet, don't try to push email."""
    payload = {
        "type": "user.updated",
        "data": {
            "id": "u_1",
            "email_addresses": [{"id": "ea_1", "email_address": "x@y.com"}],
            "primary_email_address_id": "ea_1",
        },
    }
    monkeypatch.setattr(
        "svix.webhooks.Webhook.verify",
        lambda self, body, headers: payload,
    )

    with patch(
        "core.repositories.billing_repo.get_by_owner_id",
        new=AsyncMock(return_value=None),
    ), patch(
        "core.repositories.user_repo.update_user", new=AsyncMock()
    ), patch("stripe.Customer.modify") as mock_stripe_modify:
        resp = await async_client.post(
            "/api/v1/webhooks/clerk",
            json=payload,
            headers={
                "svix-id": "msg_test",
                "svix-timestamp": "1234567890",
                "svix-signature": "ignored",
            },
        )

    assert resp.status_code == 200
    mock_stripe_modify.assert_not_called()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_webhooks_clerk_email_sync.py -v`
Expected: FAIL — `mock_stripe_modify` was never called (we haven't wired the sync yet).

- [ ] **Step 4: Add the email-sync to the handler**

Inside the `user.updated` branch in `apps/backend/routers/webhooks.py` (after the existing `user_repo.update_user(...)` call), add:

```python
        # Sync the primary email to the user's Stripe Customer if one exists.
        # Catches receipt / invoice / trial-end emails going to a stale address.
        new_email = next(
            (
                e["email_address"]
                for e in event_data.get("email_addresses") or []
                if e["id"] == event_data.get("primary_email_address_id")
            ),
            None,
        )
        if new_email:
            account = await billing_repo.get_by_owner_id(event_data["id"])
            if account and account.get("stripe_customer_id"):
                try:
                    stripe.Customer.modify(
                        account["stripe_customer_id"],
                        email=new_email,
                        idempotency_key=f"customer_email_sync:{event_data['id']}:{new_email}",
                    )
                    put_metric("stripe.customer.email_sync", dimensions={"result": "ok"})
                except stripe.error.StripeError as e:
                    put_metric("stripe.customer.email_sync", dimensions={"result": "error"})
                    logger.warning(
                        "Stripe email sync failed for %s: %s",
                        event_data["id"], e,
                    )
                    # Non-fatal — the Clerk update succeeded; we just couldn't
                    # propagate to Stripe. Surface in metrics; user can retry
                    # by editing their email again, or we manually fix.
```

Make sure `import stripe` and `from core.repositories import billing_repo` and `from core.observability.metrics import put_metric` are at the top of the file (some may already be present — check before adding).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_webhooks_clerk_email_sync.py -v`
Expected: 2 passed.

- [ ] **Step 6: Run the full webhooks test suite**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_webhooks.py tests/unit/routers/test_webhooks_clerk_email_sync.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/routers/webhooks.py apps/backend/tests/unit/routers/test_webhooks_clerk_email_sync.py
git commit -m "$(cat <<'EOF'
feat(webhooks): sync Clerk email changes to Stripe Customer

When a user changes their email in Clerk, push the new address to their
Stripe Customer (if one exists) so receipts, invoices, and trial-end
emails go to the right place. Non-fatal on Stripe failure — Clerk update
still succeeds; emit a CloudWatch metric so we see propagation errors.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Enable Stripe Tax on subscription / checkout creates

**Files:**
- Modify: `apps/backend/core/services/billing_service.py` — add `automatic_tax={"enabled": True}` to the existing `stripe.checkout.Session.create(...)` call (around line 140) and to any other subscription-create site.
- Test: `apps/backend/tests/unit/services/test_billing_automatic_tax.py` (new)

**Why:** at $50/mo selling globally, we owe sales tax in TX/NY/WA (digital services) and VAT in EU/UK. Stripe Tax handles collection, registration tracking, and remittance — but only on subscriptions / invoices that opt in via `automatic_tax`. Without this we're either breaking tax law or eating tax out of margin.

This task wires the **code** side. The **dashboard** side (enable Tax, register jurisdictions) is in the manual-config section at the bottom of this plan.

- [ ] **Step 1: Find the checkout-session create call**

Run: `grep -n 'checkout.Session.create\|Subscription.create' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/core/services/billing_service.py`

Note the line numbers. The current code only has one `stripe.checkout.Session.create` call (around line 140). The flat-fee pivot's Subscription create lives in Plan 2 — for now we just add tax to the existing checkout path so today's flow becomes tax-compliant.

- [ ] **Step 2: Write the failing test**

Create `apps/backend/tests/unit/services/test_billing_automatic_tax.py`:

```python
"""Confirm checkout sessions are created with Stripe Tax enabled."""

from unittest.mock import patch

import pytest
import stripe

from core.services import billing_service


@pytest.mark.asyncio
async def test_create_checkout_passes_automatic_tax_enabled():
    """billing_service.create_checkout_session passes
    automatic_tax={'enabled': True} so Stripe collects tax."""

    fake_session = type("S", (), {"url": "https://checkout/x", "id": "cs_test"})()
    with patch.object(
        stripe.checkout.Session, "create", return_value=fake_session
    ) as mock_create, patch(
        "core.repositories.billing_repo.get_by_owner_id",
        return_value={
            "owner_id": "u_1",
            "stripe_customer_id": "cus_test",
        },
    ):
        await billing_service.create_checkout_session(
            owner_id="u_1", tier="starter"
        )

    _, kwargs = mock_create.call_args
    assert kwargs.get("automatic_tax") == {"enabled": True}, (
        f"Expected automatic_tax={{'enabled': True}}, got "
        f"{kwargs.get('automatic_tax')!r}"
    )
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_billing_automatic_tax.py -v`
Expected: FAIL — `kwargs.get('automatic_tax')` is None.

- [ ] **Step 4: Add `automatic_tax` to the checkout-session create**

Edit `apps/backend/core/services/billing_service.py` — find the `stripe.checkout.Session.create(...)` block and add `automatic_tax={"enabled": True}` to the kwargs. Concrete diff:

Before (around line 140):
```python
        session = stripe.checkout.Session.create(
            customer=billing_account["stripe_customer_id"],
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            idempotency_key=f"checkout:{owner_id}:{int(time.time() // 300)}",
        )
```

After:
```python
        session = stripe.checkout.Session.create(
            customer=billing_account["stripe_customer_id"],
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            automatic_tax={"enabled": True},
            customer_update={"address": "auto"},
            idempotency_key=f"checkout:{owner_id}:{int(time.time() // 300)}",
        )
```

(`customer_update={"address": "auto"}` is required by Stripe when `automatic_tax` is enabled and the customer doesn't yet have an address on file — it lets Stripe collect billing address during checkout. Without this kwarg, Stripe Tax fails the API call.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_billing_automatic_tax.py -v`
Expected: PASS.

- [ ] **Step 6: Run the full billing test suite**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/ tests/unit/routers/test_billing.py -v`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/services/billing_service.py apps/backend/tests/unit/services/test_billing_automatic_tax.py
git commit -m "$(cat <<'EOF'
feat(billing): enable Stripe automatic_tax on checkout sessions

At $50/mo selling globally we owe sales tax in TX/NY/WA + VAT in EU/UK.
Stripe Tax handles collection + remittance once automatic_tax is opted in
on the subscription. Wires the code side; dashboard-side enablement
(jurisdiction registrations, tax categories) is tracked in the plan's
manual-config section.

customer_update={'address': 'auto'} is required by Stripe when
automatic_tax is enabled and the customer has no address on file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Deploy + smoke test

**Files:** none — deploy only.

- [ ] **Step 1: Run the full backend test suite locally**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/ -v`
Expected: all pass. If any fail, fix before shipping — these are the canonical tests for everything we just changed.

- [ ] **Step 2: Run lint + type-check**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync && turbo run lint --filter=@isol8/backend`
Expected: PASS.

- [ ] **Step 3: Push to dev**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git push origin main
```

- [ ] **Step 4: Watch the CI/CD runs to completion**

```bash
sleep 10  # let GH register the push
RUN_ID=$(gh run list --repo Isol8AI/isol8 --branch main --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo Isol8AI/isol8 --exit-status
```

Expected: deploy.yml + backend.yml both succeed. (deploy.yml runs the CDK synth/deploy that ships the new env var; backend.yml runs the Docker build + ECS update.)

- [ ] **Step 5: Smoke test in dev**

In a browser console at `https://dev.isol8.co/chat`:

```javascript
// Trigger a Stripe Customer Portal create — exercises the idempotency_key
// kwarg AND the dedup-on-webhook path (Stripe doesn't fire a webhook for
// Portal but the create call exercises the new code).
await fetch('https://api-dev.isol8.co/api/v1/billing/portal', {
  method: 'POST',
  headers: { Authorization: 'Bearer ' + await Clerk.session.getToken() }
}).then(r => r.json())
```

Expected: returns `{ url: "https://billing.stripe.com/..." }`. If it 500s, check CloudWatch logs for the backend task — the most likely culprit is a typo in the idempotency_key f-string.

- [ ] **Step 6: Confirm dedup is firing in CloudWatch**

Replay any recent Stripe webhook from the Stripe dashboard (Test mode → Webhooks → pick the event → "Resend"). Then in CloudWatch Metrics, look for `Isol8/Backend → stripe.webhook.dedup_skipped` — it should have at least one data point in the last 5 minutes.

- [ ] **Step 7: No commit — this is a deploy-only task**

---

## Manual Stripe Dashboard Configuration (operator)

These are **not code changes** — do them in the Stripe dashboard before the flat-fee pivot launches. They pair with the code changes above.

- [ ] **Step 1: Enable Stripe Tax**
  - Stripe Dashboard → Tax → Get started.
  - Add tax registrations for jurisdictions where MAU is expected (start with US: register for sales tax in TX, NY, WA, CA — Stripe walks you through each).
  - For EU: register for VAT MOSS once MRR from EU customers crosses ~€10k/yr (below that, EU rules let you bill VAT-free as a non-EU seller; Stripe Tax still calculates correctly).
  - This activates `automatic_tax: enabled` server-side. Without this dashboard step, the API kwarg from Task 6 is a no-op.

- [ ] **Step 2: Lock down Customer Portal**
  - Stripe Dashboard → Settings → Customer portal.
  - Functionality: enable "Update payment method", "Cancel subscriptions", "View invoice history".
  - Disable: "Switch plans" (we don't have plans to switch between under flat fee), "Update billing address" (Stripe Tax handles this).
  - Save.

- [ ] **Step 3: Enable Stripe Radar default rules**
  - Stripe Dashboard → Radar → Rules.
  - Enable the default "Block payments where risk score > 75" if not already enabled.
  - Add a custom rule:
    > **If** :card_fingerprint: has been used > 2 times in the last 90 days **then** Block
  - This blocks trial abuse via a single payment card → many trials. It only matters once Plan 2 ships the trial-card-on-file flow, but enabling now is harmless.

---

## Self-Review

**Spec coverage check** (vs spec §8.4):

| §8.4 item | Covered by |
|---|---|
| Stripe Tax | Task 6 (code) + Manual Config Step 1 (dashboard) |
| Stripe Promotion Codes | **Deferred per spec** — explicitly out of scope |
| Stripe Radar | Manual Config Step 3 (dashboard) |
| Idempotency keys on writes | Task 4 |
| Webhook event dedup | Tasks 1 + 2 + 3 |
| Customer email sync | Task 5 |
| Customer Portal config lockdown | Manual Config Step 2 (dashboard) |

All §8.4 items present.

**Placeholder scan:** clean — every step has concrete code or commands.

**Type consistency:** `WebhookDedupResult.RECORDED` / `.ALREADY_SEEN` used consistently in Tasks 2 + 3. `idempotency_key` strings follow the convention table in Task 4 Step 4 throughout.

**Dependencies between tasks:**
- Task 1 (env var) → Task 2 (helper reads env var) → Task 3 (handler uses helper). Sequential.
- Task 4 (write idempotency) is independent of 1-3; can run in parallel.
- Task 5 (email sync) depends on Task 4 (uses `idempotency_key=` in the new `stripe.Customer.modify` call).
- Task 6 (tax) is independent of all others.
- Task 7 (deploy) depends on 1-6.

**Suggested execution order (single executor):** 1 → 2 → 3 → 4 → 5 → 6 → 7. Linear, ~1-2 days work.

**For parallel execution:** can run (1→2→3), 4, 6 in parallel; then 5 (depends on 4); then 7.
