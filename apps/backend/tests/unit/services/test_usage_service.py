"""Tests for usage service."""

import os
from unittest.mock import patch

import boto3
import pytest
from moto import mock_aws

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def dynamodb_tables():
    with mock_aws():
        client = boto3.resource("dynamodb", region_name="us-east-1")
        # Usage counters
        client.create_table(
            TableName="test-usage-counters",
            KeySchema=[
                {"AttributeName": "owner_id", "KeyType": "HASH"},
                {"AttributeName": "period", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "owner_id", "AttributeType": "S"},
                {"AttributeName": "period", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        # Billing accounts
        client.create_table(
            TableName="test-billing-accounts",
            KeySchema=[{"AttributeName": "owner_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "owner_id", "AttributeType": "S"},
                {"AttributeName": "stripe_customer_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "stripe-customer-index",
                    "KeySchema": [{"AttributeName": "stripe_customer_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        with (
            patch("core.dynamodb._table_prefix", "test-"),
            patch("core.dynamodb._dynamodb_resource", client),
        ):
            yield


@pytest.fixture
def mock_stripe():
    with patch("core.services.usage_service.stripe") as mock:
        yield mock


@pytest.mark.asyncio
async def test_record_usage_increments_owner_and_member(dynamodb_tables, mock_stripe):
    from core.repositories import billing_repo, usage_repo
    from core.services.usage_service import record_usage

    await billing_repo.create_if_not_exists("org_1", "cus_abc", owner_type="org")

    await record_usage(
        owner_id="org_1",
        user_id="user_a",
        model="qwen.qwen3-vl-235b-a22b",
        input_tokens=1000,
        output_tokens=500,
        cache_read=0,
        cache_write=0,
    )

    from core.services.usage_service import _current_period

    period = _current_period()

    # Owner-level counter
    owner_usage = await usage_repo.get_period_usage("org_1", period)
    assert owner_usage is not None
    assert owner_usage["request_count"] == 1

    # Lifetime counter
    lifetime = await usage_repo.get_period_usage("org_1", "lifetime")
    assert lifetime is not None

    # Member counter
    member_usage = await usage_repo.get_period_usage("org_1", f"member:user_a:{period}")
    assert member_usage is not None
    assert member_usage["request_count"] == 1


@pytest.mark.asyncio
async def test_check_budget_free_under_limit(dynamodb_tables):
    from core.repositories import billing_repo
    from core.services.usage_service import check_budget

    await billing_repo.create_if_not_exists("user_1", "cus_abc")

    result = await check_budget("user_1")
    assert result["allowed"] is True
    assert result["within_included"] is True


@pytest.mark.asyncio
async def test_check_budget_free_over_limit(dynamodb_tables):
    from core.repositories import billing_repo, usage_repo
    from core.services.usage_service import check_budget

    await billing_repo.create_if_not_exists("user_1", "cus_abc")
    await usage_repo.increment("user_1", "lifetime", 3_000_000, 0, 0, 0, 0)

    result = await check_budget("user_1")
    assert result["allowed"] is False


@pytest.mark.asyncio
async def test_check_budget_starter_within_included(dynamodb_tables):
    from core.repositories import billing_repo
    from core.services.usage_service import check_budget

    await billing_repo.create_if_not_exists("user_1", "cus_abc")
    await billing_repo.update_subscription("user_1", "sub_123", "starter")

    result = await check_budget("user_1")
    assert result["allowed"] is True
    assert result["within_included"] is True


@pytest.mark.asyncio
async def test_check_budget_starter_over_included_no_overage(dynamodb_tables):
    from core.repositories import billing_repo, usage_repo
    from core.services.usage_service import check_budget, _current_period

    await billing_repo.create_if_not_exists("user_1", "cus_abc")
    await billing_repo.update_subscription("user_1", "sub_123", "starter")
    await usage_repo.increment("user_1", _current_period(), 11_000_000, 0, 0, 0, 0)

    result = await check_budget("user_1")
    assert result["allowed"] is False
    assert result["within_included"] is False
    assert result["overage_available"] is True  # can opt in


@pytest.mark.asyncio
async def test_check_budget_starter_overage_enabled(dynamodb_tables):
    from core.repositories import billing_repo, usage_repo
    from core.services.usage_service import check_budget, _current_period

    await billing_repo.create_if_not_exists("user_1", "cus_abc")
    await billing_repo.update_subscription("user_1", "sub_123", "starter")

    # Enable overage
    existing = await billing_repo.get_by_owner_id("user_1")
    existing["overage_enabled"] = True
    from core.dynamodb import get_table, run_in_thread

    table = get_table("billing-accounts")
    await run_in_thread(table.put_item, Item=existing)

    await usage_repo.increment("user_1", _current_period(), 11_000_000, 0, 0, 0, 0)

    result = await check_budget("user_1")
    assert result["allowed"] is True
    assert result["within_included"] is False


@pytest.mark.asyncio
async def test_record_usage_unknown_model_skips(dynamodb_tables, mock_stripe):
    from core.repositories import billing_repo
    from core.services.usage_service import record_usage

    await billing_repo.create_if_not_exists("user_1", "cus_abc")
    await record_usage("user_1", "user_1", "unknown-model", 1000, 500, 0, 0)
    # Should not raise
