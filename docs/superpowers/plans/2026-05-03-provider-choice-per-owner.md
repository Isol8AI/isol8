# Provider Choice Per Owner Implementation Plan

**Status:** In progress (main implementation shipped in PR #521; deferred cleanup PR pending)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `provider_choice` (and `byo_provider`) off the per-user `users` table onto the per-owner `billing_accounts` table, fix every reader/writer to key on `owner_id`, and add the missing org-context guard so `chatgpt_oauth` cannot be set on org owners.

**Architecture:** Single PR that adds the new repo write path, switches all readers + writers, updates the frontend picker (filter `chatgpt_oauth` for orgs + skip picker entirely when org's billing already has a choice), and ships a one-shot backfill script. Deferred cleanup PR removes `user_repo.set_provider_choice` and the legacy DDB column.

**Tech Stack:** FastAPI, Pydantic, DynamoDB, pytest (backend); Next.js 16 App Router, React 19, SWR, Clerk, vitest (frontend).

**Spec:** `docs/superpowers/specs/2026-05-03-provider-choice-per-owner-design.md`

**Testing convention:** Per saved feedback (`feedback_write_tests_run_at_end.md`), each task writes test files but does not run them mid-task. The final task runs the full suite.

---

## File structure

**Backend (modify):**
- `apps/backend/core/repositories/billing_repo.py` — add `set_provider_choice`, `clear_provider_choice`, with org invariant.
- `apps/backend/schemas/billing.py` — add `provider_choice` and `byo_provider` to `BillingAccountResponse`.
- `apps/backend/routers/billing.py` — `GET /billing/account` returns provider_choice; `POST /trial-checkout` writes provider_choice synchronously to billing_repo before Stripe call; webhook handler writes to billing_repo (instead of user_repo).
- `apps/backend/routers/container.py` — `_resolve_provider_choice` reads from billing_repo by `owner_id` (not user_id).
- `apps/backend/core/services/provision_gate.py` — `_get_provider_choice` reads from billing_repo by `owner_id`.
- `apps/backend/core/gateway/connection_pool.py` — chat-gate (line 651) and credit-deduction (line 1129) read from billing_repo by `owner_id` (not member's user_id).
- `apps/backend/routers/users.py` — drop `provider_choice` body from `POST /users/sync`; remove `provider_choice`/`byo_provider` from `GET /users/me` response.

**Backend (new):**
- `apps/backend/scripts/migrate_provider_choice.py` — one-shot backfill (run via `aws ecs run-task`).

**Backend (tests modify):**
- `apps/backend/tests/unit/repositories/test_billing_repo_provider_choice.py` (new).
- `apps/backend/tests/unit/routers/test_container_provision_gating.py` — flip mocks from user_repo to billing_repo.
- `apps/backend/tests/unit/routers/test_container_paperclip_autoprovision.py` — flip mocks.
- `apps/backend/tests/unit/routers/test_users.py` — assert /sync rejects `provider_choice` (or silently ignores), /me no longer returns provider fields.
- `apps/backend/tests/unit/routers/test_billing.py` — webhook persistence test updated for billing_repo.
- `apps/backend/tests/unit/services/test_provision_gate.py` — mock target update.

**Frontend (modify):**
- `apps/frontend/src/hooks/useBilling.ts` — expose `provider_choice` from `/billing/account`.
- `apps/frontend/src/components/chat/ProvisioningStepper.tsx` — three changes:
  - `ProviderPicker` filters `chatgpt_oauth` card when `isOrg`.
  - `handlePick` removes the `/users/sync` write call.
  - Skip rendering `ProviderPicker` entirely when `billing.provider_choice` is already set (org-member-joining-existing-org case).

**Frontend (tests modify/new):**
- `apps/frontend/src/components/chat/__tests__/ProvisioningStepper.test.tsx` — add tests for picker-filter (org), skip-picker (org-already-onboarded), and member-joining-without-prompt.

---

## Task 1: Add `billing_repo.set_provider_choice` with org invariant

**Files:**
- Modify: `apps/backend/core/repositories/billing_repo.py`
- Test: `apps/backend/tests/unit/repositories/test_billing_repo_provider_choice.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/repositories/test_billing_repo_provider_choice.py`:

```python
"""Tests for billing_repo.set_provider_choice with org invariant."""
from unittest.mock import patch

import pytest

from core.repositories import billing_repo


@pytest.mark.asyncio
async def test_set_provider_choice_personal_bedrock(dynamodb_table):
    await billing_repo.create_if_not_exists("user_x", "cus_abc", owner_type="personal")
    await billing_repo.set_provider_choice(
        "user_x",
        provider_choice="bedrock_claude",
        byo_provider=None,
        owner_type="personal",
    )
    row = await billing_repo.get_by_owner_id("user_x")
    assert row["provider_choice"] == "bedrock_claude"
    assert "byo_provider" not in row or row["byo_provider"] is None


@pytest.mark.asyncio
async def test_set_provider_choice_personal_byo_key(dynamodb_table):
    await billing_repo.create_if_not_exists("user_y", "cus_def", owner_type="personal")
    await billing_repo.set_provider_choice(
        "user_y",
        provider_choice="byo_key",
        byo_provider="openai",
        owner_type="personal",
    )
    row = await billing_repo.get_by_owner_id("user_y")
    assert row["provider_choice"] == "byo_key"
    assert row["byo_provider"] == "openai"


@pytest.mark.asyncio
async def test_set_provider_choice_personal_chatgpt_oauth(dynamodb_table):
    await billing_repo.create_if_not_exists("user_z", "cus_ghi", owner_type="personal")
    await billing_repo.set_provider_choice(
        "user_z",
        provider_choice="chatgpt_oauth",
        byo_provider=None,
        owner_type="personal",
    )
    row = await billing_repo.get_by_owner_id("user_z")
    assert row["provider_choice"] == "chatgpt_oauth"


@pytest.mark.asyncio
async def test_set_provider_choice_org_chatgpt_oauth_rejected(dynamodb_table):
    """ChatGPT OAuth cannot be set on org owners (decision 2026-04-30)."""
    await billing_repo.create_if_not_exists("org_x", "cus_jkl", owner_type="org")
    with pytest.raises(ValueError, match="chatgpt_oauth.*org"):
        await billing_repo.set_provider_choice(
            "org_x",
            provider_choice="chatgpt_oauth",
            byo_provider=None,
            owner_type="org",
        )


@pytest.mark.asyncio
async def test_set_provider_choice_org_bedrock(dynamodb_table):
    await billing_repo.create_if_not_exists("org_y", "cus_mno", owner_type="org")
    await billing_repo.set_provider_choice(
        "org_y",
        provider_choice="bedrock_claude",
        byo_provider=None,
        owner_type="org",
    )
    row = await billing_repo.get_by_owner_id("org_y")
    assert row["provider_choice"] == "bedrock_claude"


@pytest.mark.asyncio
async def test_set_provider_choice_unknown_provider_rejected(dynamodb_table):
    await billing_repo.create_if_not_exists("user_w", "cus_pqr", owner_type="personal")
    with pytest.raises(ValueError, match="unknown provider_choice"):
        await billing_repo.set_provider_choice(
            "user_w",
            provider_choice="invalid",
            byo_provider=None,
            owner_type="personal",
        )


@pytest.mark.asyncio
async def test_set_provider_choice_byo_key_without_provider_rejected(dynamodb_table):
    await billing_repo.create_if_not_exists("user_v", "cus_stu", owner_type="personal")
    with pytest.raises(ValueError, match="byo_provider required"):
        await billing_repo.set_provider_choice(
            "user_v",
            provider_choice="byo_key",
            byo_provider=None,
            owner_type="personal",
        )


@pytest.mark.asyncio
async def test_clear_provider_choice(dynamodb_table):
    await billing_repo.create_if_not_exists("user_u", "cus_vwx", owner_type="personal")
    await billing_repo.set_provider_choice(
        "user_u", provider_choice="byo_key", byo_provider="openai", owner_type="personal",
    )
    await billing_repo.clear_provider_choice("user_u")
    row = await billing_repo.get_by_owner_id("user_u")
    assert "provider_choice" not in row or row.get("provider_choice") is None
    assert "byo_provider" not in row or row.get("byo_provider") is None
```

(Re-uses the existing `dynamodb_table` fixture in `tests/unit/repositories/conftest.py`. Verify by `cat apps/backend/tests/unit/repositories/conftest.py | head -40` before assuming.)

- [ ] **Step 2: Add the implementation to `billing_repo.py`**

Append to `apps/backend/core/repositories/billing_repo.py` (after `set_subscription`, before any unrelated functions):

```python
_VALID_PROVIDER_CHOICES = frozenset({"bedrock_claude", "byo_key", "chatgpt_oauth"})


async def set_provider_choice(
    owner_id: str,
    *,
    provider_choice: str,
    byo_provider: str | None,
    owner_type: str,
) -> dict:
    """Persist the provider choice on a billing row.

    Args:
        owner_id: org_id or personal user_id.
        provider_choice: one of ``bedrock_claude``, ``byo_key``, ``chatgpt_oauth``.
        byo_provider: required when ``provider_choice == "byo_key"``; ``None``
            otherwise (also unset on the row when not byo_key).
        owner_type: ``"personal"`` or ``"org"``. Used for the org invariant.

    Raises:
        ValueError: unknown provider_choice, or chatgpt_oauth on an org row,
            or byo_key without byo_provider.
    """
    if provider_choice not in _VALID_PROVIDER_CHOICES:
        raise ValueError(f"unknown provider_choice: {provider_choice!r}")
    if owner_type == "org" and provider_choice == "chatgpt_oauth":
        # Decision 2026-04-30: ChatGPT OAuth is personal-only — orgs use
        # Bedrock or BYO API key. See memory/project_chatgpt_oauth_personal_only.md.
        raise ValueError(
            "chatgpt_oauth is not allowed for org owners; orgs must use bedrock_claude or byo_key",
        )
    if provider_choice == "byo_key" and byo_provider is None:
        raise ValueError("byo_provider required when provider_choice == 'byo_key'")

    now = utc_now_iso()
    table = _get_table()
    if provider_choice == "byo_key":
        update_expr = "SET provider_choice = :pc, byo_provider = :bp, updated_at = :t"
        values = {":pc": provider_choice, ":bp": byo_provider, ":t": now}
    else:
        update_expr = "SET provider_choice = :pc, updated_at = :t REMOVE byo_provider"
        values = {":pc": provider_choice, ":t": now}

    response = await run_in_thread(
        table.update_item,
        Key={"owner_id": owner_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )
    return response["Attributes"]


async def clear_provider_choice(owner_id: str) -> None:
    """Remove provider_choice and byo_provider from a billing row."""
    now = utc_now_iso()
    table = _get_table()
    await run_in_thread(
        table.update_item,
        Key={"owner_id": owner_id},
        UpdateExpression="REMOVE provider_choice, byo_provider SET updated_at = :t",
        ExpressionAttributeValues={":t": now},
    )
```

- [ ] **Step 3: Commit**

```bash
git add apps/backend/core/repositories/billing_repo.py apps/backend/tests/unit/repositories/test_billing_repo_provider_choice.py
git commit -m "feat(billing-repo): add set/clear_provider_choice with org invariant"
```

---

## Task 2: Surface `provider_choice` on `GET /billing/account`

**Files:**
- Modify: `apps/backend/schemas/billing.py` (`BillingAccountResponse`)
- Modify: `apps/backend/routers/billing.py` (the `account` endpoint)
- Test: `apps/backend/tests/unit/routers/test_billing_account_provider_choice.py` (new)

- [ ] **Step 1: Add `provider_choice` and `byo_provider` to `BillingAccountResponse`**

In `apps/backend/schemas/billing.py`, find `class BillingAccountResponse(BaseModel)` and add:

```python
class BillingAccountResponse(BaseModel):
    is_subscribed: bool
    current_spend: float
    lifetime_spend: float
    subscription_status: str | None = None
    trial_end: int | None = None
    # New fields for Workstream B:
    provider_choice: str | None = None
    byo_provider: str | None = None
```

- [ ] **Step 2: Populate the fields in the `account` endpoint**

In `apps/backend/routers/billing.py`, find `async def get_account(...)` (around line 70-110). After the existing `account = await _get_billing_account(auth)` line, the function builds `BillingAccountResponse(...)`. Add the two new fields:

```python
return BillingAccountResponse(
    is_subscribed=is_subscribed,
    current_spend=current_spend,
    lifetime_spend=lifetime_spend,
    subscription_status=subscription_status,
    trial_end=int(trial_end) if trial_end is not None else None,
    provider_choice=account.get("provider_choice") if account else None,
    byo_provider=account.get("byo_provider") if account else None,
)
```

- [ ] **Step 3: Write the test**

Create `apps/backend/tests/unit/routers/test_billing_account_provider_choice.py`:

```python
"""GET /billing/account exposes provider_choice for the frontend picker check."""
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_account_returns_provider_choice_from_billing_row(async_client, auth_headers):
    fake_account = {
        "owner_id": "user_x",
        "owner_type": "personal",
        "stripe_subscription_id": "sub_x",
        "subscription_status": "active",
        "provider_choice": "bedrock_claude",
    }
    with (
        patch("routers.billing.billing_repo.get_by_owner_id", new_callable=AsyncMock) as mock_get,
        patch("routers.billing.usage_service.get_usage_summary", new_callable=AsyncMock) as mock_usage,
    ):
        mock_get.return_value = fake_account
        mock_usage.return_value = {"total_spend": 0.0, "lifetime_spend": 0.0}
        resp = await async_client.get("/api/v1/billing/account", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider_choice"] == "bedrock_claude"
    assert body["byo_provider"] is None


@pytest.mark.asyncio
async def test_account_returns_null_provider_choice_when_unset(async_client, auth_headers):
    fake_account = {
        "owner_id": "user_y",
        "owner_type": "personal",
        "stripe_subscription_id": "sub_y",
        "subscription_status": "active",
    }
    with (
        patch("routers.billing.billing_repo.get_by_owner_id", new_callable=AsyncMock) as mock_get,
        patch("routers.billing.usage_service.get_usage_summary", new_callable=AsyncMock) as mock_usage,
    ):
        mock_get.return_value = fake_account
        mock_usage.return_value = {"total_spend": 0.0, "lifetime_spend": 0.0}
        resp = await async_client.get("/api/v1/billing/account", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["provider_choice"] is None
```

(Adjust the `patch` paths to match the actual import structure in `routers/billing.py`.)

- [ ] **Step 4: Commit**

```bash
git add apps/backend/schemas/billing.py apps/backend/routers/billing.py apps/backend/tests/unit/routers/test_billing_account_provider_choice.py
git commit -m "feat(billing): expose provider_choice on GET /billing/account"
```

---

## Task 3: Synchronous provider_choice write in `/trial-checkout`

**Files:**
- Modify: `apps/backend/routers/billing.py` (`create_trial_checkout`)
- Test: extend `apps/backend/tests/unit/routers/test_billing.py`

This closes the race window where the user lands on `/chat` and triggers `/container/provision` before the `customer.subscription.created` webhook lands and persists provider_choice.

- [ ] **Step 1: Write the failing test** (append to `apps/backend/tests/unit/routers/test_billing.py`)

```python
@pytest.mark.asyncio
async def test_trial_checkout_persists_provider_choice_synchronously(async_client, auth_headers):
    """Per Workstream B race-fix: /trial-checkout must write provider_choice
    to billing_accounts BEFORE creating the Stripe Checkout session, so
    /container/provision can read it without waiting for the async webhook.
    """
    from unittest.mock import AsyncMock, patch

    fake_account = {
        "owner_id": "user_x",
        "owner_type": "personal",
        "stripe_customer_id": "cus_abc",
    }

    with (
        patch("routers.billing._get_billing_account", new_callable=AsyncMock) as mock_acct,
        patch(
            "routers.billing.billing_repo.set_provider_choice",
            new_callable=AsyncMock,
        ) as mock_set_pc,
        patch(
            "routers.billing.create_flat_fee_checkout",
            new_callable=AsyncMock,
        ) as mock_checkout,
    ):
        mock_acct.return_value = fake_account
        mock_checkout.return_value = type("S", (), {"url": "https://checkout.stripe.com/foo"})()

        resp = await async_client.post(
            "/api/v1/billing/trial-checkout",
            json={"provider_choice": "bedrock_claude"},
            headers=auth_headers,
        )

    assert resp.status_code == 200
    mock_set_pc.assert_awaited_once_with(
        "user_x",
        provider_choice="bedrock_claude",
        byo_provider=None,
        owner_type="personal",
    )
    # Synchronous write happens BEFORE Stripe Checkout creation:
    assert mock_set_pc.await_args_list[0].args == ("user_x",) or "user_x" in str(mock_set_pc.await_args_list[0])
```

- [ ] **Step 2: Modify `create_trial_checkout`**

In `apps/backend/routers/billing.py`, find `async def create_trial_checkout(...)`. After the existing block:

```python
account = await _get_billing_account(auth)
if not account:
    owner_type = get_owner_type(auth)
    billing_service = BillingService()
    account = await billing_service.create_customer_for_owner(
        owner_id=owner_id,
        owner_type=owner_type,
        email=auth.email,
    )
```

(Around line 350-365, before the `_BLOCKED_REPEAT_STATUSES` block) — add:

```python
# Synchronously persist provider_choice on the billing row BEFORE
# creating the Stripe Checkout session. This closes the race window
# between Stripe Checkout completion and the customer.subscription.created
# webhook landing — /container/provision needs provider_choice to read
# from the billing row, and the webhook is async (seconds-to-minutes
# delay). The webhook handler still writes to the billing row as an
# idempotent backup. Spec: 2026-05-03-provider-choice-per-owner-design.md
await billing_repo.set_provider_choice(
    account["owner_id"],
    provider_choice=body.provider_choice,
    byo_provider=body.byo_provider if body.provider_choice == "byo_key" else None,
    owner_type=account.get("owner_type", get_owner_type(auth)),
)
```

(`body.byo_provider` will require the `TrialCheckoutRequest` schema to accept it. Update the model: `byo_provider: str | None = None`. Frontend already sends it for byo_key.)

- [ ] **Step 3: Update `TrialCheckoutRequest` schema**

In `apps/backend/routers/billing.py`, find `class TrialCheckoutRequest(BaseModel)` and add:

```python
class TrialCheckoutRequest(BaseModel):
    provider_choice: str = Field(..., description="chatgpt_oauth | byo_key | bedrock_claude")
    byo_provider: str | None = Field(None, description="openai | anthropic, required when provider_choice='byo_key'")
```

Add validation right after the existing `if body.provider_choice not in (...)` check:

```python
if body.provider_choice == "byo_key" and not body.byo_provider:
    raise HTTPException(status_code=400, detail="byo_provider required for byo_key")
```

- [ ] **Step 4: Commit**

```bash
git add apps/backend/routers/billing.py apps/backend/tests/unit/routers/test_billing.py
git commit -m "feat(billing): synchronously persist provider_choice on /trial-checkout"
```

---

## Task 4: Switch webhook handler to write to `billing_repo`

**Files:**
- Modify: `apps/backend/routers/billing.py` (the `customer.subscription.created`/`.updated` webhook branch around line 620-640)
- Test: extend `apps/backend/tests/unit/routers/test_billing.py`

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_webhook_persists_provider_choice_to_billing_repo(...):
    """customer.subscription.created webhook writes provider_choice to
    billing_accounts (not user_repo) — keyed on owner_id from the resolved
    account, not on metadata.clerk_user_id.
    """
    from unittest.mock import AsyncMock, patch

    event = {
        "type": "customer.subscription.created",
        "id": "evt_test_1",
        "data": {
            "object": {
                "id": "sub_x",
                "status": "trialing",
                "trial_end": 1779000000,
                "metadata": {
                    "owner_id": "org_x",
                    "clerk_user_id": "user_admin_y",
                    "provider_choice": "bedrock_claude",
                },
            }
        },
    }
    fake_account = {"owner_id": "org_x", "owner_type": "org"}

    with (
        patch("routers.billing._resolve_owner_account", new_callable=AsyncMock) as mock_resolve,
        patch("routers.billing.billing_repo.set_subscription", new_callable=AsyncMock) as mock_set_sub,
        patch("routers.billing.billing_repo.set_provider_choice", new_callable=AsyncMock) as mock_set_pc,
        patch("routers.billing.record_event_or_skip", new_callable=AsyncMock) as mock_dedup,
    ):
        mock_resolve.return_value = fake_account
        mock_dedup.return_value = type("R", (), {"name": "RECORDED"})()  # not ALREADY_SEEN
        # ... call the webhook endpoint with the signed event ...

    mock_set_pc.assert_awaited_once_with(
        "org_x",  # owner_id from billing row, NOT clerk_user_id from metadata
        provider_choice="bedrock_claude",
        byo_provider=None,
        owner_type="org",
    )
```

(Adjust to match the existing webhook test's auth signing pattern.)

- [ ] **Step 2: Replace the webhook persistence call**

In `apps/backend/routers/billing.py` around line 620-640, find:

```python
metadata_provider = metadata.get("provider_choice")
metadata_clerk_user_id = metadata.get("clerk_user_id") or account["owner_id"]
if metadata_provider in ("chatgpt_oauth", "byo_key", "bedrock_claude"):
    from core.repositories import user_repo

    try:
        await user_repo.set_provider_choice(
            metadata_clerk_user_id,
            provider_choice=metadata_provider,
        )
```

Replace with:

```python
metadata_provider = metadata.get("provider_choice")
metadata_byo = metadata.get("byo_provider")  # optional
if metadata_provider in ("chatgpt_oauth", "byo_key", "bedrock_claude"):
    try:
        await billing_repo.set_provider_choice(
            account["owner_id"],
            provider_choice=metadata_provider,
            byo_provider=metadata_byo if metadata_provider == "byo_key" else None,
            owner_type=account.get("owner_type", "personal"),
        )
    except ValueError:
        # Org invariant violation (chatgpt_oauth on org). Should not happen
        # post-Workstream-B because /trial-checkout's router-level guard at
        # line 335 rejects the same combo, but defense-in-depth.
        logger.exception(
            "Webhook tried to set invalid provider_choice for owner %s",
            account["owner_id"],
        )
```

(Drop the `from core.repositories import user_repo` lazy import line — that import path is no longer needed in this branch.)

- [ ] **Step 3: Commit**

```bash
git add apps/backend/routers/billing.py apps/backend/tests/unit/routers/test_billing.py
git commit -m "feat(billing): webhook writes provider_choice to billing_repo (was user_repo)"
```

---

## Task 5: `_resolve_provider_choice` reads from `billing_repo`

**Files:**
- Modify: `apps/backend/routers/container.py:71-86` (the `_resolve_provider_choice` helper)
- Modify: `apps/backend/core/services/provision_gate.py:_get_provider_choice` (introduced in Workstream A)
- Test: update `apps/backend/tests/unit/routers/test_container_provision_gating.py`, `test_container_paperclip_autoprovision.py`, `tests/unit/services/test_provision_gate.py`

Both helpers currently read from `user_repo` keyed on `clerk_user_id`. They must switch to `billing_repo` keyed on `owner_id`.

- [ ] **Step 1: Update `_resolve_provider_choice` in `container.py`**

Find:
```python
async def _resolve_provider_choice(clerk_user_id: str) -> tuple[str, str | None]:
    row = await user_repo.get(clerk_user_id)
    provider_choice = (row or {}).get("provider_choice") or "bedrock_claude"
    byo_provider = (row or {}).get("byo_provider") if provider_choice == "byo_key" else None
    return provider_choice, byo_provider
```

Replace with:
```python
async def _resolve_provider_choice(owner_id: str) -> tuple[str, str | None]:
    """Look up the owner's saved provider_choice (+ byo_provider) from billing_repo.

    Keys on owner_id (org_id in org context, user_id in personal context) —
    this is the post-Workstream-B model where provider_choice lives on the
    billing row, not the user row. Falls back to ``bedrock_claude`` when
    no row or no choice is persisted, matching the legacy default.
    """
    from core.repositories import billing_repo

    row = await billing_repo.get_by_owner_id(owner_id)
    provider_choice = (row or {}).get("provider_choice") or "bedrock_claude"
    byo_provider = (row or {}).get("byo_provider") if provider_choice == "byo_key" else None
    return provider_choice, byo_provider
```

Update each caller in `container.py` to pass `owner_id` instead of `auth.user_id`:

```bash
grep -n "_resolve_provider_choice" apps/backend/routers/container.py
```

Expected sites: lines around 104 (`_background_provision`), 137 (lazy import), and 333 (in `container_provision`). At each site, replace `auth.user_id` with `owner_id` (already in scope from `resolve_owner_id(auth)`).

- [ ] **Step 2: Update `_get_provider_choice` in `provision_gate.py`**

Find:
```python
async def _get_provider_choice(clerk_user_id: str) -> str:
    row = await user_repo.get(clerk_user_id)
    return (row or {}).get("provider_choice") or "bedrock_claude"
```

Replace with:
```python
async def _get_provider_choice(owner_id: str) -> str:
    """Read provider_choice from the billing row (post-Workstream-B model).

    Falls back to bedrock_claude when no row or choice is persisted —
    matches the legacy default and keeps recovery flows working for
    owners onboarded before Workstream B.
    """
    from core.repositories import billing_repo

    row = await billing_repo.get_by_owner_id(owner_id)
    return (row or {}).get("provider_choice") or "bedrock_claude"
```

Update the caller inside `evaluate_provision_gate`:
```python
# OLD: provider_choice = await _get_provider_choice(clerk_user_id)
# NEW:
provider_choice = await _get_provider_choice(owner_id)
```

Note: `_has_oauth_tokens` still keys on `clerk_user_id` because OAuth tokens are personal-only (per `project_chatgpt_oauth_personal_only.md`). Keep that call as-is.

- [ ] **Step 3: Update test mocks** in three files:

In `tests/unit/routers/test_container_provision_gating.py`, `tests/unit/routers/test_container_paperclip_autoprovision.py`:

Replace any:
```python
patch("routers.container.user_repo.get", ...)
```
with:
```python
patch("core.repositories.billing_repo.get_by_owner_id", ...)
```

And update the mocked return values from `{"provider_choice": "bedrock_claude"}` (a user row) to `{"owner_id": "...", "provider_choice": "bedrock_claude"}` (a billing row).

In `tests/unit/services/test_provision_gate.py`, replace the existing `_get_provider_choice` patches with patches on `core.services.provision_gate.billing_repo.get_by_owner_id` returning `{"provider_choice": "..."}` instead.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/routers/container.py apps/backend/core/services/provision_gate.py apps/backend/tests/
git commit -m "refactor(provider-choice): read from billing_repo by owner_id"
```

---

## Task 6: `connection_pool.py` reads provider_choice from billing_repo by owner

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py` (around lines 651 and 1129)
- Test: read existing test patterns and add coverage

Critical nuance: today the chat-gate at line 651 reads `user_repo.get(billing_user_id)` where `billing_user_id` is the **member** who sent the chat (in org context). After the change, `provider_choice` is keyed on the **owner** (the org), while credit deduction (which uses `billing_user_id` for the ledger lookup) stays per-member.

- [ ] **Step 1: Inspect both call sites**

```bash
awk 'NR>=640 && NR<=695' apps/backend/core/gateway/connection_pool.py
awk 'NR>=1120 && NR<=1140' apps/backend/core/gateway/connection_pool.py
```

Note `self.user_id` is the **owner_id** in this class (per existing CLAUDE.md naming — gateway pools are keyed per-owner). `billing_user_id` is the chatting member. After the change, the provider_choice lookup uses `self.user_id` (owner), credits stay on `billing_user_id` (member).

- [ ] **Step 2: Update line 651 (chat-time provider check)**

Find:
```python
user = await user_repo.get(billing_user_id)
if not user or user.get("provider_choice") != "bedrock_claude":
    return
```

Replace with:
```python
from core.repositories import billing_repo
account = await billing_repo.get_by_owner_id(self.user_id)
if not account or account.get("provider_choice") != "bedrock_claude":
    return
```

- [ ] **Step 3: Update line 1129 (credit-deduct gate)**

Find the same pattern:
```python
user = await user_repo.get(user_id)
if not user or user.get("provider_choice") != "bedrock_claude":
    return {"blocked": False}
```

Replace with:
```python
from core.repositories import billing_repo
account = await billing_repo.get_by_owner_id(self.user_id)
if not account or account.get("provider_choice") != "bedrock_claude":
    return {"blocked": False}
```

(`self.user_id` is the owner; `user_id` here is the member. Provider check moves to owner; balance check below stays on `user_id`.)

- [ ] **Step 4: Add tests**

In an appropriate gateway test file (find with `find apps/backend/tests -name "test_connection_pool*"`), add tests confirming:
1. Provider check uses `self.user_id` (owner) not `billing_user_id` (member).
2. When org has `provider_choice = bedrock_claude` but the chatting member is a fresh user with no user row, deduction still happens (because the lookup is on the org's billing row).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/gateway/connection_pool.py apps/backend/tests/
git commit -m "refactor(gateway): provider_choice keys on owner; credits stay per-member"
```

---

## Task 7: Drop `provider_choice` writes from `/users/sync`; remove from `/users/me`

**Files:**
- Modify: `apps/backend/routers/users.py`
- Modify: `apps/backend/schemas/user_schemas.py` (`SyncUserRequest`, `GetMeResponse` if exists)
- Test: update `apps/backend/tests/unit/routers/test_users.py`

Per the spec: `/users/sync` no longer accepts `provider_choice` (frontend writes via `/trial-checkout` only). `/users/me` no longer returns `provider_choice` (frontend reads from `/billing/account`).

- [ ] **Step 1: Drop the write from `sync_user`**

In `apps/backend/routers/users.py`, delete this block:
```python
if body is not None and body.provider_choice is not None:
    if body.provider_choice == "byo_key" and body.byo_provider is None:
        raise HTTPException(...)
    try:
        await user_repo.set_provider_choice(
            user_id,
            provider_choice=body.provider_choice,
            byo_provider=body.byo_provider,
        )
    except Exception as e:
        ...
```

Replace with a brief comment:
```python
# provider_choice writes were removed in Workstream B (2026-05-03);
# the canonical write path is now POST /billing/trial-checkout, which
# persists synchronously to billing_accounts before creating the
# Stripe Checkout session. /users/sync stays a pure user-row sync.
```

- [ ] **Step 2: Drop `provider_choice` from `SyncUserRequest`** schema in `apps/backend/schemas/user_schemas.py`. (Or keep the field but ignore it on the server — choose drop for cleanness; test confirms the field is rejected.)

- [ ] **Step 3: Drop `provider_choice` from `GET /users/me`**

```python
return {
    "user_id": auth.user_id,
    # provider_choice/byo_provider removed in Workstream B; the frontend
    # now reads them from GET /billing/account.
}
```

- [ ] **Step 4: Update tests**

In `tests/unit/routers/test_users.py`, change `test_sync_persists_provider_choice` to assert `provider_choice` is **not** persisted (use `mock_repo.set_provider_choice.assert_not_called()` style). Drop tests that depend on /me returning provider_choice.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/users.py apps/backend/schemas/user_schemas.py apps/backend/tests/unit/routers/test_users.py
git commit -m "refactor(users): drop provider_choice write on /sync and field on /me"
```

---

## Task 8: Frontend — picker filter, drop `/users/sync` write, skip-when-already-set

**Files:**
- Modify: `apps/frontend/src/hooks/useBilling.ts`
- Modify: `apps/frontend/src/components/chat/ProvisioningStepper.tsx`
- Test: extend `apps/frontend/src/components/chat/__tests__/ProvisioningStepper.test.tsx`

Three discrete frontend changes happen together because they're in the same file and tested as one component.

- [ ] **Step 1: Expose `provider_choice` from `useBilling`**

In `apps/frontend/src/hooks/useBilling.ts`, find the type definition for the `/billing/account` response. Add:
```typescript
export interface BillingAccount {
  is_subscribed: boolean;
  current_spend: number;
  lifetime_spend: number;
  subscription_status: string | null;
  trial_end: number | null;
  provider_choice: string | null;
  byo_provider: string | null;
}
```

(Match the existing type's exact name.)

- [ ] **Step 2: Filter `chatgpt_oauth` from `ProviderPicker` when `isOrg`**

In `apps/frontend/src/components/chat/ProvisioningStepper.tsx`, find the `ProviderPicker` component (around line 1028+). Find the `cards` array (or wherever the three cards are defined — `chatgpt_oauth`, `byo_key`, `bedrock_claude`). Wrap with:
```typescript
const cards: PickerCard[] = (
  isOrg
    ? ALL_CARDS.filter((c) => c.id !== "chatgpt_oauth")
    : ALL_CARDS
);
```

Update the section heading copy when `isOrg` (find the existing subhead and conditionalize):
```typescript
{isOrg
  ? "Choose how your team's container connects to Claude. Personal ChatGPT accounts can't be shared across an org."
  : "Choose how your container connects to Claude. Pick the path that fits."}
```

- [ ] **Step 3: Drop the `/users/sync` write from `handlePick`**

In `ProvisioningStepper.tsx` around line 368, find:
```typescript
if (providerChoice !== "byo_key") {
  await api.post("/users/sync", { provider_choice: providerChoice });
}
```

Delete this block. Replace with a comment:
```typescript
// provider_choice is no longer persisted on /users/sync (Workstream B
// 2026-05-03). The wizard's "Subscribe" step writes it synchronously
// to billing_accounts via POST /billing/trial-checkout, which is the
// only canonical write path now.
```

The `providerChoice` state stays — `handlePick` updates local state, and the trial-checkout call later in the wizard already includes it in the body.

- [ ] **Step 4: Skip the picker entirely when `billing.provider_choice` is set**

In `ProvisioningStepper.tsx` around line 416 (where the `!isSubscribed → ProviderPicker` early-return lives), update the condition:

```typescript
// OLD:
if (!isSubscribed) {
  return <ProviderPicker isOrg={isOrg} orgName={organization?.name} />;
}

// NEW:
if (!isSubscribed && !billing?.provider_choice) {
  return <ProviderPicker isOrg={isOrg} orgName={organization?.name} />;
}
```

This fixes the cofounder bug: a member joining an existing org with `billing.provider_choice = bedrock_claude` skips the picker entirely. The rest of the stepper falls through to its normal flow.

(`billing` here comes from `useBilling()` — verify the variable name in the existing file. Likely `billingData?.provider_choice` or similar.)

- [ ] **Step 5: Tests**

Add to `apps/frontend/src/components/chat/__tests__/ProvisioningStepper.test.tsx`:

```typescript
import { vi } from "vitest";

vi.mock("@/hooks/useBilling", () => ({
  useBilling: vi.fn(),
}));

import { useBilling } from "@/hooks/useBilling";
const useBillingMock = useBilling as ReturnType<typeof vi.fn>;

describe("ProviderPicker org filter", () => {
  it("hides chatgpt_oauth card when isOrg=true", () => {
    // Render ProvisioningStepper with isOrg=true (mock Clerk's organization
    // hook) and !isSubscribed and billing.provider_choice = null.
    // Assert: chatgpt_oauth card NOT in DOM, byo_key + bedrock_claude IS.
    // (See @/hooks/__tests__/useProvisioningState.test.tsx for the Clerk mock pattern.)
  });

  it("renders all 3 cards in personal context", () => {
    // isOrg=false → chatgpt_oauth visible.
  });
});

describe("ProvisioningStepper picker-skip", () => {
  it("skips picker when org member joins org with billing.provider_choice already set", () => {
    useBillingMock.mockReturnValue({
      billing: { provider_choice: "bedrock_claude", is_subscribed: false },
      isLoading: false,
      isSubscribed: false,
    });
    // ... mock other hooks (useProvisioningState, organization) as in
    //     existing tests
    // Render and assert: ProviderPicker NOT in DOM. The next stepper phase
    // (probably "container" or "ready") IS in DOM.
  });

  it("renders picker when billing has no provider_choice yet (initial onboarding)", () => {
    useBillingMock.mockReturnValue({
      billing: { provider_choice: null, is_subscribed: false },
      isLoading: false,
      isSubscribed: false,
    });
    // ... render and assert ProviderPicker IS in DOM.
  });
});
```

(Fill in the test bodies based on the project's existing testing-library patterns. The implementer should refer to `useProvisioningState.test.tsx` from Workstream A for the mock pattern.)

- [ ] **Step 6: Commit**

```bash
git add apps/frontend/src/hooks/useBilling.ts apps/frontend/src/components/chat/ProvisioningStepper.tsx apps/frontend/src/components/chat/__tests__/ProvisioningStepper.test.tsx
git commit -m "feat(frontend): provider picker filter for orgs, skip when billing has choice, drop /users/sync write"
```

---

## Task 9: Migration script

**Files:**
- Create: `apps/backend/scripts/migrate_provider_choice.py`
- Doc: append a runbook line to the script's module docstring

This is a one-shot script run via `aws ecs run-task` after the new code deploys.

- [ ] **Step 1: Write the script**

```python
"""One-shot backfill: copy provider_choice from users → billing_accounts.

Run via:
    aws ecs run-task \\
        --cluster isol8-prod-service-... \\
        --task-definition isol8-prod-backend-... \\
        --launch-type FARGATE \\
        --overrides '{"containerOverrides":[{"name":"backend","command":["python","scripts/migrate_provider_choice.py"]}]}' \\
        --network-configuration awsvpcConfiguration=...

Idempotent — re-running is safe. Skips rows that already have
provider_choice set.

Strategy: scan billing_accounts (the destination), and for each row
without provider_choice, look up the owner's user-side choice via the
users table and copy. For org rows we don't know which user originally
set the choice — we use the org admin's user row as the source if
findable, else skip and log.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from core.repositories import billing_repo, user_repo
from core.services.clerk_admin import ClerkAdminClient

logger = logging.getLogger(__name__)


async def _find_user_choice(billing_row: dict) -> tuple[str | None, str | None] | None:
    owner_id = billing_row["owner_id"]
    owner_type = billing_row.get("owner_type", "personal")

    if owner_type == "personal":
        # owner_id IS the clerk user_id.
        user = await user_repo.get(owner_id)
        if not user or not user.get("provider_choice"):
            return None
        return user.get("provider_choice"), user.get("byo_provider")

    # Org: find an org admin via Clerk, use their user row's choice.
    clerk = ClerkAdminClient()
    members = await clerk.list_org_members(owner_id)
    for member in members:
        if member.get("role") not in ("admin", "org:admin"):
            continue
        user = await user_repo.get(member["user_id"])
        if user and user.get("provider_choice"):
            return user.get("provider_choice"), user.get("byo_provider")
    return None


async def main() -> int:
    scanned = migrated = skipped_already = skipped_no_source = skipped_org_invariant = 0
    async for billing_row in billing_repo.scan_all():  # implementer: add scan_all helper if absent
        scanned += 1
        if billing_row.get("provider_choice"):
            skipped_already += 1
            continue
        result = await _find_user_choice(billing_row)
        if result is None:
            skipped_no_source += 1
            logger.warning("No source user choice found for owner %s", billing_row["owner_id"])
            continue
        provider_choice, byo_provider = result

        # Org invariant: chatgpt_oauth on org → skip (org will be re-prompted to pick).
        if billing_row.get("owner_type") == "org" and provider_choice == "chatgpt_oauth":
            skipped_org_invariant += 1
            logger.warning(
                "Org %s had chatgpt_oauth — skipping (orgs must use bedrock_claude or byo_key)",
                billing_row["owner_id"],
            )
            continue

        await billing_repo.set_provider_choice(
            billing_row["owner_id"],
            provider_choice=provider_choice,
            byo_provider=byo_provider if provider_choice == "byo_key" else None,
            owner_type=billing_row.get("owner_type", "personal"),
        )
        migrated += 1
        logger.info(
            "Migrated owner %s: provider_choice=%s byo_provider=%s",
            billing_row["owner_id"], provider_choice, byo_provider,
        )

    print(
        f"scanned={scanned} migrated={migrated} "
        f"skipped_already={skipped_already} skipped_no_source={skipped_no_source} "
        f"skipped_org_invariant={skipped_org_invariant}",
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(asyncio.run(main()))
```

- [ ] **Step 2: Add `scan_all` helper to `billing_repo.py` if missing**

```python
async def scan_all():
    """Async iterator over all billing rows. Used by the one-shot
    provider_choice migration. Not for production hot paths.
    """
    table = _get_table()
    response = await run_in_thread(table.scan)
    for item in response.get("Items", []):
        yield item
    while response.get("LastEvaluatedKey"):
        response = await run_in_thread(
            table.scan, ExclusiveStartKey=response["LastEvaluatedKey"],
        )
        for item in response.get("Items", []):
            yield item
```

- [ ] **Step 3: Commit**

```bash
git add apps/backend/scripts/migrate_provider_choice.py apps/backend/core/repositories/billing_repo.py
git commit -m "feat(scripts): one-shot provider_choice backfill from users → billing_accounts"
```

---

## Task 10: Final verification

- [ ] **Step 1: Backend tests**
```bash
cd apps/backend && uv run pytest tests/ -v 2>&1 | tail -50
```

Expected: all green. Most likely failure modes:
- Test mocks still reference `routers.container.user_repo.get` (Task 5 mock-flip incomplete).
- `test_billing.py` webhook test still expects `user_repo.set_provider_choice` (Task 4 mock-flip incomplete).

Fix any failures, then re-run.

- [ ] **Step 2: Frontend tests**
```bash
cd apps/frontend && pnpm test 2>&1 | tail -30
```

- [ ] **Step 3: Lint + TypeScript**
```bash
cd apps/frontend && pnpm run lint
cd apps/frontend && pnpm run build  # type-check via Next.js build
```

- [ ] **Step 4: Commit any verification fixes**
```bash
git add -A && git commit -m "test: full-suite verification fixups"
```

---

## Out of scope (deferred to follow-up PR)

- **`user_repo.set_provider_choice` / `clear_provider_choice` removal.** Keep the methods so the migration script can read from `users.provider_choice`. After the migration runs and dashboards confirm zero `users.provider_choice` lookups in production logs for a few days, ship a cleanup PR that:
  1. Deletes the two methods from `user_repo.py`.
  2. Drops `provider_choice` and `byo_provider` from the `users` DynamoDB items via a small one-off script (`UPDATE … REMOVE provider_choice, byo_provider`).
  3. Removes any remaining test fixtures referencing the old fields.

- **Switch-provider UI** (settings page that lets an owner change provider after onboarding). Own design.
- **Clerk `user.deleted` webhook → orphan personal-container cleanup.** Own ticket. Live evidence: `user_3CxcOiaf5GaHb69Gv1B7IYj8MBG`'s container is still running on prod since 2026-05-01.
- **BYOK-in-org semantics** (which member's API key does the org container use?). Own design.
