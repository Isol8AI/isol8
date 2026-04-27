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
    """event_id is global; the same id from different sources still dedupes."""
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
    item = client.get_item(TableName=dedup_table, Key={"event_id": {"S": "evt_ttl"}})["Item"]
    ttl = int(item["ttl"]["N"])
    assert before + 2_592_000 - 5 <= ttl <= after + 2_592_000 + 5
