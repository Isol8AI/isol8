"""Tests for usage service — counter writes for analytics."""

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
        with (
            patch("core.dynamodb._table_prefix", "test-"),
            patch("core.dynamodb._dynamodb_resource", client),
        ):
            yield


@pytest.mark.asyncio
async def test_record_usage_increments_owner_lifetime_and_member(dynamodb_tables):
    from core.repositories import usage_repo
    from core.services.usage_service import _current_period, record_usage

    await record_usage(
        owner_id="org_1",
        user_id="user_a",
        model="anthropic.claude-sonnet-4-6",
        input_tokens=1000,
        output_tokens=500,
        cache_read=0,
        cache_write=0,
    )

    period = _current_period()

    owner_usage = await usage_repo.get_period_usage("org_1", period)
    assert owner_usage is not None
    assert owner_usage["request_count"] == 1

    lifetime = await usage_repo.get_period_usage("org_1", "lifetime")
    assert lifetime is not None

    member_usage = await usage_repo.get_period_usage("org_1", f"member:user_a:{period}")
    assert member_usage is not None
    assert member_usage["request_count"] == 1


@pytest.mark.asyncio
async def test_record_usage_strips_provider_prefix(dynamodb_tables):
    """Models from chat.final arrive prefixed (``amazon-bedrock/``); the prefix
    must be stripped before pricing lookup."""
    from core.repositories import usage_repo
    from core.services.usage_service import _current_period, record_usage

    await record_usage(
        owner_id="org_2",
        user_id="user_b",
        model="amazon-bedrock/anthropic.claude-opus-4-6-v1",
        input_tokens=1000,
        output_tokens=500,
        cache_read=0,
        cache_write=0,
    )
    period = _current_period()
    owner_usage = await usage_repo.get_period_usage("org_2", period)
    assert owner_usage is not None
    assert owner_usage["request_count"] == 1


@pytest.mark.asyncio
async def test_record_usage_unknown_model_skips(dynamodb_tables):
    from core.services.usage_service import record_usage

    # Should not raise
    await record_usage("user_1", "user_1", "unknown-model", 1000, 500, 0, 0)


@pytest.mark.asyncio
async def test_get_usage_summary_returns_zeros_for_empty(dynamodb_tables):
    from core.services.usage_service import get_usage_summary

    summary = await get_usage_summary("user_with_no_usage")
    assert summary["total_spend"] == 0
    assert summary["request_count"] == 0
    assert summary["lifetime_spend"] == 0
