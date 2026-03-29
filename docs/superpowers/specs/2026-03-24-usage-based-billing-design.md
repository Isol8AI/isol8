# Usage-Based Billing System Design

**Date**: 2026-03-24
**Status**: Draft
**Issues**: #44, #30

## Overview

Replace the current subscription-based billing model (Starter $25/mo, Pro $75/mo + metered LLM) with a pure usage-based model. Users get a free container on sign-up with a $2 spending cap and a single cheap model. After hitting the cap, they add a payment method via Stripe Checkout ($0/mo subscription) which unlocks all models and custom spend limits. Revenue comes from a 40% markup on Bedrock LLM costs.

## Business Model

- **Pricing**: Pure usage-based. No monthly fees. 40% markup (1.4x) on AWS Bedrock costs.
- **Free tier**: $2 lifetime spend cap (one-time, never resets), restricted to one cheap model (configurable via `FREE_TIER_MODEL` env var).
- **Paid tier**: $0/mo Stripe subscription (collects payment method). All models unlocked. User-configurable spend limit (default: unlimited).
- **Enforcement**: Hard stop when spend limit reached. Current request completes, next request rejected.

## User Flow

1. Sign up via Clerk → billing account auto-created (no Stripe customer yet)
2. Container auto-provisions immediately on first sign-in (`POST /users/sync`)
3. User chats with the free-tier model, up to $2 lifetime spend
4. At $2 → hard stop: "Add payment to continue"
5. User goes through Stripe Checkout → $0/mo subscription (payment method collected, metered price attached)
6. Limit unlocked → user can set custom spend limit via settings UI
7. Stripe invoices metered usage in arrears at end of billing cycle

## Architecture

### Pricing: `bedrock_pricing.py` (replaces `bedrock_discovery.py`)

Repurpose the existing `bedrock_discovery.py` file. Replace model discovery with pricing discovery.

- Call AWS Pricing API: `pricing.get_products(ServiceCode='AmazonBedrock', Filters=[regionCode, feature='On-demand Inference'])`
- Parse response to extract per-model token prices for: `input`, `output`, `cacheRead`, `cacheWrite`
- 24-hour in-memory cache (same pattern as old discovery service)
- Hardcoded fallback dict when API unavailable (local dev, errors)
- Expose: `get_model_price(model_id) -> {"input": float, "output": float, "cache_read": float, "cache_write": float}` (per-token, in dollars)
- Update `core/config.py` to import from `bedrock_pricing` instead of `bedrock_discovery`
- Update corresponding test file

### Usage Recording: `usage_service.py` (new)

**`record_usage(user_id, model, input_tokens, output_tokens, cache_read, cache_write)`**:

1. Look up model price via `bedrock_pricing` cache
2. Calculate raw cost: `(input * input_price) + (output * output_price) + (cache_read * cache_read_price) + (cache_write * cache_write_price)`
3. Calculate billable cost: `raw_cost * 1.4`
4. Convert to microdollars (int)
5. Two atomic DynamoDB `UpdateItem` with `ADD` — one for the monthly period (`"2026-03"`), one for `"lifetime"`. Both are no-read-before-write.
6. Stripe `MeterEvent.create()` with idempotency key (`{user_id}_{timestamp_ms}`) — reports billable microdollars
7. Called via fire-and-forget `asyncio.create_task` from `_fire_usage_callback`

**`check_spend_limit(user_id) -> {allowed, current_spend, limit, is_subscribed}`**:

1. Read billing account (spend limit, subscription status)
2. For **free users**: read lifetime usage counter (SK = `"lifetime"`) and compare against $2 cap
3. For **subscribed users**: read current monthly period counter (SK = `"2026-03"`) and compare against their custom spend limit (or skip if unlimited)
4. Return result — called before every chat request

**`get_usage_summary(user_id) -> {total_spend, total_input_tokens, total_output_tokens, request_count}`**:

1. Read current period usage counter
2. Return for frontend display

### Usage Repository: `usage_repo.py` (new)

DynamoDB operations for the `usage-counters` table:

- `increment(user_id, period, spend_microdollars, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)` — atomic `ADD`. Called twice per request: once for the monthly period (`"2026-03"`) and once for `"lifetime"`.
- `get_period_usage(user_id, period)` — single `GetItem`. Use `"lifetime"` for free tier checks, monthly key for paid user checks and usage display.

### Connection Pool Wiring

**`core/containers/__init__.py`** — Update `get_gateway_pool()` to pass an `on_usage` callback to `GatewayConnectionPool`. The callback imports and calls `usage_service.record_usage()`.

**`core/gateway/connection_pool.py`**:

- Update `UsageCallback` type alias to accept 6 params: `(user_id, model, input_tokens, output_tokens, cache_read, cache_write) -> Coroutine`
- Fix `_fire_usage_callback` to extract exact OpenClaw fields: `inputTokens`, `outputTokens`, `cacheRead`, `cacheWrite`, `model` — no field name guessing, no nested object fallbacks. Missing fields default to `0`.
- `_fire_usage_callback` calls `asyncio.create_task(self._on_usage(...))` — the task must catch and log all exceptions (unhandled task exceptions are silently swallowed in Python 3.12+)
- `record_usage()` itself is a normal async function (not fire-and-forget internally). The fire-and-forget happens in `_fire_usage_callback` via `create_task`.

### Pre-Chat Enforcement

In `routers/websocket_chat.py`, in the `agent_chat` handler, before forwarding to gateway:

1. **Spend limit**: Call `usage_service.check_spend_limit(user_id)`. If not allowed, reject with `{"type": "error", "code": "SPEND_LIMIT_REACHED"}`

Spend limit check is a single DynamoDB read — sub-millisecond latency.

### Model Restriction for Free Users

The `agent_chat` message only contains `agent_id` and `message` — the model is configured in `openclaw.json` on EFS per agent, not per request. Model restriction is enforced at the **config layer**, not per-chat:

1. When writing `openclaw.json` via `core/containers/config.py` (`write_openclaw_config()`), check if the user is subscribed.
2. **Free users**: Set the agent's model to `FREE_TIER_MODEL` regardless of what was requested. Only include the free model in the `models` list.
3. **Subscribed users**: Allow any model configured for the agent.
4. When a free user subscribes (webhook), rewrite `openclaw.json` to unlock all models.
5. Frontend `ModelSelector` shows only the free model for free users (other models grayed out with "Subscribe to unlock"). Model changes via the control panel also go through a backend endpoint that enforces the restriction before writing config.

### Edge Case: Mid-Conversation Overage

The pre-chat check is point-in-time. A user at $1.99 could have a response costing $0.10, pushing to $2.09. This is acceptable — the in-flight request completes, overage is recorded and billed, and the next request is blocked.

## DynamoDB Changes

### New Table: `usage-counters`

Add to `database-stack.ts`:

```
Table: isol8-{env}-usage-counters
PK: user_id (String)
SK: period (String, e.g. "2026-03")
Attributes:
  total_spend_microdollars: Number (atomic ADD)
  total_input_tokens: Number (atomic ADD)
  total_output_tokens: Number (atomic ADD)
  total_cache_read_tokens: Number (atomic ADD)
  total_cache_write_tokens: Number (atomic ADD)
  request_count: Number (atomic ADD)
```

No GSIs needed — only queried by `user_id + period`.

### Existing Table: `billing-accounts`

Add attribute: `spend_limit` (Number, microdollars. `null` = unlimited for subscribed users, `2_000_000` default for free users).

## Stripe Changes

### New Structure

- **One product**: "Isol8 Usage"
- **One metered price**: Per-unit, 1 unit = 1 microdollar of billable usage
- **One meter**: Event name `llm_usage`, value = billable microdollars per request
- **No fixed-price products or prices**

### Checkout Flow

- `create_checkout_session()` creates a $0/mo subscription with only the metered price line item
- No tier parameter — single plan
- Stripe collects payment method for future metered billing

### Webhook Changes

- `customer.subscription.created` → marks user as subscribed, unlocks models. Does NOT provision container (already exists).
- `customer.subscription.deleted` → reverts to free tier model + $2 limit. Does NOT stop container.
- `invoice.paid` / `invoice.payment_failed` → keep as-is (logging)

### Dev Stripe Cleanup

- Delete: Starter fixed price product/price (`price_1TBm0NI54BysGS3r57fcRXOJ`)
- Delete: Pro fixed price product/price (`price_1TBm0PI54BysGS3rFjUOtmrR`)
- Keep: Metered price (`price_1TBm0fI54BysGS3rrqTaZ5Zz`) — verify meter event name matches
- Keep: Meter (`mtr_test_61UL9xth9m1qTEaXv41I54BysGS3rJCC`)

### Prod Stripe Setup

- Create matching product, metered price, and meter
- Update CDK `service-stack.ts` placeholders with real IDs

## Backend File Changes

### Modified Files

| File | Changes |
|------|---------|
| `core/services/bedrock_discovery.py` | Rename to `bedrock_pricing.py`, rewrite: AWS Pricing API, 24h cache, fallback dict |
| `core/config.py` | Remove `PLAN_BUDGETS`, `FALLBACK_MODELS`, `get_available_models()`. Add `FREE_TIER_LIMIT_MICRODOLLARS`, `FREE_TIER_MODEL` env var. Import from `bedrock_pricing` |
| `core/services/billing_service.py` | Remove `PLAN_PRICES`, `METERED_PRICE_ID` module var. Simplify `create_checkout_session()` — no tier param, single metered price. Keep `create_customer_for_user()`, `create_portal_session()` |
| `core/repositories/billing_repo.py` | Add `spend_limit` field. Add `update_spend_limit()` method |
| `core/gateway/connection_pool.py` | Update `UsageCallback` type (add `cache_read`, `cache_write` params). Wire `on_usage` callback. Fix `_fire_usage_callback` to use exact OpenClaw fields. Add exception handling in `create_task`. Remove field name guessing |
| `core/containers/__init__.py` | Update `get_gateway_pool()` to pass `on_usage` callback to `GatewayConnectionPool` |
| `core/containers/config.py` | Enforce `FREE_TIER_MODEL` for unsubscribed users when writing `openclaw.json` |
| `routers/billing.py` | `GET /account` returns real spend. `GET /usage` returns from DynamoDB. Add `GET /pricing` endpoint. Add `PUT /spend-limit`. Remove tier from checkout. Update webhook handlers (no container provisioning/teardown) |
| `routers/websocket_chat.py` | Add pre-chat model restriction + spend limit check |
| `routers/users.py` | Trigger container provisioning on `POST /sync` if no container exists |
| `schemas/billing.py` | Remove tier from `CheckoutRequest`. Update `BillingAccountResponse` with `spend_limit`, `is_subscribed`, `current_spend`. Update `UsageResponse` with server-calculated costs |
| `apps/infra/lib/stacks/service-stack.ts` | Remove `STRIPE_STARTER_FIXED_PRICE_ID`, `STRIPE_PRO_FIXED_PRICE_ID`. Keep `STRIPE_METERED_PRICE_ID`, `STRIPE_METER_ID` |
| `apps/infra/lib/stacks/database-stack.ts` | Add `usage-counters` DynamoDB table |

### New Files

| File | Purpose |
|------|---------|
| `core/services/usage_service.py` | `record_usage()`, `check_spend_limit()`, `get_usage_summary()` |
| `core/repositories/usage_repo.py` | DynamoDB operations for `usage-counters` table |
| `tests/unit/services/test_usage_service.py` | Unit tests for usage service |
| `tests/unit/repositories/test_usage_repo.py` | Unit tests for usage repo |

### Deleted Code

| What | Where |
|------|-------|
| `bedrock_discovery.py` | Renamed to `bedrock_pricing.py` |
| `PLAN_BUDGETS` | `config.py` |
| `FALLBACK_MODELS` | `config.py` |
| `get_available_models()` | `config.py` |
| `PLAN_PRICES` dict | `billing_service.py` |
| Container provisioning in webhook | `routers/billing.py` |
| Container teardown in webhook | `routers/billing.py` |
| Field name guessing in `_fire_usage_callback` | `connection_pool.py` |

## Frontend File Changes

### Modified Files

| File | Changes |
|------|---------|
| `UsagePanel.tsx` | Remove all client-side cost calculation, hardcoded `MODEL_PRICING`, `MARKUP`, `getModelPricing()`, `useGatewayRpc("sessions.list")`. Fetch from `GET /billing/account` and `GET /billing/usage`. Add spend limit control (input + save). Budget bar shows spend vs. limit |
| `useBilling.ts` | Add `spendLimit`, `currentSpend` to account type. Add `updateSpendLimit()`. Add `fetchUsage()`. Remove tier-specific logic |
| `ProvisioningStepper.tsx` | Remove billing step. Add banner: "$2 free usage, add payment to unlock all models" |
| `ChatInput.tsx` / `AgentChatWindow.tsx` | Handle `SPEND_LIMIT_REACHED` and `MODEL_RESTRICTED` error codes. Disable input + show CTA when limit reached |
| `ModelSelector.tsx` | Free users: show only free-tier model, gray out others with "Subscribe to unlock" |
| `Sidebar.tsx` | Update if any tier references exist |

### Deleted Frontend Code

| What | Where |
|------|-------|
| `MODEL_PRICING` hardcoded dict | `UsagePanel.tsx` |
| `MARKUP` constant | `UsagePanel.tsx` |
| `getModelPricing()` function | `UsagePanel.tsx` |
| Client-side cost aggregation from `sessions.list` | `UsagePanel.tsx` |
| `useGatewayRpc("sessions.list")` dependency | `UsagePanel.tsx` |
| Tier-specific checkout logic | `useBilling.ts` |

## Token Coverage

OpenClaw's `chat` final payload includes these exact fields:

- `inputTokens` — prompt tokens
- `outputTokens` — completion tokens (includes reasoning tokens for models like DeepSeek R1)
- `cacheRead` — cached input tokens read
- `cacheWrite` — cached input tokens written
- `model` — Bedrock model ID

All four token types factor into cost calculation. The `_fire_usage_callback` will extract these fields directly — no field name guessing or nested object fallbacks.

## API Endpoints (New/Changed)

### `GET /billing/pricing`

Returns model pricing from `bedrock_pricing` cache. Response:

```json
{
  "models": {
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": {
      "input": 0.000003,
      "output": 0.000015,
      "cache_read": 0.0000003,
      "cache_write": 0.00000375,
      "name": "Claude Sonnet 4.5"
    }
  },
  "markup": 1.4,
  "free_tier_model": "us.amazon.nova-lite-v1:0"
}
```

Used by frontend `ModelSelector` (shows prices) and `UsagePanel` (shows cost breakdown).

## AWS Pricing API Notes

The AWS Pricing API (`pricing.get_products`) is slow (2-5s per call) and returns deeply nested JSON. Bedrock inference profile IDs (e.g., `us.anthropic.claude-*`) may not always be present. The **hardcoded fallback dict is essential** and should cover all models in our `openclaw.json` config. The API call is an enhancement for catching price changes, not the primary source.

## Known Limitations

- **TOCTOU on spend limits**: Two concurrent requests could both pass the spend check before either records usage. Acceptable for $2 free tier (overage is one request's cost). For paid users with tight limits, concurrent requests could slightly exceed the limit. Documented, not prevented.
- **Stripe MeterEvent rate limits**: 1000 events/second per meter. Fine at current scale. If we reach high concurrency, batch meter events.
- **Stripe MeterEvent idempotency**: Each `MeterEvent.create()` should include an idempotency key (e.g., `{user_id}_{timestamp_ms}`) to prevent duplicate billing on retries.
- **Idle containers for churned users**: When a subscriber cancels, their container keeps running (free tier with $2 cap). If they've already used $2, the container is idle. Future work: add a cleanup job to stop containers for users who have been at their limit for >30 days.

## Migration

No existing paying users — platform has not launched. Clean-slate implementation:
- Delete old Stripe products/prices in dev test mode
- Deploy new code
- Create new Stripe product + metered price
- No data migration needed

## Out of Scope

- Landing page pricing section update
- Tool-specific usage tracking (Perplexity search, etc.) — future work per #35, #41
- User API key usage attribution — future work per #41
- Usage history beyond current billing period
- Per-model spend breakdowns in the spend limit (limit is total, not per-model)
- Model discovery/listing — OpenClaw handles this via `bedrockDiscovery` in `openclaw.json`; `bedrock_pricing.py` only handles pricing, not model enumeration
