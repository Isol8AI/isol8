# Usage-Based Billing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace subscription-based billing with pure usage-based billing — free $2 cap, 40% markup on Bedrock LLM costs, Stripe metered billing.

**Architecture:** Backend-only metering via OpenClaw chat "final" events → `bedrock_pricing` for cost lookup → DynamoDB atomic counters for spend tracking → Stripe Meter for invoicing. Free users get one cheap model + $2 lifetime cap. Paid users get all models + custom spend limits.

**Tech Stack:** Python/FastAPI, DynamoDB (boto3/moto), Stripe API, AWS Pricing API, TypeScript/Next.js 16, CDK

**Spec:** `docs/superpowers/specs/2026-03-24-usage-based-billing-design.md`

**Testing approach:** Write tests first (TDD), but run the full test suite at the end of each task, not after every individual step. This saves time while still catching issues per task.

**Stripe CLI steps:** Tasks marked with 🔧 require manual Stripe CLI/dashboard operations. These are checkpoints where the orchestrator must pause between agent runs and perform the Stripe operations before continuing to the next task.

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `apps/backend/core/services/bedrock_pricing.py` | AWS Pricing API + fallback dict, 24h cache, `get_model_price()` |
| `apps/backend/core/repositories/usage_repo.py` | DynamoDB CRUD for `usage-counters` table |
| `apps/backend/core/services/usage_service.py` | `record_usage()`, `check_spend_limit()`, `get_usage_summary()` |
| `apps/backend/tests/unit/repositories/test_usage_repo.py` | Moto-based tests for usage repo |
| `apps/backend/tests/unit/services/test_usage_service.py` | Tests for usage service |
| `apps/backend/tests/unit/services/test_bedrock_pricing.py` | Tests for pricing service |

### Modified Files
| File | What Changes |
|------|-------------|
| `apps/backend/core/config.py` | Remove `PLAN_BUDGETS`, `FALLBACK_MODELS`, `get_available_models()`. Add `FREE_TIER_LIMIT_MICRODOLLARS`, `FREE_TIER_MODEL` |
| `apps/backend/schemas/billing.py` | Remove `PlanTier`, `CheckoutRequest.tier`. Update response schemas |
| `apps/backend/core/repositories/billing_repo.py` | Add `update_spend_limit()` |
| `apps/backend/core/services/billing_service.py` | Remove `PLAN_PRICES`. Simplify checkout to single metered price |
| `apps/backend/core/gateway/connection_pool.py` | Update `UsageCallback` type, fix `_fire_usage_callback`, add exception handling |
| `apps/backend/core/containers/__init__.py` | Pass `on_usage` callback to `GatewayConnectionPool` |
| `apps/backend/routers/billing.py` | Real usage data, pricing endpoint, spend limit, simplified webhooks |
| `apps/backend/routers/websocket_chat.py` | Pre-chat spend limit check |
| `apps/backend/routers/users.py` | Container auto-provisioning on sync |
| `apps/infra/lib/stacks/database-stack.ts` | Add `usage-counters` table |
| `apps/infra/lib/stacks/service-stack.ts` | Remove fixed price env vars |
| `apps/frontend/src/components/control/panels/UsagePanel.tsx` | Rewrite: REST-only, no client-side cost calc |
| `apps/frontend/src/hooks/useBilling.ts` | Add spend limit, usage, remove tiers |
| `apps/frontend/src/components/chat/AgentChatWindow.tsx` | Handle spend limit errors |
| `apps/frontend/src/components/chat/ProvisioningStepper.tsx` | Remove billing step |

### Deleted Files
| File | Reason |
|------|--------|
| `apps/backend/core/services/bedrock_discovery.py` | Replaced by `bedrock_pricing.py` |
| `apps/backend/tests/unit/core/test_config.py` | Tests for `discover_models` — rewrite for pricing |

---

## Task 1: Bedrock Pricing Service

Replace `bedrock_discovery.py` with `bedrock_pricing.py`. Hardcoded fallback dict is the primary source; AWS Pricing API is an enhancement.

**Files:**
- Delete: `apps/backend/core/services/bedrock_discovery.py`
- Create: `apps/backend/core/services/bedrock_pricing.py`
- Create: `apps/backend/tests/unit/services/test_bedrock_pricing.py`
- Modify: `apps/backend/core/config.py:6,96-133`

- [ ] **Step 1: Write the test file**

Create `apps/backend/tests/unit/services/test_bedrock_pricing.py`:

```python
"""Tests for Bedrock pricing service."""

import os
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from core.services.bedrock_pricing import (
    get_model_price,
    get_all_prices,
    FALLBACK_PRICING,
    _reset_cache_for_test,
)


class TestGetModelPrice:
    """Tests for get_model_price()."""

    def setup_method(self):
        _reset_cache_for_test()

    def test_exact_match_returns_pricing(self):
        price = get_model_price("us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        assert price is not None
        assert price["input"] == pytest.approx(3.0 / 1e6)
        assert price["output"] == pytest.approx(15.0 / 1e6)

    def test_unknown_model_returns_none(self):
        price = get_model_price("nonexistent-model-id")
        assert price is None

    def test_all_fallback_models_have_four_fields(self):
        for model_id, pricing in FALLBACK_PRICING.items():
            assert "input" in pricing, f"{model_id} missing input"
            assert "output" in pricing, f"{model_id} missing output"
            assert "cache_read" in pricing, f"{model_id} missing cache_read"
            assert "cache_write" in pricing, f"{model_id} missing cache_write"

    def test_get_all_prices_returns_dict(self):
        prices = get_all_prices()
        assert isinstance(prices, dict)
        assert len(prices) > 0


class TestPricingApiRefresh:
    """Tests for AWS Pricing API integration."""

    def setup_method(self):
        _reset_cache_for_test()

    @patch("core.services.bedrock_pricing.boto3.client")
    def test_api_failure_falls_back(self, mock_boto):
        mock_client = MagicMock()
        mock_client.get_products.side_effect = Exception("API unavailable")
        mock_boto.return_value = mock_client

        from core.services.bedrock_pricing import refresh_pricing_cache
        refresh_pricing_cache()

        # Should still have fallback pricing
        price = get_model_price("us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        assert price is not None
```

- [ ] **Step 2: Delete `bedrock_discovery.py` and create `bedrock_pricing.py`**

Delete `apps/backend/core/services/bedrock_discovery.py`.

Create `apps/backend/core/services/bedrock_pricing.py`:

```python
"""
Bedrock model pricing — hardcoded fallback + optional AWS Pricing API refresh.

The hardcoded FALLBACK_PRICING dict is the primary source of truth. It covers
all models in our openclaw.json config. The AWS Pricing API is called on startup
(and every 24h) to catch price changes, but failures are silently ignored.

Prices are per-token in USD.
"""

import logging
import time
from typing import TypedDict

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 86400  # 24 hours
_cached_pricing: dict[str, "ModelPrice"] = {}
_cache_expires_at: float = 0


class ModelPrice(TypedDict):
    input: float
    output: float
    cache_read: float
    cache_write: float


# Per-token USD pricing. Source: https://aws.amazon.com/bedrock/pricing/
# Last verified: 2026-03-24
FALLBACK_PRICING: dict[str, ModelPrice] = {
    # Claude Opus 4.6 / 4.5: $5/$25 per 1M tokens
    "us.anthropic.claude-opus-4-6-v1": {
        "input": 5.0 / 1e6, "output": 25.0 / 1e6,
        "cache_read": 0.5 / 1e6, "cache_write": 6.25 / 1e6,
    },
    "us.anthropic.claude-opus-4-5-20251101-v1:0": {
        "input": 5.0 / 1e6, "output": 25.0 / 1e6,
        "cache_read": 0.5 / 1e6, "cache_write": 6.25 / 1e6,
    },
    # Claude Sonnet 4.5: $3/$15 per 1M tokens
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": {
        "input": 3.0 / 1e6, "output": 15.0 / 1e6,
        "cache_read": 0.3 / 1e6, "cache_write": 3.75 / 1e6,
    },
    # Claude Haiku 4.5: $1/$5 per 1M tokens
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": {
        "input": 1.0 / 1e6, "output": 5.0 / 1e6,
        "cache_read": 0.1 / 1e6, "cache_write": 1.25 / 1e6,
    },
    # DeepSeek R1: $1.35/$5.40 per 1M tokens (cross-region)
    "us.deepseek.r1-v1:0": {
        "input": 1.35 / 1e6, "output": 5.40 / 1e6,
        "cache_read": 0.135 / 1e6, "cache_write": 1.35 / 1e6,
    },
    # Llama 3.3 70B: $0.72/$0.72 per 1M tokens (cross-region)
    "us.meta.llama3-3-70b-instruct-v1:0": {
        "input": 0.72 / 1e6, "output": 0.72 / 1e6,
        "cache_read": 0.0, "cache_write": 0.0,
    },
    # Amazon Nova Pro: $0.80/$3.20 per 1M tokens
    "us.amazon.nova-pro-v1:0": {
        "input": 0.80 / 1e6, "output": 3.20 / 1e6,
        "cache_read": 0.08 / 1e6, "cache_write": 0.80 / 1e6,
    },
    # Amazon Nova Lite: $0.06/$0.24 per 1M tokens
    "us.amazon.nova-lite-v1:0": {
        "input": 0.06 / 1e6, "output": 0.24 / 1e6,
        "cache_read": 0.006 / 1e6, "cache_write": 0.06 / 1e6,
    },
    # Mistral Large 3: $2/$6 per 1M tokens (cross-region)
    "us.mistral.mistral-large-2512-v1:0": {
        "input": 2.0 / 1e6, "output": 6.0 / 1e6,
        "cache_read": 0.2 / 1e6, "cache_write": 2.0 / 1e6,
    },
    # Qwen3 235B: $0.80/$2.00 per 1M tokens (cross-region, estimated)
    "us.qwen.qwen3-235b-a22b-2507-v1:0": {
        "input": 0.80 / 1e6, "output": 2.00 / 1e6,
        "cache_read": 0.0, "cache_write": 0.0,
    },
    # Qwen3 32B: $0.15/$0.60 per 1M tokens (cross-region, estimated)
    "us.qwen.qwen3-32b-v1:0": {
        "input": 0.15 / 1e6, "output": 0.60 / 1e6,
        "cache_read": 0.0, "cache_write": 0.0,
    },
}


def _reset_cache_for_test() -> None:
    global _cached_pricing, _cache_expires_at
    _cached_pricing = {}
    _cache_expires_at = 0


def refresh_pricing_cache(region: str = "us-east-1") -> None:
    """Attempt to refresh pricing from AWS Pricing API. Non-fatal on failure."""
    global _cached_pricing, _cache_expires_at
    try:
        client = boto3.client("pricing", region_name="us-east-1")
        paginator = client.get_paginator("get_products")
        import json as json_mod

        updated: dict[str, ModelPrice] = dict(FALLBACK_PRICING)

        for page in paginator.paginate(
            ServiceCode="AmazonBedrock",
            Filters=[
                {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
            ],
        ):
            for price_str in page.get("PriceList", []):
                try:
                    price_item = json_mod.loads(price_str)
                    _parse_price_item(price_item, updated)
                except Exception:
                    continue

        _cached_pricing = updated
        _cache_expires_at = time.time() + _CACHE_TTL_SECONDS
        logger.info("Refreshed Bedrock pricing cache: %d models", len(updated))

    except (ClientError, Exception) as e:
        logger.warning("Failed to refresh Bedrock pricing (using fallback): %s", e)
        if not _cached_pricing:
            _cached_pricing = dict(FALLBACK_PRICING)
            _cache_expires_at = time.time() + _CACHE_TTL_SECONDS


def _parse_price_item(price_item: dict, updated: dict[str, ModelPrice]) -> None:
    """Parse a single AWS Pricing API response item. Best-effort."""
    # AWS Pricing API response structure is deeply nested and varies.
    # This is best-effort extraction — fallback dict handles anything we miss.
    pass  # TODO: implement when we have sample API responses to test against


def get_model_price(model_id: str) -> ModelPrice | None:
    """Get per-token pricing for a model. Returns None if unknown."""
    if not _cached_pricing:
        # First call — initialize from fallback
        global _cache_expires_at
        _cached_pricing.update(FALLBACK_PRICING)
        _cache_expires_at = time.time() + _CACHE_TTL_SECONDS

    return _cached_pricing.get(model_id)


def get_all_prices() -> dict[str, ModelPrice]:
    """Get all cached model prices."""
    if not _cached_pricing:
        get_model_price("")  # trigger init
    return dict(_cached_pricing)
```

- [ ] **Step 3: Update `config.py` — remove discovery, add billing config**

In `apps/backend/core/config.py`:

Remove line 6 (`from core.services.bedrock_discovery import discover_models`).
Remove lines 96-133 (`PLAN_BUDGETS`, `FALLBACK_MODELS`, `get_available_models()`).

Add after `settings = Settings()`:

```python
# Free tier: $2 lifetime cap in microdollars (1 microdollar = $0.000001)
FREE_TIER_LIMIT_MICRODOLLARS = 2_000_000  # $2
```

Add to `Settings` class:

```python
FREE_TIER_MODEL: str = os.getenv("FREE_TIER_MODEL", "us.amazon.nova-lite-v1:0")
```

- [ ] **Step 4: Delete old test file**

Delete `apps/backend/tests/unit/core/test_config.py` (tests `discover_models` which no longer exists).

- [ ] **Step 5: Run tests**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_bedrock_pricing.py tests/ -v --timeout=30`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add -A apps/backend/core/services/bedrock_pricing.py apps/backend/tests/unit/services/test_bedrock_pricing.py apps/backend/core/config.py
git rm apps/backend/core/services/bedrock_discovery.py apps/backend/tests/unit/core/test_config.py
git commit -m "feat: replace bedrock_discovery with bedrock_pricing service"
```

---

## Task 2: Usage Counter Repository (DynamoDB)

Create the `usage_repo.py` for atomic counter operations on the `usage-counters` table.

**Files:**
- Create: `apps/backend/core/repositories/usage_repo.py`
- Create: `apps/backend/tests/unit/repositories/test_usage_repo.py`

- [ ] **Step 1: Write the test file**

Create `apps/backend/tests/unit/repositories/test_usage_repo.py`:

```python
"""Tests for usage counter DynamoDB repository."""

import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def dynamodb_table():
    """Create a moto DynamoDB usage-counters table."""
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")
        table = client.create_table(
            TableName="test-usage-counters",
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "period", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "period", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.meta.client.get_waiter("table_exists").wait(TableName="test-usage-counters")

        with (
            patch("core.dynamodb._table_prefix", "test-"),
            patch("core.dynamodb._dynamodb_resource", client),
        ):
            yield table


@pytest.mark.asyncio
async def test_increment_creates_item(dynamodb_table):
    from core.repositories import usage_repo

    await usage_repo.increment(
        user_id="user_1",
        period="2026-03",
        spend_microdollars=100_000,
        input_tokens=500,
        output_tokens=200,
        cache_read_tokens=50,
        cache_write_tokens=10,
    )

    result = await usage_repo.get_period_usage("user_1", "2026-03")
    assert result is not None
    assert result["total_spend_microdollars"] == 100_000
    assert result["total_input_tokens"] == 500
    assert result["total_output_tokens"] == 200
    assert result["request_count"] == 1


@pytest.mark.asyncio
async def test_increment_adds_atomically(dynamodb_table):
    from core.repositories import usage_repo

    await usage_repo.increment("user_1", "2026-03", 100_000, 500, 200, 0, 0)
    await usage_repo.increment("user_1", "2026-03", 50_000, 300, 100, 0, 0)

    result = await usage_repo.get_period_usage("user_1", "2026-03")
    assert result["total_spend_microdollars"] == 150_000
    assert result["total_input_tokens"] == 800
    assert result["request_count"] == 2


@pytest.mark.asyncio
async def test_get_nonexistent_returns_none(dynamodb_table):
    from core.repositories import usage_repo

    result = await usage_repo.get_period_usage("user_1", "2026-03")
    assert result is None


@pytest.mark.asyncio
async def test_different_periods_are_independent(dynamodb_table):
    from core.repositories import usage_repo

    await usage_repo.increment("user_1", "2026-03", 100_000, 500, 200, 0, 0)
    await usage_repo.increment("user_1", "lifetime", 100_000, 500, 200, 0, 0)

    march = await usage_repo.get_period_usage("user_1", "2026-03")
    lifetime = await usage_repo.get_period_usage("user_1", "lifetime")
    assert march["total_spend_microdollars"] == 100_000
    assert lifetime["total_spend_microdollars"] == 100_000
```

- [ ] **Step 2: Write `usage_repo.py`**

Create `apps/backend/core/repositories/usage_repo.py`:

```python
"""Usage counter repository -- DynamoDB atomic counters for the usage-counters table."""

from decimal import Decimal

from core.dynamodb import get_table, run_in_thread


def _get_table():
    return get_table("usage-counters")


async def increment(
    user_id: str,
    period: str,
    spend_microdollars: int,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> None:
    """Atomically increment all counters for a user+period. No read-before-write."""
    table = _get_table()
    await run_in_thread(
        table.update_item,
        Key={"user_id": user_id, "period": period},
        UpdateExpression=(
            "ADD total_spend_microdollars :spend, "
            "total_input_tokens :inp, "
            "total_output_tokens :out, "
            "total_cache_read_tokens :cr, "
            "total_cache_write_tokens :cw, "
            "request_count :one"
        ),
        ExpressionAttributeValues={
            ":spend": Decimal(str(spend_microdollars)),
            ":inp": Decimal(str(input_tokens)),
            ":out": Decimal(str(output_tokens)),
            ":cr": Decimal(str(cache_read_tokens)),
            ":cw": Decimal(str(cache_write_tokens)),
            ":one": Decimal("1"),
        },
    )


async def get_period_usage(user_id: str, period: str) -> dict | None:
    """Get usage counters for a user+period. Returns None if no usage recorded."""
    table = _get_table()
    response = await run_in_thread(
        table.get_item,
        Key={"user_id": user_id, "period": period},
    )
    item = response.get("Item")
    if item is None:
        return None
    # Convert Decimals to int for clean API responses
    return {
        "total_spend_microdollars": int(item.get("total_spend_microdollars", 0)),
        "total_input_tokens": int(item.get("total_input_tokens", 0)),
        "total_output_tokens": int(item.get("total_output_tokens", 0)),
        "total_cache_read_tokens": int(item.get("total_cache_read_tokens", 0)),
        "total_cache_write_tokens": int(item.get("total_cache_write_tokens", 0)),
        "request_count": int(item.get("request_count", 0)),
    }
```

- [ ] **Step 3: Run tests**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_usage_repo.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/repositories/usage_repo.py apps/backend/tests/unit/repositories/test_usage_repo.py
git commit -m "feat: add usage counter DynamoDB repository with atomic increments"
```

---

## Task 3: Usage Service

Core business logic: `record_usage()`, `check_spend_limit()`, `get_usage_summary()`.

**Files:**
- Create: `apps/backend/core/services/usage_service.py`
- Create: `apps/backend/tests/unit/services/test_usage_service.py`

- [ ] **Step 1: Write the test file**

Create `apps/backend/tests/unit/services/test_usage_service.py`:

```python
"""Tests for usage service."""

import os
from decimal import Decimal
from unittest.mock import patch, AsyncMock, MagicMock

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def dynamodb_tables():
    """Create moto DynamoDB tables for usage-counters and billing-accounts."""
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")

        # Usage counters table
        client.create_table(
            TableName="test-usage-counters",
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "period", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "period", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Billing accounts table
        client.create_table(
            TableName="test-billing-accounts",
            KeySchema=[{"AttributeName": "clerk_user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "clerk_user_id", "AttributeType": "S"},
                {"AttributeName": "stripe_customer_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "stripe-customer-index",
                    "KeySchema": [{"AttributeName": "stripe_customer_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        with (
            patch("core.dynamodb._table_prefix", "test-"),
            patch("core.dynamodb._dynamodb_resource", client),
        ):
            yield client


@pytest.fixture
def mock_stripe():
    with patch("core.services.usage_service.stripe") as mock:
        yield mock


@pytest.mark.asyncio
async def test_record_usage_increments_counters(dynamodb_tables, mock_stripe):
    from core.repositories import billing_repo
    from core.services.usage_service import record_usage

    await billing_repo.create("user_1", "cus_abc")

    await record_usage(
        user_id="user_1",
        model="us.anthropic.claude-sonnet-4-5-20250929-v1:0",
        input_tokens=1000,
        output_tokens=500,
        cache_read=0,
        cache_write=0,
    )

    from core.repositories import usage_repo
    lifetime = await usage_repo.get_period_usage("user_1", "lifetime")
    assert lifetime is not None
    assert lifetime["total_spend_microdollars"] > 0
    assert lifetime["request_count"] == 1


@pytest.mark.asyncio
async def test_record_usage_reports_to_stripe(dynamodb_tables, mock_stripe):
    from core.repositories import billing_repo
    from core.services.usage_service import record_usage

    await billing_repo.create("user_1", "cus_abc")

    await record_usage("user_1", "us.anthropic.claude-sonnet-4-5-20250929-v1:0", 1000, 500, 0, 0)

    mock_stripe.billing.MeterEvent.create.assert_called_once()


@pytest.mark.asyncio
async def test_check_spend_limit_free_user_under_limit(dynamodb_tables):
    from core.repositories import billing_repo
    from core.services.usage_service import check_spend_limit

    await billing_repo.create("user_1", "cus_abc")

    result = await check_spend_limit("user_1")
    assert result["allowed"] is True
    assert result["is_subscribed"] is False


@pytest.mark.asyncio
async def test_check_spend_limit_free_user_over_limit(dynamodb_tables):
    from core.repositories import billing_repo, usage_repo
    from core.services.usage_service import check_spend_limit

    await billing_repo.create("user_1", "cus_abc")
    # Simulate $3 of lifetime usage (over $2 cap)
    await usage_repo.increment("user_1", "lifetime", 3_000_000, 0, 0, 0, 0)

    result = await check_spend_limit("user_1")
    assert result["allowed"] is False


@pytest.mark.asyncio
async def test_check_spend_limit_subscribed_user_no_limit(dynamodb_tables):
    from core.repositories import billing_repo
    from core.services.usage_service import check_spend_limit

    await billing_repo.create("user_1", "cus_abc")
    await billing_repo.update_subscription("user_1", "sub_123", "paid")

    result = await check_spend_limit("user_1")
    assert result["allowed"] is True
    assert result["is_subscribed"] is True


@pytest.mark.asyncio
async def test_check_spend_limit_subscribed_user_over_custom_limit(dynamodb_tables):
    from core.repositories import billing_repo, usage_repo
    from core.services.usage_service import check_spend_limit

    await billing_repo.create("user_1", "cus_abc")
    await billing_repo.update_subscription("user_1", "sub_123", "paid")
    await billing_repo.update_spend_limit("user_1", 10_000_000)  # $10 limit

    # Simulate $12 of monthly usage (over $10 limit)
    from core.services.usage_service import _current_period
    await usage_repo.increment("user_1", _current_period(), 12_000_000, 0, 0, 0, 0)

    result = await check_spend_limit("user_1")
    assert result["allowed"] is False
    assert result["is_subscribed"] is True


@pytest.mark.asyncio
async def test_record_usage_unknown_model_skips(dynamodb_tables, mock_stripe):
    from core.repositories import billing_repo
    from core.services.usage_service import record_usage

    await billing_repo.create("user_1", "cus_abc")

    # Should not raise, just log warning
    await record_usage("user_1", "unknown-model", 1000, 500, 0, 0)
```

- [ ] **Step 2: Write `usage_service.py`**

Create `apps/backend/core/services/usage_service.py`:

```python
"""Usage tracking service — records LLM usage, checks spend limits, reports to Stripe."""

import logging
import time
from datetime import datetime, timezone

import stripe

from core.config import settings, FREE_TIER_LIMIT_MICRODOLLARS
from core.repositories import billing_repo, usage_repo
from core.services.bedrock_pricing import get_model_price

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY
_MARKUP = settings.BILLING_MARKUP


def _current_period() -> str:
    """Return current billing period key, e.g. '2026-03'."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def record_usage(
    user_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cache_write: int,
) -> None:
    """Record a single LLM usage event: price it, store counters, report to Stripe."""
    pricing = get_model_price(model)
    if pricing is None:
        logger.warning("No pricing for model %s — usage not recorded for user %s", model, user_id)
        return

    raw_cost = (
        input_tokens * pricing["input"]
        + output_tokens * pricing["output"]
        + cache_read * pricing["cache_read"]
        + cache_write * pricing["cache_write"]
    )
    billable_cost = raw_cost * _MARKUP
    spend_microdollars = int(billable_cost * 1_000_000)

    if spend_microdollars <= 0:
        return

    period = _current_period()

    # Dual-write: monthly period + lifetime
    await usage_repo.increment(
        user_id, period, spend_microdollars,
        input_tokens, output_tokens, cache_read, cache_write,
    )
    await usage_repo.increment(
        user_id, "lifetime", spend_microdollars,
        input_tokens, output_tokens, cache_read, cache_write,
    )

    # Report to Stripe Meter (non-fatal)
    try:
        account = await billing_repo.get_by_clerk_user_id(user_id)
        if account and account.get("stripe_customer_id") and settings.STRIPE_METER_ID:
            stripe.billing.MeterEvent.create(
                event_name="llm_usage",
                payload={
                    "stripe_customer_id": account["stripe_customer_id"],
                    "value": str(spend_microdollars),
                },
                identifier=f"{user_id}_{int(time.time() * 1000)}",
            )
    except Exception as e:
        logger.warning("Failed to report usage to Stripe for user %s: %s", user_id, e)


async def check_spend_limit(user_id: str) -> dict:
    """Check if user is within their spend limit.

    Returns: {allowed: bool, current_spend: float, limit: float, is_subscribed: bool}
    """
    account = await billing_repo.get_by_clerk_user_id(user_id)
    is_subscribed = bool(account and account.get("stripe_subscription_id"))

    if not is_subscribed:
        # Free user: check lifetime usage against $2 cap
        usage = await usage_repo.get_period_usage(user_id, "lifetime")
        current_spend = (usage["total_spend_microdollars"] if usage else 0) / 1_000_000
        limit = FREE_TIER_LIMIT_MICRODOLLARS / 1_000_000
        return {
            "allowed": current_spend < limit,
            "current_spend": current_spend,
            "limit": limit,
            "is_subscribed": False,
        }

    # Subscribed user: check monthly usage against custom limit (None = unlimited)
    spend_limit = account.get("spend_limit")  # microdollars or None
    period = _current_period()
    usage = await usage_repo.get_period_usage(user_id, period)
    current_spend = (usage["total_spend_microdollars"] if usage else 0) / 1_000_000

    if spend_limit is None:
        return {
            "allowed": True,
            "current_spend": current_spend,
            "limit": None,
            "is_subscribed": True,
        }

    limit_dollars = int(spend_limit) / 1_000_000
    return {
        "allowed": current_spend < limit_dollars,
        "current_spend": current_spend,
        "limit": limit_dollars,
        "is_subscribed": True,
    }


async def get_usage_summary(user_id: str) -> dict:
    """Get current period usage summary for display."""
    period = _current_period()
    usage = await usage_repo.get_period_usage(user_id, period)
    lifetime = await usage_repo.get_period_usage(user_id, "lifetime")

    if usage is None:
        usage = {
            "total_spend_microdollars": 0, "total_input_tokens": 0,
            "total_output_tokens": 0, "total_cache_read_tokens": 0,
            "total_cache_write_tokens": 0, "request_count": 0,
        }

    return {
        "period": period,
        "total_spend": usage["total_spend_microdollars"] / 1_000_000,
        "total_input_tokens": usage["total_input_tokens"],
        "total_output_tokens": usage["total_output_tokens"],
        "total_cache_read_tokens": usage["total_cache_read_tokens"],
        "total_cache_write_tokens": usage["total_cache_write_tokens"],
        "request_count": usage["request_count"],
        "lifetime_spend": (lifetime["total_spend_microdollars"] if lifetime else 0) / 1_000_000,
    }
```

- [ ] **Step 3: Run tests**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_usage_service.py -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/services/usage_service.py apps/backend/tests/unit/services/test_usage_service.py
git commit -m "feat: add usage service with record_usage, check_spend_limit, Stripe metering"
```

---

## Task 4: Connection Pool Wiring

Wire the usage callback into the gateway connection pool.

**Files:**
- Modify: `apps/backend/core/gateway/connection_pool.py:28-33,227-272`
- Modify: `apps/backend/core/containers/__init__.py:33-40`

- [ ] **Step 1: Update `UsageCallback` type and fix `_fire_usage_callback`**

In `apps/backend/core/gateway/connection_pool.py`:

Replace lines 31-33 (type alias):
```python
    # Type alias for the usage callback:
    # (user_id, model, input_tokens, output_tokens, cache_read, cache_write) -> Coroutine
    UsageCallback = Callable[[str, str, int, int, int, int], Coroutine[Any, Any, None]]
```

Replace lines 227-272 (`_fire_usage_callback` method):
```python
    def _fire_usage_callback(self, payload: dict) -> None:
        """Extract token usage from a chat final payload and fire the callback."""
        if not self._on_usage:
            return

        input_tokens = int(payload.get("inputTokens", 0) or 0)
        output_tokens = int(payload.get("outputTokens", 0) or 0)
        cache_read = int(payload.get("cacheRead", 0) or 0)
        cache_write = int(payload.get("cacheWrite", 0) or 0)
        model = payload.get("model") or "unknown"

        if input_tokens == 0 and output_tokens == 0:
            logger.debug("No token usage in chat final for user %s", self.user_id)
            return

        async def _safe_record():
            try:
                await self._on_usage(
                    self.user_id, model, input_tokens, output_tokens, cache_read, cache_write
                )
            except Exception:
                logger.exception("Usage recording failed for user %s", self.user_id)

        asyncio.create_task(_safe_record())
        logger.info(
            "Usage recording scheduled: user=%s model=%s in=%d out=%d cr=%d cw=%d",
            self.user_id, model, input_tokens, output_tokens, cache_read, cache_write,
        )
```

- [ ] **Step 2: Wire callback in `__init__.py`**

In `apps/backend/core/containers/__init__.py`, replace `get_gateway_pool()`:

```python
def get_gateway_pool() -> GatewayConnectionPool:
    """Get the gateway connection pool singleton (GatewayConnectionPool)."""
    global _gateway_pool
    if _gateway_pool is None:
        from core.services.usage_service import record_usage

        _gateway_pool = GatewayConnectionPool(
            management_api=ManagementApiClient(),
            on_usage=record_usage,
        )
    return _gateway_pool
```

Also check that `GatewayConnectionPool.__init__` accepts and passes `on_usage` to `GatewayConnection`. Read `connection_pool.py` lines 385+ (the pool class) to verify — the pool must store `on_usage` and pass it when creating `GatewayConnection` instances.

- [ ] **Step 3: Run existing tests**

Run: `cd apps/backend && uv run pytest tests/ -v --timeout=30`
Expected: All existing tests pass (no regressions)

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/gateway/connection_pool.py apps/backend/core/containers/__init__.py
git commit -m "feat: wire usage callback into gateway connection pool"
```

---

## Task 5: Billing Schemas & Repo Updates

Update Pydantic schemas and billing repo for the new model.

**Files:**
- Modify: `apps/backend/schemas/billing.py`
- Modify: `apps/backend/core/repositories/billing_repo.py`

- [ ] **Step 1: Rewrite `schemas/billing.py`**

Replace entire file:

```python
"""Pydantic schemas for billing API endpoints."""

from datetime import date
from pydantic import BaseModel


class UsagePeriod(BaseModel):
    start: date
    end: date
    spend_limit: float | None  # None = unlimited
    current_spend: float


class BillingAccountResponse(BaseModel):
    is_subscribed: bool
    current_period: UsagePeriod
    lifetime_spend: float
    spend_limit: float | None  # user's custom limit (None = unlimited for subscribed)


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class SpendLimitRequest(BaseModel):
    limit_dollars: float | None  # None = unlimited


class UsageSummary(BaseModel):
    period: str
    total_spend: float
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_write_tokens: int
    request_count: int
    lifetime_spend: float


class ModelPriceResponse(BaseModel):
    input: float
    output: float
    cache_read: float
    cache_write: float


class PricingResponse(BaseModel):
    models: dict[str, ModelPriceResponse]
    markup: float
    free_tier_model: str
```

- [ ] **Step 2: Add `update_spend_limit` to `billing_repo.py`**

Append to `apps/backend/core/repositories/billing_repo.py`:

```python
async def update_spend_limit(clerk_user_id: str, spend_limit: int | None) -> dict | None:
    """Update a user's custom spend limit. None = unlimited."""
    existing = await get_by_clerk_user_id(clerk_user_id)
    if existing is None:
        return None

    if spend_limit is not None:
        existing["spend_limit"] = Decimal(str(spend_limit))
    else:
        existing.pop("spend_limit", None)
    existing["updated_at"] = utc_now_iso()

    table = _get_table()
    await run_in_thread(table.put_item, Item=existing)
    return existing
```

- [ ] **Step 3: Run existing billing repo tests**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_billing_repo.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/backend/schemas/billing.py apps/backend/core/repositories/billing_repo.py
git commit -m "feat: update billing schemas and repo for usage-based model"
```

---

## Task 6: Billing Service & Router

Simplify billing service (remove tiers), update router with real usage data, pricing endpoint, spend limits.

**Files:**
- Modify: `apps/backend/core/services/billing_service.py`
- Modify: `apps/backend/routers/billing.py`

- [ ] **Step 1: Simplify `billing_service.py`**

Rewrite `apps/backend/core/services/billing_service.py`:

```python
"""Service for Stripe billing operations — usage-based model."""

import logging
import os

import stripe

from core.config import settings
from core.repositories import billing_repo

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY

METERED_PRICE_ID = os.getenv("STRIPE_METERED_PRICE_ID", "")
FRONTEND_URL = os.getenv(
    "FRONTEND_URL", settings.cors_origins_list[0] if settings.cors_origins_list else "http://localhost:3000"
)


class BillingServiceError(Exception):
    pass


class BillingService:
    """Manages Stripe customers, subscriptions, and checkout flows."""

    async def create_customer_for_user(self, clerk_user_id: str, email: str) -> dict:
        """Create Stripe customer + billing account. Idempotent."""
        existing = await billing_repo.get_by_clerk_user_id(clerk_user_id)
        if existing:
            return existing

        customer = stripe.Customer.create(
            email=email or None,
            metadata={"clerk_user_id": clerk_user_id},
        )

        return await billing_repo.get_or_create(
            clerk_user_id=clerk_user_id,
            stripe_customer_id=customer.id,
        )

    async def create_checkout_session(self, billing_account: dict) -> str:
        """Create a Stripe Checkout session for $0/mo metered subscription."""
        if not METERED_PRICE_ID:
            raise BillingServiceError("STRIPE_METERED_PRICE_ID not configured")

        session = stripe.checkout.Session.create(
            customer=billing_account["stripe_customer_id"],
            mode="subscription",
            line_items=[{"price": METERED_PRICE_ID}],
            success_url=f"{FRONTEND_URL}/chat?subscription=success",
            cancel_url=f"{FRONTEND_URL}/chat?subscription=canceled",
        )
        return session.url

    async def create_portal_session(self, billing_account: dict) -> str:
        """Create a Stripe Customer Portal session."""
        session = stripe.billing_portal.Session.create(
            customer=billing_account["stripe_customer_id"],
            return_url=f"{FRONTEND_URL}/settings/billing",
        )
        return session.url

    async def update_subscription(self, billing_account: dict, subscription_id: str) -> None:
        """Mark user as subscribed."""
        await billing_repo.update_subscription(
            clerk_user_id=billing_account["clerk_user_id"],
            stripe_subscription_id=subscription_id,
            plan_tier="paid",
        )

    async def cancel_subscription(self, billing_account: dict) -> None:
        """Revert to free tier."""
        await billing_repo.update_subscription(
            clerk_user_id=billing_account["clerk_user_id"],
            stripe_subscription_id=None,
            plan_tier="free",
        )
```

- [ ] **Step 2: Rewrite `routers/billing.py`**

Rewrite `apps/backend/routers/billing.py` — see spec for endpoint details. Key changes:
- `GET /account` returns real spend from usage service
- `GET /usage` returns `UsageSummary` from DynamoDB
- `GET /pricing` returns model pricing from `bedrock_pricing`
- `PUT /spend-limit` updates custom spend limit
- `POST /checkout` — no tier param
- Webhooks: no container provisioning/teardown

The full router should be written by the implementing agent using the spec and the schemas from Task 5. Key: import `usage_service`, `bedrock_pricing`, and the new schemas.

- [ ] **Step 3: Update billing router tests**

Update `apps/backend/tests/unit/routers/test_billing.py` to match the new API shape (no tier in checkout, real usage data, etc.). Check existing test file first for the test patterns used.

- [ ] **Step 4: Run all tests**

Run: `cd apps/backend && uv run pytest tests/ -v --timeout=30`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/billing_service.py apps/backend/routers/billing.py apps/backend/tests/unit/routers/test_billing.py
git commit -m "feat: simplify billing to usage-based model, add pricing and spend limit endpoints"
```

---

## Task 7: Pre-Chat Spend Limit Enforcement

Add spend limit check before forwarding chat messages to the gateway.

**Files:**
- Modify: `apps/backend/routers/websocket_chat.py:237-256`

- [ ] **Step 1: Add spend limit check in `agent_chat` handler**

In `apps/backend/routers/websocket_chat.py`, in the `agent_chat` block (around line 237), add the spend limit check before `background_tasks.add_task`:

```python
    if msg_type == "agent_chat":
        agent_id = body.get("agent_id")
        message = body.get("message")

        if not agent_id or not message:
            management_api = await get_management_api_client()
            management_api.send_message(
                x_connection_id,
                {"type": "error", "message": "Missing agent_id or message"},
            )
            return Response(status_code=200)

        # Spend limit check
        from core.services.usage_service import check_spend_limit
        limit_result = await check_spend_limit(user_id)
        if not limit_result["allowed"]:
            management_api = await get_management_api_client()
            management_api.send_message(
                x_connection_id,
                {
                    "type": "error",
                    "code": "SPEND_LIMIT_REACHED",
                    "message": "You've reached your spending limit. Add a payment method or increase your limit to continue.",
                    "current_spend": limit_result["current_spend"],
                    "limit": limit_result["limit"],
                    "is_subscribed": limit_result["is_subscribed"],
                },
            )
            return Response(status_code=200)

        background_tasks.add_task(
            _process_agent_chat_background,
            connection_id=x_connection_id,
            user_id=user_id,
            agent_id=agent_id,
            message=message,
        )
        return Response(status_code=200)
```

- [ ] **Step 2: Run existing websocket tests**

Run: `cd apps/backend && uv run pytest tests/ -v -k websocket --timeout=30`
Expected: PASS (existing tests should not be affected)

- [ ] **Step 3: Commit**

```bash
git add apps/backend/routers/websocket_chat.py
git commit -m "feat: add pre-chat spend limit enforcement"
```

---

## Task 8: Container Auto-Provisioning on Sync

Move container provisioning from Stripe webhook to user sync.

**Files:**
- Modify: `apps/backend/routers/users.py`

- [ ] **Step 1: Read current `users.py` to understand sync endpoint**

Read `apps/backend/routers/users.py` fully before modifying.

- [ ] **Step 2: Add container provisioning to sync endpoint**

In the `POST /sync` handler, after creating/syncing the user, check if a container exists. If not, provision one:

```python
# Auto-provision container for new users
from core.containers import get_ecs_manager
from core.containers.ecs_manager import EcsManagerError
from core.containers.workspace import WorkspaceError
from core.repositories import container_repo

existing_container = await container_repo.get_by_user_id(auth.user_id)
if not existing_container:
    try:
        service_name = await get_ecs_manager().provision_user_container(auth.user_id)
        logger.info("Auto-provisioned container %s for user %s", service_name, auth.user_id)
    except (EcsManagerError, WorkspaceError) as e:
        logger.error("Failed to auto-provision container for user %s: %s", auth.user_id, e)
```

- [ ] **Step 3: Run tests**

Run: `cd apps/backend && uv run pytest tests/ -v --timeout=30`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/backend/routers/users.py
git commit -m "feat: auto-provision container on user sync instead of Stripe webhook"
```

---

## Task 9: CDK Infrastructure

Add the `usage-counters` DynamoDB table and clean up Stripe env vars.

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`
- Modify: `apps/infra/lib/stacks/service-stack.ts:482-497`

- [ ] **Step 1: Add `usage-counters` table to `database-stack.ts`**

After the `apiKeysTable` definition (around line 79), add:

```typescript
    this.usageCountersTable = new dynamodb.Table(this, "UsageCountersTable", {
      tableName: `isol8-${env}-usage-counters`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "period", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });
```

Add the public property: `public readonly usageCountersTable: dynamodb.Table;`

- [ ] **Step 2: Clean up `service-stack.ts` env vars**

Remove `STRIPE_STARTER_FIXED_PRICE_ID` and `STRIPE_PRO_FIXED_PRICE_ID` entries (lines 482-489).
Add `FREE_TIER_MODEL` env var:

```typescript
        FREE_TIER_MODEL: "us.amazon.nova-lite-v1:0",
```

- [ ] **Step 3: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts apps/infra/lib/stacks/service-stack.ts
git commit -m "feat: add usage-counters DynamoDB table, remove fixed price env vars"
```

---

## 🔧 Task 10: Stripe Cleanup (MANUAL — orchestrator must perform)

This task requires manual Stripe dashboard/CLI operations. Pause agent execution and perform these steps before continuing.

- [ ] **Step 1: Delete old Stripe products (dev test mode)**

In the Stripe test mode dashboard or via CLI:
```bash
# Archive the old fixed-price products (Stripe doesn't allow deletion, only archival)
stripe prices archive price_1TBm0NI54BysGS3r57fcRXOJ  # Starter fixed
stripe prices archive price_1TBm0PI54BysGS3rFjUOtmrR  # Pro fixed
```

- [ ] **Step 2: Verify existing metered price and meter**

```bash
# Verify the meter exists and note the event name
stripe billing meters list
# Should show meter mtr_test_61UL9xth9m1qTEaXv41I54BysGS3rJCC

# Verify the metered price exists
stripe prices retrieve price_1TBm0fI54BysGS3rrqTaZ5Zz
```

Check that the meter's `event_name` matches what `usage_service.py` reports (`llm_usage`). If it doesn't match, either update the meter or update the code.

- [ ] **Step 3: Create new product (if needed)**

If the existing metered price is attached to a product with "Starter" or "Pro" in the name, create a clean product:

```bash
stripe products create --name="Isol8 Usage" --description="Pay-as-you-go LLM usage"
# Note the product ID, attach the existing metered price to it if needed
```

- [ ] **Step 4: Verify checkout works with $0 subscription**

Test that creating a checkout session with only the metered price line item works (the subscription total will be $0/mo + usage).

---

## Task 11: Free-Tier Model Restriction

Enforce that free users can only use the cheap model. Restriction happens at the config layer (when writing `openclaw.json`) and in the Stripe webhook (unlock/lock on subscription change).

**Files:**
- Modify: `apps/backend/core/containers/config.py`
- Modify: `apps/backend/routers/billing.py` (webhook section)

- [ ] **Step 1: Read `core/containers/config.py`**

Read `apps/backend/core/containers/config.py` fully to understand `write_openclaw_config()`. Find where the model is set in the agent config and where the `models` list is populated.

- [ ] **Step 2: Add subscription check to `write_openclaw_config()`**

In `write_openclaw_config()`, add a parameter `is_subscribed: bool = True`. When `is_subscribed` is `False`:
- Override the agent's model to `settings.FREE_TIER_MODEL`
- Only include `settings.FREE_TIER_MODEL` in the available models list

The caller must pass subscription status. Check `billing_repo.get_by_clerk_user_id()` when provisioning.

- [ ] **Step 3: Update webhook to rewrite config on subscription changes**

In `routers/billing.py`, in the `customer.subscription.created` handler:
- After marking user as subscribed, rewrite `openclaw.json` with `is_subscribed=True` (unlocks all models)

In the `customer.subscription.deleted` handler:
- After reverting to free tier, rewrite `openclaw.json` with `is_subscribed=False` (locks to free model)

Use the existing `write_openclaw_config()` function. The container keeps running — only the config on EFS changes. OpenClaw picks up config changes on next chat.

- [ ] **Step 4: Run tests**

Run: `cd apps/backend && uv run pytest tests/ -v --timeout=30`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/containers/config.py apps/backend/routers/billing.py
git commit -m "feat: enforce free-tier model restriction via openclaw.json config"
```

---

## Task 12: Frontend — Billing Hook & UsagePanel

Rewrite frontend to consume backend APIs instead of client-side calculation.

**Files:**
- Modify: `apps/frontend/src/hooks/useBilling.ts`
- Modify: `apps/frontend/src/components/control/panels/UsagePanel.tsx`

- [ ] **Step 1: Read current `useBilling.ts` and `UsagePanel.tsx`**

Read both files fully before modifying.

- [ ] **Step 2: Update `useBilling.ts`**

Update the hook to match the new API response shape:
- `account` response now has `is_subscribed`, `spend_limit`, `lifetime_spend`, `current_period.current_spend`
- Add `updateSpendLimit(limit: number | null)` → `PUT /billing/spend-limit`
- Add `fetchUsage()` → `GET /billing/usage`
- Add `fetchPricing()` → `GET /billing/pricing`
- Remove any tier-specific logic (`planTier`, `isSubscribed` based on tier, etc.)

- [ ] **Step 3: Rewrite `UsagePanel.tsx`**

Remove all client-side cost calculation code:
- Delete `MODEL_PRICING`, `MARKUP`, `getModelPricing()`, `FALLBACK_PRICING`
- Delete `useGatewayRpc("sessions.list")` and all `sessionStats` computation
- Delete `TOOL_MODEL_IDS`, `TOOL_DISPLAY_NAMES`, `isToolUsage`, `toolDisplayName`

Replace with REST-only data fetching:
- Fetch `GET /billing/account` for spend/limit info
- Fetch `GET /billing/usage` for usage breakdown
- Add a spend limit control (input + save button) calling `PUT /billing/spend-limit`
- Budget bar shows `current_spend` vs `spend_limit`

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/hooks/useBilling.ts apps/frontend/src/components/control/panels/UsagePanel.tsx
git commit -m "feat: rewrite UsagePanel to use backend APIs, remove client-side cost calculation"
```

---

## Task 13: Frontend — Chat Error Handling, Model Selector & Provisioning

Handle spend limit errors in the chat UI, restrict model selector for free users, and remove billing from the provisioning stepper.

**Files:**
- Modify: `apps/frontend/src/components/chat/AgentChatWindow.tsx`
- Modify: `apps/frontend/src/components/chat/ChatInput.tsx`
- Modify: `apps/frontend/src/components/chat/ModelSelector.tsx`
- Modify: `apps/frontend/src/components/chat/ProvisioningStepper.tsx`

- [ ] **Step 1: Read current files**

Read `AgentChatWindow.tsx`, `ChatInput.tsx`, `ModelSelector.tsx`, and `ProvisioningStepper.tsx`.

- [ ] **Step 2: Handle `SPEND_LIMIT_REACHED` in chat**

In `AgentChatWindow.tsx`, check for `code: "SPEND_LIMIT_REACHED"` in WebSocket error messages:
- Show an inline banner: "You've reached your spending limit"
- If `is_subscribed` is false: CTA button "Add payment method" → triggers Stripe Checkout
- If `is_subscribed` is true: CTA button "Increase limit" → opens spend limit settings

In `ChatInput.tsx`:
- Disable the chat input when a `SPEND_LIMIT_REACHED` error is active
- Show placeholder text explaining the limit

- [ ] **Step 3: Restrict model list for free users**

`ModelSelector` is a controlled component — it receives `models` as a prop from its parent. The restriction happens at the data level, not in the component:

In the parent component that provides models to `ModelSelector`, filter based on subscription status:
- Free users: filter the models list to only include `free_tier_model` (from `GET /billing/pricing`)
- Subscribed users: pass all models as before

This means `ModelSelector.tsx` itself may not need changes — the parent filters what it receives. Read the parent to determine where the models list comes from (likely via `useGatewayRpc("models.list")` or similar).

- [ ] **Step 4: Simplify `ProvisioningStepper.tsx`**

Remove the billing/checkout step. Container now provisions on sign-up.
Add a text banner: "You have $2 in free usage. Add a payment method anytime to unlock all models."

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/chat/AgentChatWindow.tsx apps/frontend/src/components/chat/ChatInput.tsx apps/frontend/src/components/chat/ModelSelector.tsx apps/frontend/src/components/chat/ProvisioningStepper.tsx
git commit -m "feat: handle spend limit errors, restrict models for free users, simplify stepper"
```

---

## Task 14: Final Integration Test & Cleanup

Run all tests, verify the full flow, clean up.

**Files:**
- All modified files

- [ ] **Step 1: Run full backend test suite**

Run: `cd apps/backend && uv run pytest tests/ -v --timeout=30`
Expected: All PASS

- [ ] **Step 2: Run frontend lint and build**

Run: `cd apps/frontend && pnpm run lint && pnpm run build`
Expected: No errors

- [ ] **Step 3: Check for any remaining references to old code**

Search for dead references:
- `PLAN_BUDGETS` — should have zero hits
- `PLAN_PRICES` — should have zero hits
- `bedrock_discovery` — should have zero hits
- `PlanTier` — should have zero hits (except maybe frontend if not yet cleaned)
- `STRIPE_STARTER_FIXED_PRICE_ID` — should have zero hits
- `STRIPE_PRO_FIXED_PRICE_ID` — should have zero hits

- [ ] **Step 4: Final commit if any cleanup needed**

```bash
git add -A && git commit -m "chore: clean up dead references to old billing model"
```
