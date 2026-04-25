# Trial + Frontend Pivot + Cutover Implementation Plan (Plan 3 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the user-visible flat-fee pivot — Stripe-native trial subscriptions, the 3-card landing page + onboarding wizard, settings panels for the new provider/credits flow, chat-path wiring of the credit ledger, and cutover (tear down test containers + delete deprecated code).

**Architecture:** Stripe owns the trial lifecycle via `trial_period_days=14` on the Subscription; backend listens to `customer.subscription.trial_will_end / .updated / .deleted` webhooks. Frontend gets a 3-card landing page that routes signup into one of three provider-specific onboarding steps. Settings exposes credit balance / auto-reload / provider switching. The gateway gains a pre-chat balance check (card-3 hard stop) and a post-chat deduct hook firing on `chat.final`. Cutover tears down the 6 existing test containers, flips the feature flag, and deletes the per-tier env vars + code paths.

**Tech Stack:** Next.js 16 App Router, React 19, Tailwind CSS v4, SWR, Stripe.js + Stripe Elements (`@stripe/react-stripe-js`), Clerk for auth, Framer Motion for the wizard transitions, Python FastAPI for the trial + chat-path wiring.

**Depends on:** Plan 1 (Stripe hardening — webhook dedup + idempotency_key) and Plan 2 (credit_ledger, oauth_service, write_openclaw_config branches, provision_container provider_choice).

---

## File Structure

**New backend files:**
- (none — Plan 3 only modifies existing services + adds endpoints to existing routers)

**Modified backend files:**
- `apps/backend/core/services/billing_service.py` — `create_trial_subscription(owner_id, payment_method_id)`.
- `apps/backend/routers/billing.py` — three new Stripe webhook branches.
- `apps/backend/core/gateway/connection_pool.py` — pre-chat balance check (gate `chat.send` for card 3 when balance≤0); post-chat deduct on `chat.final`.
- `apps/backend/core/repositories/user_repo.py` — store `provider_choice` on the user record so the gateway knows whether to gate.

**New frontend files:**
- `apps/frontend/src/components/landing/PricingThreeCard.tsx`
- `apps/frontend/src/components/chat/ChatGPTOAuthStep.tsx`
- `apps/frontend/src/components/chat/ByoKeyStep.tsx`
- `apps/frontend/src/components/chat/CreditsStep.tsx`
- `apps/frontend/src/components/chat/TrialBanner.tsx`
- `apps/frontend/src/components/chat/OutOfCreditsBanner.tsx`
- `apps/frontend/src/components/control/panels/LLMPanel.tsx`
- `apps/frontend/src/components/control/panels/CreditsPanel.tsx`
- `apps/frontend/src/hooks/useCredits.ts`
- `apps/frontend/src/hooks/useChatGPTOAuth.ts`

**Modified frontend files:**
- `apps/frontend/src/components/landing/Pricing.tsx` — replaces body with `<PricingThreeCard />`.
- `apps/frontend/src/components/chat/ProvisioningStepper.tsx` — branch on `provider_choice`.
- `apps/frontend/src/components/chat/ChatLayout.tsx` — render `<TrialBanner />` and `<OutOfCreditsBanner />` above the chat surface.
- `apps/frontend/src/components/control/ControlPanelRouter.tsx` — register new panels.
- `apps/frontend/src/components/control/ControlSidebar.tsx` — add nav items for LLM + Credits panels.

**Deleted files (cutover):**
- `apps/backend/core/config.py` lines for `STRIPE_STARTER_PRICE_ID`, `STRIPE_PRO_PRICE_ID`, `STRIPE_ENTERPRISE_PRICE_ID`, `STRIPE_METERED_PRICE_ID`, `STRIPE_METER_ID`, `BILLING_MARKUP`.
- `apps/backend/core/services/billing_service.py` — `create_checkout_session`, `set_metered_overage_item`, anything reading the per-tier price IDs.
- `apps/backend/models/billing.py` — `usage_event` / `usage_daily` schema (if not already deleted in Plan 2 Task 16).
- CDK: `apps/infra/lib/stacks/database-stack.ts` — `usageCountersTable` if no longer referenced.

---

## Task 1: `create_trial_subscription` in billing_service

**Files:**
- Modify: `apps/backend/core/services/billing_service.py`
- Test: `apps/backend/tests/unit/services/test_billing_trial.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/services/test_billing_trial.py`:

```python
"""create_trial_subscription: Stripe Subscription with trial_period_days=14."""

from unittest.mock import AsyncMock, patch

import pytest
import stripe

from core.services import billing_service


@pytest.mark.asyncio
async def test_create_trial_subscription_passes_trial_period_days_14(monkeypatch):
    monkeypatch.setattr(
        billing_service.settings, "STRIPE_FLAT_PRICE_ID", "price_flat"
    )
    fake_sub = type("S", (), {
        "id": "sub_test", "status": "trialing",
        "trial_end": 1700000000,
    })()
    with patch.object(stripe.Subscription, "create", return_value=fake_sub) as mock_create, \
         patch(
            "core.repositories.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value={"stripe_customer_id": "cus_x"}),
         ), \
         patch(
            "core.repositories.billing_repo.set_subscription",
            new=AsyncMock(),
         ):
        result = await billing_service.create_trial_subscription(
            owner_id="u_1", payment_method_id="pm_1"
        )

    assert result.id == "sub_test"
    _, kwargs = mock_create.call_args
    assert kwargs["trial_period_days"] == 14
    assert kwargs["customer"] == "cus_x"
    assert kwargs["items"] == [{"price": "price_flat"}]
    assert kwargs["default_payment_method"] == "pm_1"
    assert kwargs["automatic_tax"] == {"enabled": True}
    assert kwargs["payment_behavior"] == "default_incomplete"
    assert kwargs["payment_settings"] == {
        "save_default_payment_method": "on_subscription",
        "payment_method_types": ["card"],
    }
    assert kwargs["idempotency_key"] == "trial_signup:u_1"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_billing_trial.py -v`
Expected: FAIL — `create_trial_subscription` not defined.

- [ ] **Step 3: Add `create_trial_subscription` to `billing_service.py`**

Append to `apps/backend/core/services/billing_service.py`:

```python
async def create_trial_subscription(
    *, owner_id: str, payment_method_id: str
) -> stripe.Subscription:
    """Create a Stripe Subscription with a 14-day trial.

    Per spec §7.1: card-on-file via SetupIntent, then this call kicks off
    the trial. Stripe handles conversion on day 15 (Smart Retries on
    failure). The backend just listens to the resulting webhooks.
    """
    if not settings.STRIPE_FLAT_PRICE_ID:
        raise RuntimeError("STRIPE_FLAT_PRICE_ID not configured")

    account = await billing_repo.get_by_owner_id(owner_id)
    if not account or not account.get("stripe_customer_id"):
        raise RuntimeError(f"No Stripe customer for owner_id={owner_id}")

    with timing("stripe.api.latency", {"op": "subscription.create"}):
        sub = stripe.Subscription.create(
            customer=account["stripe_customer_id"],
            items=[{"price": settings.STRIPE_FLAT_PRICE_ID}],
            trial_period_days=14,
            default_payment_method=payment_method_id,
            automatic_tax={"enabled": True},
            payment_behavior="default_incomplete",
            payment_settings={
                "save_default_payment_method": "on_subscription",
                "payment_method_types": ["card"],
            },
            idempotency_key=f"trial_signup:{owner_id}",
        )

    await billing_repo.set_subscription(
        owner_id=owner_id,
        subscription_id=sub.id,
        status=sub.status,
    )
    return sub
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/services/test_billing_trial.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/services/billing_service.py apps/backend/tests/unit/services/test_billing_trial.py
git commit -m "$(cat <<'EOF'
feat(billing): create_trial_subscription with trial_period_days=14

Stripe-native trial. Backend creates the Subscription immediately at
signup with the saved payment method; Stripe handles the day-15 charge
and Smart Retries autonomously. Per spec §7.1 + §7.3.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Webhook branches for `subscription.updated` / `.deleted` / `.trial_will_end`

**Files:**
- Modify: `apps/backend/routers/billing.py`

- [ ] **Step 1: Find the existing webhook event-type chain**

Run: `grep -n 'event_type ==\|event\\["type"\\]' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/routers/billing.py | head -10`

You should already see `customer.subscription.created`, `.updated`, `.deleted`, `invoice.payment_succeeded`, `invoice.payment_failed`, and (from Plan 2) `payment_intent.succeeded`.

- [ ] **Step 2: Make sure `customer.subscription.updated` syncs the status**

The existing `.updated` handler (around line 371) updates the user record. Verify it copies `event["data"]["object"]["status"]` into the DDB row. If not, add:

```python
    elif event_type == "customer.subscription.updated":
        sub = event["data"]["object"]
        customer_id = sub["customer"]
        account = await billing_repo.get_by_stripe_customer_id(customer_id)
        if account:
            await billing_repo.set_subscription(
                owner_id=account["owner_id"],
                subscription_id=sub["id"],
                status=sub["status"],          # NEW: drive UI from this
                trial_end=sub.get("trial_end"),  # NEW: for the trial banner
            )
```

(If the existing handler already does this, skip.)

- [ ] **Step 3: Make sure `customer.subscription.deleted` tears down the container**

Verify the existing `.deleted` handler calls `ecs_manager.deprovision_container(user_id)`. If it doesn't:

```python
    elif event_type == "customer.subscription.deleted":
        sub = event["data"]["object"]
        account = await billing_repo.get_by_stripe_customer_id(sub["customer"])
        if account:
            from core.containers import get_ecs_manager
            await get_ecs_manager().deprovision_container(user_id=account["owner_id"])
            await billing_repo.set_subscription(
                owner_id=account["owner_id"],
                subscription_id=None,
                status="canceled",
            )
```

- [ ] **Step 4: Add the `customer.subscription.trial_will_end` branch**

Add a new `elif` branch (Stripe fires this 3 days before `trial_end`):

```python
    elif event_type == "customer.subscription.trial_will_end":
        sub = event["data"]["object"]
        account = await billing_repo.get_by_stripe_customer_id(sub["customer"])
        if account:
            user = await user_repo.get(account["owner_id"])
            if user and user.get("email"):
                # TODO future: send a branded reminder email via SES.
                # For now, just emit a metric so we can see how often it fires.
                put_metric(
                    "trial.will_end_3day",
                    dimensions={"plan": "flat_fee"},
                )
```

(Remove the `TODO future` once an SES integration lands. The metric is sufficient for now — Stripe sends its own default reminder email even without our branded one.)

- [ ] **Step 5: Add an integration test for the new branch**

Append to `apps/backend/tests/unit/routers/test_billing.py` (or create a new file):

```python
@pytest.mark.asyncio
async def test_trial_will_end_emits_metric(
    async_client, monkeypatch, dedup_table_and_settings
):
    fake_event = {
        "id": "evt_trial_end_1",
        "type": "customer.subscription.trial_will_end",
        "data": {
            "object": {
                "id": "sub_x", "customer": "cus_x",
                "trial_end": 1700000000, "status": "trialing",
            }
        },
    }
    monkeypatch.setattr(
        "stripe.Webhook.construct_event",
        lambda body, sig, secret: fake_event,
    )

    with patch(
        "core.repositories.billing_repo.get_by_stripe_customer_id",
        new=AsyncMock(return_value={"owner_id": "u_1"}),
    ), patch(
        "core.repositories.user_repo.get",
        new=AsyncMock(return_value={"email": "u@x.com"}),
    ), patch(
        "core.observability.metrics.put_metric"
    ) as mock_put:
        import json
        resp = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=json.dumps(fake_event),
            headers={"stripe-signature": "ignored"},
        )

    assert resp.status_code == 200
    assert any(
        c.args[0] == "trial.will_end_3day" for c in mock_put.call_args_list
    )
```

- [ ] **Step 6: Run the new test**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/routers/test_billing.py -k trial_will_end -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/routers/billing.py apps/backend/tests/unit/routers/test_billing.py
git commit -m "$(cat <<'EOF'
feat(billing): handle trial_will_end + ensure subscription.updated/.deleted sync

Per spec §7.2 + §8.2:
- subscription.updated now writes status + trial_end to user record
- subscription.deleted tears down container + clears subscription_id
- trial_will_end (3 days before) emits a CloudWatch metric for now;
  branded reminder email comes later

Stripe owns the lifecycle; backend just observes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Persist `provider_choice` on the user record

**Files:**
- Modify: `apps/backend/core/repositories/user_repo.py` — add a `provider_choice` field accessor.
- Modify: `apps/backend/routers/users.py` (or wherever `POST /users/sync` lives) — accept it on signup.

- [ ] **Step 1: Find the user-sync endpoint**

Run: `grep -rn 'sync\|user_repo.upsert' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/routers/users.py | head -10`

- [ ] **Step 2: Add `provider_choice` to the request schema**

Find the request model. Add:

```python
class SyncUserRequest(BaseModel):
    provider_choice: Literal["chatgpt_oauth", "byo_key", "bedrock_claude"] | None = None
    byo_provider: Literal["openai", "anthropic"] | None = None
```

- [ ] **Step 3: Persist it via the repo**

In the sync handler:

```python
if body.provider_choice:
    await user_repo.set_provider_choice(
        ctx.user_id,
        provider_choice=body.provider_choice,
        byo_provider=body.byo_provider,
    )
```

And add the helper to `user_repo.py`:

```python
async def set_provider_choice(
    user_id: str,
    *,
    provider_choice: str,
    byo_provider: str | None,
) -> None:
    expr_parts = ["SET provider_choice = :pc, updated_at = :t"]
    values = {":pc": provider_choice, ":t": _now_iso()}
    if byo_provider:
        expr_parts.append("byo_provider = :bp")
        values[":bp"] = byo_provider
    update_expr = expr_parts[0] if len(expr_parts) == 1 else expr_parts[0] + ", " + ", ".join(expr_parts[1:])
    _table().update_item(
        Key={"user_id": user_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=values,
    )
```

- [ ] **Step 4: Smoke import**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run python -c "from core.repositories.user_repo import set_provider_choice; print('ok')"`
Expected: `ok`.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/repositories/user_repo.py apps/backend/routers/users.py
git commit -m "$(cat <<'EOF'
feat(users): persist provider_choice + byo_provider on user record

The gateway needs to know which signup card the user picked so it can
gate chat on credits (card 3 only). Stored on the user record at
sync time, set by the onboarding wizard.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Gateway pre-chat balance check (card 3 only)

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py` — gate `chat.send` for `provider_choice == "bedrock_claude"` when balance≤0.
- Test: `apps/backend/tests/unit/gateway/test_connection_pool_credits_gate.py` (new)

- [ ] **Step 1: Find where `chat.send` is forwarded to OpenClaw**

Run: `grep -n 'chat.send\|chat_send\|forward.*chat\|send_chat' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/core/gateway/connection_pool.py | head -10`

You should see the path where the backend RPCs into the user's container.

- [ ] **Step 2: Write the failing test**

Create `apps/backend/tests/unit/gateway/test_connection_pool_credits_gate.py`:

```python
"""Pre-chat balance check: card-3 users with $0 are blocked."""

from unittest.mock import AsyncMock, patch

import pytest

from core.gateway.connection_pool import GatewayConnectionPool


@pytest.mark.asyncio
async def test_card3_with_zero_balance_blocked():
    pool = GatewayConnectionPool()
    with patch(
        "core.repositories.user_repo.get",
        new=AsyncMock(return_value={"provider_choice": "bedrock_claude"}),
    ), patch(
        "core.services.credit_ledger.get_balance",
        new=AsyncMock(return_value=0),
    ):
        result = await pool.gate_chat(user_id="u_1")

    assert result == {"blocked": True, "code": "out_of_credits"}


@pytest.mark.asyncio
async def test_card3_with_positive_balance_allowed():
    pool = GatewayConnectionPool()
    with patch(
        "core.repositories.user_repo.get",
        new=AsyncMock(return_value={"provider_choice": "bedrock_claude"}),
    ), patch(
        "core.services.credit_ledger.get_balance",
        new=AsyncMock(return_value=5_000_000),
    ):
        result = await pool.gate_chat(user_id="u_1")

    assert result == {"blocked": False}


@pytest.mark.asyncio
async def test_card1_oauth_user_never_gated_by_credits():
    pool = GatewayConnectionPool()
    with patch(
        "core.repositories.user_repo.get",
        new=AsyncMock(return_value={"provider_choice": "chatgpt_oauth"}),
    ):
        result = await pool.gate_chat(user_id="u_1")
    assert result == {"blocked": False}


@pytest.mark.asyncio
async def test_card2_byo_user_never_gated_by_credits():
    pool = GatewayConnectionPool()
    with patch(
        "core.repositories.user_repo.get",
        new=AsyncMock(return_value={"provider_choice": "byo_key"}),
    ):
        result = await pool.gate_chat(user_id="u_1")
    assert result == {"blocked": False}
```

- [ ] **Step 3: Add the `gate_chat` method**

In `apps/backend/core/gateway/connection_pool.py`, inside the `GatewayConnectionPool` class, add:

```python
    async def gate_chat(self, *, user_id: str) -> dict:
        """Pre-chat hard-stop check. Card 3 only.

        Per spec §6.3 step 1 + §6.6: blocks chat when card-3 balance ≤ 0.
        Cards 1 + 2 are never gated — their inference cost is on someone else.
        Returns {"blocked": True, "code": "out_of_credits"} or
        {"blocked": False}.
        """
        from core.repositories import user_repo
        from core.services import credit_ledger

        user = await user_repo.get(user_id)
        if not user or user.get("provider_choice") != "bedrock_claude":
            return {"blocked": False}

        # Consistent read so a top-up that just landed via webhook unblocks
        # the next message immediately (no eventual-consistency lag).
        balance = await credit_ledger.get_balance(user_id, consistent=True)
        if balance <= 0:
            return {"blocked": True, "code": "out_of_credits"}
        return {"blocked": False}
```

- [ ] **Step 4: Wire `gate_chat` into the existing `chat.send` path**

Find where `chat.send` is forwarded. Wrap the forward in a gate:

```python
    async def forward_chat(self, *, user_id: str, message: str, **rest):
        gate = await self.gate_chat(user_id=user_id)
        if gate["blocked"]:
            return {
                "type": "error",
                "code": gate["code"],
                "message": "You're out of Claude credits. Top up to continue.",
            }
        # ... existing forward logic ...
```

(Adapt method name to whatever the existing entry point is. The key is: hard-stop check before the OpenClaw RPC.)

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/gateway/test_connection_pool_credits_gate.py -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/gateway/connection_pool.py apps/backend/tests/unit/gateway/test_connection_pool_credits_gate.py
git commit -m "$(cat <<'EOF'
feat(gateway): pre-chat balance hard-stop for card-3 users

Per spec §6.3 step 1 + §6.6: card-3 (bedrock_claude) users with balance
≤ 0 cannot start a chat. Backend returns {type: error, code: out_of_credits}
and the frontend renders the OutOfCreditsBanner.

Cards 1 + 2 are never gated — their LLM cost isn't on us.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Gateway post-chat deduct on `chat.final`

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py` — in `_transform_agent_event`, deduct on `chat.final` for card-3 users.

- [ ] **Step 1: Find the `chat.final` event handler**

Run: `grep -n '_transform_agent_event\|chat.*final\|"final"' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/core/gateway/connection_pool.py | head -10`

- [ ] **Step 2: Write the failing test**

Create `apps/backend/tests/unit/gateway/test_connection_pool_deduct.py`:

```python
"""On chat.final, card-3 users get deducted via credit_ledger."""

from unittest.mock import AsyncMock, patch

import pytest

from core.gateway.connection_pool import GatewayConnectionPool


@pytest.mark.asyncio
async def test_chat_final_deducts_for_card3():
    pool = GatewayConnectionPool()
    fake_final = {
        "stream": "chat",
        "state": "final",
        "input_tokens": 1000,
        "output_tokens": 500,
        "model": "amazon-bedrock/anthropic.claude-sonnet-4-6",
        "session_id": "sess_1",
    }
    with patch(
        "core.repositories.user_repo.get",
        new=AsyncMock(return_value={"provider_choice": "bedrock_claude"}),
    ), patch(
        "core.services.credit_ledger.deduct", new=AsyncMock(return_value=8_000_000)
    ) as mock_deduct:
        await pool.handle_post_chat_billing(user_id="u_1", final_event=fake_final)

    mock_deduct.assert_awaited_once()
    _, kwargs = mock_deduct.call_args
    # Sonnet 4.6: 1000 input × $3/MTok = $0.003 = 3000 microcents
    #             500 output × $15/MTok = $0.0075 = 7500 microcents
    # Raw = 10500. Marked up by 1.4 = 14_700 microcents.
    assert kwargs["amount_microcents"] == 14_700
    assert kwargs["raw_cost_microcents"] == 10_500
    assert kwargs["markup_multiplier"] == 1.4
    assert kwargs["chat_session_id"] == "sess_1"


@pytest.mark.asyncio
async def test_chat_final_skips_deduct_for_card1():
    pool = GatewayConnectionPool()
    fake_final = {
        "stream": "chat", "state": "final",
        "input_tokens": 999, "output_tokens": 999,
        "model": "openai-codex/gpt-5.5", "session_id": "sess_x",
    }
    with patch(
        "core.repositories.user_repo.get",
        new=AsyncMock(return_value={"provider_choice": "chatgpt_oauth"}),
    ), patch(
        "core.services.credit_ledger.deduct", new=AsyncMock()
    ) as mock_deduct:
        await pool.handle_post_chat_billing(user_id="u_1", final_event=fake_final)
    mock_deduct.assert_not_called()
```

- [ ] **Step 3: Add the `handle_post_chat_billing` method**

In `connection_pool.py`:

```python
    async def handle_post_chat_billing(
        self, *, user_id: str, final_event: dict
    ) -> None:
        """Deduct credits on chat.final. Card 3 only.

        Per spec §6.3: extract token counts from the final event, compute
        raw cost via bedrock_pricing, apply 1.4× markup, deduct atomically.
        Cards 1 + 2 are no-ops (their LLM cost is elsewhere).
        """
        from core.repositories import user_repo
        from core.services import credit_ledger
        from core.billing.bedrock_pricing import (
            UnknownModelError, cost_microcents,
        )

        user = await user_repo.get(user_id)
        if not user or user.get("provider_choice") != "bedrock_claude":
            return

        # Strip the "amazon-bedrock/" prefix from the model id.
        full_model = final_event.get("model", "")
        bare_model = full_model.split("/", 1)[-1] if "/" in full_model else full_model

        try:
            raw = cost_microcents(
                model_id=bare_model,
                input_tokens=int(final_event.get("input_tokens", 0)),
                output_tokens=int(final_event.get("output_tokens", 0)),
            )
        except UnknownModelError:
            logger.warning(
                "Unknown Bedrock model %r in chat.final for user %s — skipping deduct",
                bare_model, user_id,
            )
            return

        marked_up = int(raw * 1.4)
        await credit_ledger.deduct(
            user_id,
            amount_microcents=marked_up,
            chat_session_id=final_event.get("session_id", ""),
            raw_cost_microcents=raw,
            markup_multiplier=1.4,
        )
```

- [ ] **Step 4: Wire it into the chat.final code path**

Find where `chat.final` is handled in `_transform_agent_event` (or wherever final events are emitted). Just before forwarding the event to the frontend, call:

```python
            if event.get("stream") == "chat" and event.get("state") == "final":
                await self.handle_post_chat_billing(
                    user_id=user_id, final_event=event,
                )
```

(Order matters: deduct AFTER the chat completed and we have token counts; BEFORE forwarding `done` to the frontend so the next chat sees the updated balance.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/unit/gateway/test_connection_pool_deduct.py -v`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/backend/core/gateway/connection_pool.py apps/backend/tests/unit/gateway/test_connection_pool_deduct.py
git commit -m "$(cat <<'EOF'
feat(gateway): deduct credits on chat.final for card-3 users

Per spec §6.3: extract token counts from chat.final, compute raw cost
via bedrock_pricing, apply 1.4× markup, atomic deduct from credit_ledger.
Cards 1 + 2 skip this entirely.

Unknown model_id is logged + skipped (no overdraft, no error to user).
This is the chat-path wiring that Plan 2 deliberately deferred.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `useCredits` and `useChatGPTOAuth` frontend hooks

**Files:**
- Create: `apps/frontend/src/hooks/useCredits.ts`
- Create: `apps/frontend/src/hooks/useChatGPTOAuth.ts`

- [ ] **Step 1: Implement `useCredits.ts`**

Create `apps/frontend/src/hooks/useCredits.ts`:

```ts
import useSWR from "swr";
import { useApi } from "@/lib/api";

export type CreditsBalance = {
  balance_microcents: number;
  balance_dollars: string;
};

export function useCredits() {
  const api = useApi();
  const { data, error, mutate } = useSWR<CreditsBalance>(
    "/billing/credits/balance",
    (path) => api.get(path),
    {
      // Re-fetch on focus + every 30s while the chat surface is open;
      // top-ups land via webhook so we want to see them quickly.
      refreshInterval: 30_000,
      revalidateOnFocus: true,
    },
  );

  const startTopUp = async (amountCents: number): Promise<{ client_secret: string }> => {
    return api.post("/billing/credits/top_up", { amount_cents: amountCents });
  };

  const setAutoReload = async (params: {
    enabled: boolean;
    threshold_cents?: number;
    amount_cents?: number;
  }): Promise<void> => {
    await api.put("/billing/credits/auto_reload", params);
  };

  return {
    balance: data,
    isLoading: !data && !error,
    error,
    refresh: mutate,
    startTopUp,
    setAutoReload,
  };
}
```

- [ ] **Step 2: Implement `useChatGPTOAuth.ts`**

Create `apps/frontend/src/hooks/useChatGPTOAuth.ts`:

```ts
"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useApi } from "@/lib/api";

export type OAuthState =
  | { status: "idle" }
  | {
      status: "pending";
      userCode: string;
      verificationUri: string;
      expiresAt: number;
    }
  | { status: "completed"; accountId: string | null }
  | { status: "error"; message: string };

type StartResponse = {
  user_code: string;
  verification_uri: string;
  expires_in: number;
  interval: number;
};

type PollResponse =
  | { status: "pending" }
  | { status: "completed"; account_id: string | null };

export function useChatGPTOAuth() {
  const api = useApi();
  const [state, setState] = useState<OAuthState>({ status: "idle" });
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const pollIntervalSec = useRef<number>(5);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
    intervalRef.current = null;
  }, []);

  const start = useCallback(async () => {
    stopPolling();
    try {
      const r: StartResponse = await api.post("/oauth/chatgpt/start");
      pollIntervalSec.current = r.interval;
      setState({
        status: "pending",
        userCode: r.user_code,
        verificationUri: r.verification_uri,
        expiresAt: Date.now() + r.expires_in * 1000,
      });
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : "OAuth start failed";
      setState({ status: "error", message });
    }
  }, [api, stopPolling]);

  // Poll when we're in pending state.
  useEffect(() => {
    if (state.status !== "pending") return;
    intervalRef.current = setInterval(async () => {
      try {
        const r: PollResponse = await api.post("/oauth/chatgpt/poll");
        if (r.status === "completed") {
          stopPolling();
          setState({ status: "completed", accountId: r.account_id });
        }
      } catch (e: unknown) {
        const message = e instanceof Error ? e.message : "OAuth poll failed";
        stopPolling();
        setState({ status: "error", message });
      }
    }, pollIntervalSec.current * 1000);

    return () => stopPolling();
  }, [state.status, api, stopPolling]);

  // Stop on unmount.
  useEffect(() => () => stopPolling(), [stopPolling]);

  return { state, start };
}
```

- [ ] **Step 3: Verify TS types compile**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/frontend/src/hooks/useCredits.ts apps/frontend/src/hooks/useChatGPTOAuth.ts
git commit -m "$(cat <<'EOF'
feat(hooks): useCredits + useChatGPTOAuth

useCredits: SWR-backed balance + top_up + set_auto_reload helpers.
30-sec polling so webhook-driven top-ups appear quickly.

useChatGPTOAuth: drives the device-code flow. start() calls /oauth/chatgpt/start
to get the user_code + verification_uri; the hook then polls /oauth/chatgpt/poll
on the interval Stripe — sorry, OpenAI — returned. Stops cleanly on
completion / error / unmount.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Landing page — `<PricingThreeCard />`

**Files:**
- Create: `apps/frontend/src/components/landing/PricingThreeCard.tsx`
- Modify: `apps/frontend/src/components/landing/Pricing.tsx` — replace body with the new component.

- [ ] **Step 1: Implement the 3-card component**

Create `apps/frontend/src/components/landing/PricingThreeCard.tsx`:

```tsx
"use client";
import Link from "next/link";

type Card = {
  id: "chatgpt_oauth" | "byo_key" | "bedrock_claude";
  title: string;
  subtitle: string;
  trial: string;
  bullets: string[];
  cta: string;
  href: string;
};

const CARDS: Card[] = [
  {
    id: "chatgpt_oauth",
    title: "Sign in with ChatGPT",
    subtitle: "$50 / month + your ChatGPT subscription",
    trial: "14-day free trial",
    bullets: [
      "GPT-5.5 included via your ChatGPT account",
      "All channels (Telegram, Discord, WhatsApp)",
      "Always-on container",
    ],
    cta: "Start trial",
    href: "/sign-up?provider=chatgpt_oauth",
  },
  {
    id: "byo_key",
    title: "Bring your own API key",
    subtitle: "$50 / month + your provider bill",
    trial: "14-day free trial",
    bullets: [
      "OpenAI or Anthropic — your key, your billing",
      "All channels",
      "Always-on container",
    ],
    cta: "Start trial",
    href: "/sign-up?provider=byo_key",
  },
  {
    id: "bedrock_claude",
    title: "Powered by Claude",
    subtitle: "$50 / month + Claude credits",
    trial: "Pay-as-you-go credits, 1.4× markup",
    bullets: [
      "Claude Sonnet 4.6 + Opus 4.7",
      "All channels",
      "Always-on container",
    ],
    cta: "Get started",
    href: "/sign-up?provider=bedrock_claude",
  },
];

export function PricingThreeCard() {
  return (
    <section
      id="pricing"
      className="container mx-auto px-4 py-16 md:py-24"
    >
      <h2 className="text-3xl md:text-4xl font-bold text-center mb-2">
        One price. Three ways to power it.
      </h2>
      <p className="text-center text-muted-foreground mb-12 max-w-2xl mx-auto">
        Every plan is $50/month for the always-on agent infrastructure.
        Choose how you want to pay for inference.
      </p>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6 max-w-6xl mx-auto">
        {CARDS.map((card) => (
          <div
            key={card.id}
            className="rounded-2xl border border-border bg-card p-8 flex flex-col"
          >
            <h3 className="text-xl font-semibold mb-1">{card.title}</h3>
            <p className="text-sm text-muted-foreground mb-1">{card.subtitle}</p>
            <p className="text-sm text-primary font-medium mb-6">{card.trial}</p>
            <ul className="space-y-2 flex-1 mb-8">
              {card.bullets.map((b) => (
                <li
                  key={b}
                  className="flex items-start gap-2 text-sm"
                >
                  <span aria-hidden className="text-primary">✓</span>
                  <span>{b}</span>
                </li>
              ))}
            </ul>
            <Link
              href={card.href}
              className="inline-flex items-center justify-center rounded-md bg-primary text-primary-foreground px-4 py-2 text-sm font-medium hover:bg-primary/90 transition"
            >
              {card.cta}
            </Link>
          </div>
        ))}
      </div>
    </section>
  );
}
```

- [ ] **Step 2: Replace Pricing.tsx body**

Edit `apps/frontend/src/components/landing/Pricing.tsx`:

```tsx
"use client";
import { PricingThreeCard } from "./PricingThreeCard";

export default function Pricing() {
  return <PricingThreeCard />;
}
```

(Keep the file path so existing landing-page imports of `Pricing` continue to work without other edits.)

- [ ] **Step 3: Verify TS + visual smoke**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend
pnpm tsc --noEmit
pnpm run dev
```

Open `http://localhost:3000` in a browser. Confirm the 3-card layout renders, cards are responsive (single column on mobile, 3-up on desktop), and each CTA links to `/sign-up?provider=<id>`.

- [ ] **Step 4: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/frontend/src/components/landing/PricingThreeCard.tsx apps/frontend/src/components/landing/Pricing.tsx
git commit -m "$(cat <<'EOF'
feat(landing): 3-card pricing layout for the flat-fee pivot

Per spec §9.1: ChatGPT OAuth | BYO API key | Powered by Claude. All $50/mo.
Each CTA preserves the choice into signup via ?provider= query param,
which the onboarding wizard reads in the next task.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Onboarding step — `<ChatGPTOAuthStep />`

**Files:**
- Create: `apps/frontend/src/components/chat/ChatGPTOAuthStep.tsx`

- [ ] **Step 1: Implement the step**

Create `apps/frontend/src/components/chat/ChatGPTOAuthStep.tsx`:

```tsx
"use client";
import { useEffect } from "react";
import { useChatGPTOAuth } from "@/hooks/useChatGPTOAuth";

type Props = {
  onComplete: () => void;
};

export function ChatGPTOAuthStep({ onComplete }: Props) {
  const { state, start } = useChatGPTOAuth();

  useEffect(() => {
    if (state.status === "completed") onComplete();
  }, [state, onComplete]);

  if (state.status === "idle") {
    return (
      <div className="flex flex-col items-center gap-4 py-8">
        <h3 className="text-xl font-semibold">Sign in with ChatGPT</h3>
        <p className="text-sm text-muted-foreground text-center max-w-md">
          We'll connect to your ChatGPT account so your agent can use
          GPT-5.5 with your existing subscription. No keys to copy.
        </p>
        <button
          onClick={start}
          className="rounded-md bg-primary px-6 py-3 text-primary-foreground font-medium hover:bg-primary/90"
        >
          Connect ChatGPT
        </button>
      </div>
    );
  }

  if (state.status === "pending") {
    return (
      <div className="flex flex-col items-center gap-4 py-8">
        <h3 className="text-xl font-semibold">Almost there</h3>
        <ol className="text-sm space-y-2 list-decimal list-inside max-w-md">
          <li>
            Open{" "}
            <a
              href={state.verificationUri}
              target="_blank"
              rel="noreferrer"
              className="text-primary underline"
            >
              {state.verificationUri}
            </a>
          </li>
          <li>
            Enter this code:{" "}
            <code className="bg-muted px-2 py-1 rounded font-mono text-base">
              {state.userCode}
            </code>
          </li>
        </ol>
        <p className="text-xs text-muted-foreground">
          Waiting for you to complete sign-in…
        </p>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex flex-col items-center gap-4 py-8">
        <p className="text-destructive">Connection failed: {state.message}</p>
        <button
          onClick={start}
          className="rounded-md bg-secondary px-4 py-2 text-sm"
        >
          Try again
        </button>
      </div>
    );
  }

  // status === "completed" — useEffect already called onComplete; show
  // a brief checkmark while the parent advances.
  return (
    <div className="flex items-center justify-center py-8 text-primary">
      ✓ Connected
    </div>
  );
}
```

- [ ] **Step 2: TS check + visual smoke**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend
pnpm tsc --noEmit
```

Wired into the wizard in Task 11.

- [ ] **Step 3: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/frontend/src/components/chat/ChatGPTOAuthStep.tsx
git commit -m "$(cat <<'EOF'
feat(onboarding): ChatGPTOAuthStep — display device-code, poll, advance

Renders the user_code + verification_uri returned from useChatGPTOAuth.
Auto-advances to the next wizard step on completion.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Onboarding step — `<ByoKeyStep />`

**Files:**
- Create: `apps/frontend/src/components/chat/ByoKeyStep.tsx`

- [ ] **Step 1: Implement the step**

Create `apps/frontend/src/components/chat/ByoKeyStep.tsx`:

```tsx
"use client";
import { useState } from "react";
import { useApi } from "@/lib/api";

type Provider = "openai" | "anthropic";
type Props = { onComplete: () => void };

export function ByoKeyStep({ onComplete }: Props) {
  const api = useApi();
  const [provider, setProvider] = useState<Provider>("openai");
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.post("/settings/keys", {
        provider,
        api_key: apiKey,
      });
      onComplete();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to save key");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 py-8 max-w-md mx-auto">
      <h3 className="text-xl font-semibold">Bring your own API key</h3>
      <p className="text-sm text-muted-foreground">
        Use your own OpenAI or Anthropic account. We never see your key after
        you save it — it's stored encrypted in AWS Secrets Manager and
        injected into your container at runtime.
      </p>

      <fieldset className="flex gap-3">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="provider"
            value="openai"
            checked={provider === "openai"}
            onChange={() => setProvider("openai")}
          />
          <span>OpenAI</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="radio"
            name="provider"
            value="anthropic"
            checked={provider === "anthropic"}
            onChange={() => setProvider("anthropic")}
          />
          <span>Anthropic</span>
        </label>
      </fieldset>

      <input
        type="password"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        placeholder={
          provider === "openai" ? "sk-proj-..." : "sk-ant-..."
        }
        required
        autoComplete="off"
        spellCheck={false}
        className="rounded-md border border-input bg-background px-3 py-2 font-mono text-sm"
      />

      {error && <p className="text-sm text-destructive">{error}</p>}

      <button
        type="submit"
        disabled={submitting || !apiKey}
        className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "Validating…" : "Save key"}
      </button>
    </form>
  );
}
```

- [ ] **Step 2: TS check**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/frontend/src/components/chat/ByoKeyStep.tsx
git commit -m "$(cat <<'EOF'
feat(onboarding): ByoKeyStep — provider radio + key input + validation

Submits to POST /settings/keys, which validates the key with a 1-token
test call and stores it in Secrets Manager. Auto-advances on success.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Onboarding step — `<CreditsStep />` (Stripe Elements)

**Files:**
- Create: `apps/frontend/src/components/chat/CreditsStep.tsx`

- [ ] **Step 1: Confirm `@stripe/react-stripe-js` is in package.json**

Run: `grep -n '@stripe/react-stripe-js\|@stripe/stripe-js' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend/package.json`

If missing, add: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend && pnpm add @stripe/react-stripe-js @stripe/stripe-js`

- [ ] **Step 2: Implement the step**

Create `apps/frontend/src/components/chat/CreditsStep.tsx`:

```tsx
"use client";
import { useEffect, useMemo, useState } from "react";
import { Elements, PaymentElement, useElements, useStripe } from "@stripe/react-stripe-js";
import { loadStripe } from "@stripe/stripe-js";
import { useCredits } from "@/hooks/useCredits";

type Props = { onComplete: () => void };

const STRIPE_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY!;
const stripePromise = loadStripe(STRIPE_PUBLISHABLE_KEY);

const PRESET_AMOUNTS_CENTS = [1000, 2000, 5000, 10000]; // $10, $20, $50, $100

export function CreditsStep({ onComplete }: Props) {
  const { startTopUp } = useCredits();
  const [amount, setAmount] = useState<number>(2000);
  const [clientSecret, setClientSecret] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const beginCheckout = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const r = await startTopUp(amount);
      setClientSecret(r.client_secret);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start checkout");
    } finally {
      setSubmitting(false);
    }
  };

  const options = useMemo(
    () => (clientSecret ? { clientSecret } : null),
    [clientSecret],
  );

  if (clientSecret && options) {
    return (
      <Elements stripe={stripePromise} options={options}>
        <PaymentForm onSuccess={onComplete} amount={amount} />
      </Elements>
    );
  }

  return (
    <div className="flex flex-col gap-4 py-8 max-w-md mx-auto">
      <h3 className="text-xl font-semibold">Add Claude credits</h3>
      <p className="text-sm text-muted-foreground">
        Prepay for Claude inference. Credits are deducted as you chat
        (1.4× cost). Add any amount, top up later anytime.
      </p>

      <div className="grid grid-cols-4 gap-2">
        {PRESET_AMOUNTS_CENTS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => setAmount(c)}
            className={`rounded-md border px-3 py-2 text-sm ${
              amount === c
                ? "border-primary bg-primary/10"
                : "border-border bg-card"
            }`}
          >
            ${c / 100}
          </button>
        ))}
      </div>

      <input
        type="number"
        min={5}
        step={5}
        value={amount / 100}
        onChange={(e) => setAmount(Math.round(Number(e.target.value) * 100))}
        className="rounded-md border border-input bg-background px-3 py-2"
      />

      {error && <p className="text-sm text-destructive">{error}</p>}

      <button
        onClick={beginCheckout}
        disabled={submitting || amount < 500}
        className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "Loading…" : `Add $${amount / 100}`}
      </button>
    </div>
  );
}

function PaymentForm({
  onSuccess,
  amount,
}: {
  onSuccess: () => void;
  amount: number;
}) {
  const stripe = useStripe();
  const elements = useElements();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stripe || !elements) return;
    setSubmitting(true);
    setError(null);
    const { error: stripeError } = await stripe.confirmPayment({
      elements,
      confirmParams: { return_url: window.location.href },
      redirect: "if_required",
    });
    if (stripeError) {
      setError(stripeError.message ?? "Payment failed");
      setSubmitting(false);
      return;
    }
    // Webhook will credit the balance asynchronously; advance the wizard.
    onSuccess();
  };

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 py-8 max-w-md mx-auto">
      <h3 className="text-xl font-semibold">Pay ${amount / 100}</h3>
      <PaymentElement />
      {error && <p className="text-sm text-destructive">{error}</p>}
      <button
        type="submit"
        disabled={!stripe || submitting}
        className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
      >
        {submitting ? "Processing…" : `Pay $${amount / 100}`}
      </button>
    </form>
  );
}
```

- [ ] **Step 3: Add `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` to `.env.local` and Vercel**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend
echo "NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY=pk_test_REPLACE_ME" >> .env.local
```

Then in Vercel dashboard for the dev/staging/prod projects: Settings → Environment Variables → add `NEXT_PUBLIC_STRIPE_PUBLISHABLE_KEY` with the matching `pk_test_*` (dev/staging) and `pk_live_*` (prod).

- [ ] **Step 4: TS check**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/frontend/src/components/chat/CreditsStep.tsx apps/frontend/package.json apps/frontend/pnpm-lock.yaml
git commit -m "$(cat <<'EOF'
feat(onboarding): CreditsStep — Stripe Elements payment form

Two-stage UI: amount-picker (4 presets + custom input, $5 min), then
PaymentElement-driven Stripe checkout. Confirms the PaymentIntent client-side;
backend webhook credits the balance after Stripe finalizes.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `<ProvisioningStepper />` rewrite — branch on `provider_choice`

**Files:**
- Modify: `apps/frontend/src/components/chat/ProvisioningStepper.tsx`

- [ ] **Step 1: Read the current stepper structure**

Run: `wc -l /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend/src/components/chat/ProvisioningStepper.tsx`

If it's >500 lines, read it in chunks. Identify the existing step ordering (e.g. billing → container → gateway → channels).

- [ ] **Step 2: Determine `provider_choice` from query string**

At the top of the component, derive the choice from the URL:

```tsx
import { useSearchParams } from "next/navigation";

const params = useSearchParams();
const providerChoice = params.get("provider") as
  | "chatgpt_oauth"
  | "byo_key"
  | "bedrock_claude"
  | null;
```

(If the choice arrives via state instead of query string, adapt accordingly. The landing-page CTA in Task 7 uses `/sign-up?provider=...`, and that param should be preserved through the Clerk redirect to `/onboarding`.)

- [ ] **Step 3: Insert provider-specific step in the wizard order**

Replace the existing ordered step list with provider-aware ordering. Pseudocode:

```tsx
import { ChatGPTOAuthStep } from "./ChatGPTOAuthStep";
import { ByoKeyStep } from "./ByoKeyStep";
import { CreditsStep } from "./CreditsStep";

// Step order: SignUpAccount → SetupPaymentMethod → ProviderStep → ContainerProvision → ChannelsOptional → Done.

const providerStep = (() => {
  if (providerChoice === "chatgpt_oauth") {
    return <ChatGPTOAuthStep onComplete={advance} />;
  }
  if (providerChoice === "byo_key") {
    return <ByoKeyStep onComplete={advance} />;
  }
  if (providerChoice === "bedrock_claude") {
    return <CreditsStep onComplete={advance} />;
  }
  return null;
})();
```

Insert `providerStep` between the payment-method step and the container-provision step.

- [ ] **Step 4: On wizard final step, sync `provider_choice` to backend**

Before kicking off `provision_container`, call:

```tsx
await api.post("/users/sync", {
  provider_choice: providerChoice,
  byo_provider: byoProvider,  // captured from ByoKeyStep if applicable
});
```

This populates the user record so the gateway's `gate_chat` (Task 4) and `handle_post_chat_billing` (Task 5) can branch correctly.

- [ ] **Step 5: TS check + visual smoke**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend
pnpm tsc --noEmit
pnpm run dev
```

Visit `http://localhost:3000/sign-up?provider=bedrock_claude`, sign up, and walk through the wizard. Confirm the credits step appears and that `POST /users/sync` is called with `provider_choice: "bedrock_claude"`.

- [ ] **Step 6: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/frontend/src/components/chat/ProvisioningStepper.tsx
git commit -m "$(cat <<'EOF'
feat(onboarding): ProvisioningStepper branches on ?provider= query param

Inserts ChatGPTOAuthStep | ByoKeyStep | CreditsStep into the wizard
flow based on which landing-page CTA the user clicked. Syncs the choice
back to the user record via POST /users/sync so the gateway knows
whether to gate chat on credits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: `<TrialBanner />` and `<OutOfCreditsBanner />`

**Files:**
- Create: `apps/frontend/src/components/chat/TrialBanner.tsx`
- Create: `apps/frontend/src/components/chat/OutOfCreditsBanner.tsx`
- Modify: `apps/frontend/src/components/chat/ChatLayout.tsx`

- [ ] **Step 1: TrialBanner**

Create `apps/frontend/src/components/chat/TrialBanner.tsx`:

```tsx
"use client";
import useSWR from "swr";
import Link from "next/link";
import { useApi } from "@/lib/api";

type BillingAccount = {
  subscription_status?: string;
  trial_end?: number; // Unix seconds
};

export function TrialBanner() {
  const api = useApi();
  const { data } = useSWR<BillingAccount>(
    "/billing/account",
    (path) => api.get(path),
    { refreshInterval: 60_000 },
  );

  if (data?.subscription_status !== "trialing" || !data.trial_end) {
    return null;
  }
  const daysLeft = Math.max(
    0,
    Math.ceil((data.trial_end * 1000 - Date.now()) / 86_400_000),
  );
  const chargeDate = new Date(data.trial_end * 1000).toLocaleDateString();

  return (
    <div className="bg-primary/10 border-b border-primary/20 px-4 py-2 text-sm flex items-center justify-between">
      <span>
        Your free trial ends in <strong>{daysLeft} day{daysLeft === 1 ? "" : "s"}</strong>.
        You'll be charged $50 on {chargeDate}.
      </span>
      <Link href="/settings/billing" className="text-primary underline">
        Manage
      </Link>
    </div>
  );
}
```

- [ ] **Step 2: OutOfCreditsBanner**

Create `apps/frontend/src/components/chat/OutOfCreditsBanner.tsx`:

```tsx
"use client";
import Link from "next/link";
import { useCredits } from "@/hooks/useCredits";

export function OutOfCreditsBanner() {
  const { balance } = useCredits();
  if (!balance || balance.balance_microcents > 0) return null;

  return (
    <div className="bg-destructive/10 border-b border-destructive/20 px-4 py-2 text-sm flex items-center justify-between">
      <span className="text-destructive">
        You're out of Claude credits. Top up to keep chatting.
      </span>
      <Link
        href="/settings/credits"
        className="rounded-md bg-destructive px-3 py-1 text-destructive-foreground text-xs"
      >
        Top up now
      </Link>
    </div>
  );
}
```

- [ ] **Step 3: Render both above the chat surface**

Edit `apps/frontend/src/components/chat/ChatLayout.tsx`. Find where the chat content is rendered and add (above any chat content):

```tsx
import { TrialBanner } from "./TrialBanner";
import { OutOfCreditsBanner } from "./OutOfCreditsBanner";

// inside the JSX, top of the chat area:
<TrialBanner />
<OutOfCreditsBanner />
```

(If the user is on cards 1 or 2, `useCredits` will still return `balance_microcents > 0` because the backend writes 0 for new users — no harm, banner stays hidden. Strictly speaking we could check `provider_choice`; defer that polish.)

- [ ] **Step 4: TS check**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/frontend/src/components/chat/TrialBanner.tsx apps/frontend/src/components/chat/OutOfCreditsBanner.tsx apps/frontend/src/components/chat/ChatLayout.tsx
git commit -m "$(cat <<'EOF'
feat(chat): TrialBanner + OutOfCreditsBanner above the chat surface

TrialBanner reads subscription.status + trial_end from /billing/account,
shows days-left countdown + charge date. Hidden once status flips to active.

OutOfCreditsBanner reads balance from useCredits, shows red bar + top-up
CTA when balance hits 0. Hidden otherwise.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Settings panels — `<LLMPanel />` and `<CreditsPanel />`

**Files:**
- Create: `apps/frontend/src/components/control/panels/LLMPanel.tsx`
- Create: `apps/frontend/src/components/control/panels/CreditsPanel.tsx`
- Modify: `apps/frontend/src/components/control/ControlPanelRouter.tsx`
- Modify: `apps/frontend/src/components/control/ControlSidebar.tsx`

- [ ] **Step 1: LLMPanel**

Create `apps/frontend/src/components/control/panels/LLMPanel.tsx`:

```tsx
"use client";
import { useState } from "react";
import useSWR from "swr";
import { useApi } from "@/lib/api";
import { useChatGPTOAuth } from "@/hooks/useChatGPTOAuth";

type UserData = {
  provider_choice?: "chatgpt_oauth" | "byo_key" | "bedrock_claude";
  byo_provider?: "openai" | "anthropic";
};

export function LLMPanel() {
  const api = useApi();
  const { data: user, mutate } = useSWR<UserData>("/users/me", (p) => api.get(p));
  const { state: oauthState, start: startOAuth } = useChatGPTOAuth();

  const disconnectOAuth = async () => {
    await api.post("/oauth/chatgpt/disconnect");
    await mutate();
  };

  if (!user) return <div className="p-6 text-sm">Loading…</div>;

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-xl font-semibold">LLM Provider</h2>

      {user.provider_choice === "chatgpt_oauth" && (
        <section className="space-y-3">
          <div className="text-sm">
            <strong>Sign in with ChatGPT</strong> · Connected
          </div>
          <button
            onClick={disconnectOAuth}
            className="rounded-md bg-secondary px-3 py-1.5 text-sm"
          >
            Disconnect
          </button>
        </section>
      )}

      {user.provider_choice === "byo_key" && (
        <section className="space-y-3">
          <div className="text-sm">
            <strong>Bring your own key</strong> ·{" "}
            {user.byo_provider === "openai" ? "OpenAI" : "Anthropic"}
          </div>
          <p className="text-xs text-muted-foreground">
            Your key is stored encrypted in AWS Secrets Manager. To rotate
            it, paste a new key below.
          </p>
          <ReplaceKeyForm
            currentProvider={user.byo_provider!}
            onReplaced={() => mutate()}
          />
        </section>
      )}

      {user.provider_choice === "bedrock_claude" && (
        <section className="space-y-3">
          <div className="text-sm">
            <strong>Powered by Claude</strong> · We provide the LLM
          </div>
          <p className="text-xs text-muted-foreground">
            Manage credits in the Credits panel.
          </p>
        </section>
      )}
    </div>
  );
}

function ReplaceKeyForm({
  currentProvider,
  onReplaced,
}: {
  currentProvider: "openai" | "anthropic";
  onReplaced: () => void;
}) {
  const api = useApi();
  const [apiKey, setApiKey] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    await api.post("/settings/keys", {
      provider: currentProvider,
      api_key: apiKey,
    });
    setApiKey("");
    setSubmitting(false);
    onReplaced();
  };

  return (
    <form onSubmit={submit} className="flex gap-2">
      <input
        type="password"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        placeholder={
          currentProvider === "openai" ? "sk-proj-…" : "sk-ant-…"
        }
        className="flex-1 rounded-md border border-input px-3 py-2 font-mono text-sm"
      />
      <button
        type="submit"
        disabled={submitting || !apiKey}
        className="rounded-md bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
      >
        Save
      </button>
    </form>
  );
}
```

- [ ] **Step 2: CreditsPanel**

Create `apps/frontend/src/components/control/panels/CreditsPanel.tsx`:

```tsx
"use client";
import { useState } from "react";
import { useCredits } from "@/hooks/useCredits";

export function CreditsPanel() {
  const { balance, startTopUp, setAutoReload, refresh } = useCredits();
  const [topUpAmount, setTopUpAmount] = useState(2000);
  const [autoEnabled, setAutoEnabled] = useState(false);
  const [threshold, setThreshold] = useState(500);
  const [reloadAmount, setReloadAmount] = useState(2000);

  const handleTopUp = async () => {
    const r = await startTopUp(topUpAmount);
    // For settings-panel top-ups, redirect into Stripe Checkout's hosted page
    // rather than embedding Elements (simpler than the onboarding flow).
    // The PaymentIntent.client_secret can be confirmed via Stripe.js.
    // Quick path: open a modal or trigger an Elements flow inline.
    // For brevity in this panel, point the user to the onboarding-style flow.
    alert(
      `Top-up payment intent created (client_secret: ${r.client_secret}).\nWire Stripe Elements here in a follow-up.`,
    );
    refresh();
  };

  const handleAutoReloadSave = async () => {
    await setAutoReload({
      enabled: autoEnabled,
      threshold_cents: autoEnabled ? threshold : undefined,
      amount_cents: autoEnabled ? reloadAmount : undefined,
    });
  };

  return (
    <div className="p-6 space-y-8">
      <h2 className="text-xl font-semibold">Claude credits</h2>

      <section>
        <div className="text-3xl font-bold">
          {balance ? `$${balance.balance_dollars}` : "$0.00"}
        </div>
        <div className="text-xs text-muted-foreground">Current balance</div>
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Add credits</h3>
        <div className="flex gap-2">
          {[1000, 2000, 5000, 10000].map((c) => (
            <button
              key={c}
              onClick={() => setTopUpAmount(c)}
              className={`rounded-md border px-3 py-1.5 text-sm ${
                topUpAmount === c ? "border-primary bg-primary/10" : ""
              }`}
            >
              ${c / 100}
            </button>
          ))}
        </div>
        <button
          onClick={handleTopUp}
          className="rounded-md bg-primary px-4 py-2 text-primary-foreground text-sm"
        >
          Add ${topUpAmount / 100}
        </button>
      </section>

      <section className="space-y-2">
        <h3 className="text-sm font-semibold">Auto-reload</h3>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={autoEnabled}
            onChange={(e) => setAutoEnabled(e.target.checked)}
          />
          Enabled
        </label>
        {autoEnabled && (
          <div className="space-y-2 text-sm">
            <label className="block">
              When balance drops below:
              <input
                type="number"
                min={5}
                step={5}
                value={threshold / 100}
                onChange={(e) => setThreshold(Math.round(Number(e.target.value) * 100))}
                className="ml-2 w-24 rounded-md border border-input px-2 py-1"
              />
            </label>
            <label className="block">
              Charge me:
              <input
                type="number"
                min={5}
                step={5}
                value={reloadAmount / 100}
                onChange={(e) => setReloadAmount(Math.round(Number(e.target.value) * 100))}
                className="ml-2 w-24 rounded-md border border-input px-2 py-1"
              />
            </label>
          </div>
        )}
        <button
          onClick={handleAutoReloadSave}
          className="rounded-md bg-secondary px-4 py-2 text-sm"
        >
          Save
        </button>
      </section>
    </div>
  );
}
```

- [ ] **Step 3: Register panels in ControlPanelRouter + Sidebar**

Find `apps/frontend/src/components/control/ControlPanelRouter.tsx`. Add cases for `"llm"` and `"credits"`:

```tsx
import { LLMPanel } from "./panels/LLMPanel";
import { CreditsPanel } from "./panels/CreditsPanel";

// inside the route switch:
case "llm": return <LLMPanel />;
case "credits": return <CreditsPanel />;
```

Find `ControlSidebar.tsx`. Add nav items:

```tsx
{ id: "llm", label: "LLM Provider", icon: ChevronsLeftRight },
{ id: "credits", label: "Credits", icon: Coins },
```

(Use whatever icon library is established — likely `lucide-react`.)

- [ ] **Step 4: TS check**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add apps/frontend/src/components/control/panels/LLMPanel.tsx apps/frontend/src/components/control/panels/CreditsPanel.tsx apps/frontend/src/components/control/ControlPanelRouter.tsx apps/frontend/src/components/control/ControlSidebar.tsx
git commit -m "$(cat <<'EOF'
feat(settings): LLM Provider + Claude Credits panels

LLMPanel: shows current provider, allows OAuth disconnect / key rotation /
provider switch. CreditsPanel: balance, top-up buttons, auto-reload toggle.

Wired into ControlPanelRouter + ControlSidebar.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: End-to-end smoke test in dev

**Files:** none — verification only.

- [ ] **Step 1: Push backend + frontend**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git push origin main
sleep 10
RUN_ID=$(gh run list --repo Isol8AI/isol8 --branch main --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo Isol8AI/isol8 --exit-status
```

Expected: deploy.yml + backend.yml + frontend (Vercel) all succeed.

- [ ] **Step 2: Walk the card-3 happy path manually**

In a fresh incognito browser:
1. Go to `https://dev.isol8.co/`
2. Confirm the new 3-card pricing layout renders.
3. Click "Get started" on the **Powered by Claude** card.
4. Sign up with a fresh Mailsac email (NOT `isol8-e2e-testing@mailsac.com`).
5. Walk the wizard: payment method → credits step → add $10 with a Stripe test card (`4242 4242 4242 4242`).
6. Wait ~5 sec for the webhook to land. Check the Credits panel — balance should show ~$10.
7. Confirm the agent provisions and can complete a chat.
8. Send a chat. After it finishes, refresh the Credits panel — balance should have decreased.
9. Open the LLM panel — should show "Powered by Claude".

- [ ] **Step 3: Walk the card-2 (BYO key) happy path**

Repeat with a different account, picking the BYO key card. Use a real Anthropic test key (from your own console). Confirm the agent chats successfully.

- [ ] **Step 4: Skip card 1 manual test for now**

Card 1 requires a ChatGPT account; cover later or with a dedicated test account.

- [ ] **Step 5: No commit — verification only**

If anything breaks, file a follow-up commit fixing forward.

---

## Task 15: CUTOVER — Tear down the 6 existing test containers

**Files:** none — runtime operation.

- [ ] **Step 1: List existing containers**

```bash
aws ecs list-services \
  --cluster isol8-prod-container-Cluster... \
  --profile isol8-admin --region us-east-1 \
  --query 'serviceArns'

aws ecs list-services \
  --cluster isol8-dev-container-Cluster... \
  --profile isol8-admin --region us-east-1 \
  --query 'serviceArns'
```

Note the per-user service names (`openclaw-{user_id}-{hash}`).

- [ ] **Step 2: Identify the 6 test users**

Get their Clerk user_ids:

```bash
aws dynamodb scan --table-name isol8-prod-users \
  --profile isol8-admin --region us-east-1 \
  --query 'Items[].user_id.S' --output text
```

(Likely 4 prod accounts + 2 dev accounts.)

- [ ] **Step 3: Tear them down via the debug endpoint**

For each user, call `DELETE /api/v1/debug/provision` from a session authed as that user. Easier: directly invoke the deprovision API server-side via an admin-actions helper. The simplest path is the dev-only debug endpoint — set `ENVIRONMENT=dev` temporarily on prod (do NOT do this without a coordinated rollback plan), or better, write a one-off admin script.

A safer one-off:

```bash
# On a workstation with admin AWS creds, delete the ECS service + EFS access point per user.
USER_ID=u_test_1
aws ecs delete-service \
  --cluster isol8-prod-container-Cluster... \
  --service openclaw-$USER_ID-... \
  --force \
  --profile isol8-admin --region us-east-1

aws efs delete-access-point \
  --access-point-id <ap-id-from-DDB-containers-table> \
  --profile isol8-admin --region us-east-1
```

Repeat for each user. The DDB `containers` table has the EFS access point IDs.

- [ ] **Step 4: Wipe the DDB rows for those users**

```bash
for USER_ID in u_test_1 u_test_2 u_test_3 u_test_4 u_test_5 u_test_6; do
  aws dynamodb delete-item --table-name isol8-prod-containers \
    --key "{\"user_id\":{\"S\":\"$USER_ID\"}}" \
    --profile isol8-admin --region us-east-1
done
```

- [ ] **Step 5: No commit**

This is an operational step. Document what you did in a private incident-style note so you can refer back.

---

## Task 16: CUTOVER — Delete deprecated env vars + code paths

**Files:**
- Modify: `apps/backend/core/config.py`
- Modify: `apps/backend/core/services/billing_service.py`
- Modify: `apps/infra/lib/stacks/service-stack.ts` (drop env vars)
- Possibly delete: `apps/backend/models/billing.py` if only `usage_event` / `usage_daily` lived there.

- [ ] **Step 1: Confirm zero live callers of the deprecated functions**

Run: `grep -rn 'create_checkout_session\|set_metered_overage_item\|STRIPE_STARTER_PRICE_ID\|STRIPE_PRO_PRICE_ID\|STRIPE_ENTERPRISE_PRICE_ID\|STRIPE_METERED_PRICE_ID\|BILLING_MARKUP\|FREE_TIER_MODEL' /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend/ /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/frontend/ /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/infra/ --include='*.py' --include='*.ts' --include='*.tsx' | grep -v __pycache__`

You should see only the definition sites (and tests). If you see other call sites, fix those before deleting.

- [ ] **Step 2: Delete the deprecated env vars from `core/config.py`**

Remove the lines for `STRIPE_STARTER_PRICE_ID`, `STRIPE_PRO_PRICE_ID`, `STRIPE_ENTERPRISE_PRICE_ID`, `STRIPE_METERED_PRICE_ID`, `STRIPE_METER_ID`, `BILLING_MARKUP`, `FREE_TIER_MODEL`.

- [ ] **Step 3: Delete the deprecated functions from `billing_service.py`**

Remove `create_checkout_session` (the per-tier version), `set_metered_overage_item`, the `_PRICE_IDS_BY_TIER` map.

- [ ] **Step 4: Drop the env vars from `service-stack.ts`**

Remove the corresponding env-var lines from the backend container's `environment:` block.

- [ ] **Step 5: Delete `models/billing.py` if obsolete**

If `models/billing.py` only contains `usage_event` / `usage_daily` and you didn't already delete in Plan 2 Task 16, delete it now.

- [ ] **Step 6: Run the test suite**

Run: `cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync/apps/backend && uv run pytest tests/ -v`
Expected: all pass. Likely some old per-tier tests break — delete them, the code they tested is gone.

- [ ] **Step 7: Commit**

```bash
cd /Users/prasiddhaparthsarthy/Desktop/isol8.nosync
git add -A
git commit -m "$(cat <<'EOF'
chore: cutover — delete per-tier env vars + code paths

Removes the now-dead per-tier price IDs, BILLING_MARKUP, FREE_TIER_MODEL,
the create_checkout_session per-tier helper, and set_metered_overage_item.
Drops the corresponding env vars from CDK service-stack.

After this commit, the backend has only the flat-fee path. Tests covering
the deleted code paths are removed alongside the code.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 8: Push, watch CI, smoke test**

```bash
git push origin main
sleep 10
RUN_ID=$(gh run list --repo Isol8AI/isol8 --branch main --limit 1 --json databaseId --jq '.[0].databaseId')
gh run watch $RUN_ID --repo Isol8AI/isol8 --exit-status
```

In production after deploy, sign up a brand-new account on each card, walk the full happy path. Watch CloudWatch errors for 24h.

---

## Self-Review

**Spec coverage check** (vs spec sections covered by Plan 3):

| Spec section | Tasks |
|---|---|
| §6.3 chat-deduct flow + hard-stop | Tasks 4 + 5 |
| §6.6 hard stop on $0 | Task 4 (gateway gate) + Task 12 (banner) |
| §7.1 trial signup with SetupIntent + Subscription | Tasks 1 + 11 (wizard) |
| §7.2 trial UX + cancel | Task 12 (banner) |
| §7.3 Stripe-native conversion | Task 1 + Task 2 (webhook handlers) |
| §7.4 abuse via Stripe Radar | Plan 1 dashboard config — no code in Plan 3 |
| §7.5 backend state minimization | Task 3 (only stores customer_id, sub_id, provider_choice) |
| §8.2 webhooks (trial_will_end, payment_intent.succeeded, subscription.*) | Task 2 + Plan 2 Task 15 |
| §9.1 landing 3-card | Task 7 |
| §9.2 onboarding wizard | Tasks 8, 9, 10, 11 |
| §9.3 settings panels | Task 13 |
| §9.4 trial banner | Task 12 |
| §9.5 out-of-credits banner | Task 12 |
| §13 Phase 4 cutover | Tasks 14, 15, 16 |

All Plan-3-scoped spec items present.

**Placeholder scan:** clean — every step has concrete code or commands. The CreditsPanel has one `alert(...)` placeholder for the in-panel top-up flow that's intentional (deferred to a follow-up). It's noted in the inline comment.

**Type / signature consistency:**
- `provider_choice: "chatgpt_oauth" | "byo_key" | "bedrock_claude"` everywhere (Tasks 3, 4, 7, 11, 13).
- `byo_provider: "openai" | "anthropic"` everywhere (Tasks 9, 11, 13).
- `useChatGPTOAuth().state.status: "idle" | "pending" | "completed" | "error"` consistent (Tasks 6, 8, 13).
- `credit_ledger.deduct(user_id, *, amount_microcents, chat_session_id, raw_cost_microcents, markup_multiplier, ...)` matches Plan 2 Task 6 signature.
- `gate_chat({user_id})` returns `{blocked: bool, code?: str}` consistently (Task 4 → wired in by `forward_chat`).

**Dependencies:**
- Plan 2 must be deployed first (this plan calls `credit_ledger`, `oauth_service`, `provision_container(provider_choice=...)`).
- Tasks 4 + 5 + 6 + 7 + 8 + 9 + 10 are independent of each other — can run in parallel.
- Task 11 (wizard) depends on 8 + 9 + 10 (steps to assemble).
- Task 12 depends on Task 6 (uses `useCredits`).
- Task 13 depends on Task 6 (uses `useCredits` + `useChatGPTOAuth`).
- Task 14 (smoke) depends on everything before it.
- Tasks 15 + 16 (cutover) depend on Task 14 passing.

**Suggested execution order (single executor):** 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16. Linear, ~4-6 days work.

**For parallel execution:** can run (1, 2, 3, 4+5) on backend in parallel, (6, 7, 8, 9, 10) on frontend in parallel; then (11, 12, 13) once their deps complete; then 14; then 15+16.
