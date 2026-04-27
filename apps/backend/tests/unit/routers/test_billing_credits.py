"""Tests for the credit-management endpoints (Plan 2 Tasks 14 + 15)."""

import json
from unittest.mock import AsyncMock, patch

import boto3
import pytest
from moto import mock_aws


@pytest.fixture
def credit_ledger_tables(monkeypatch):
    """Provision moto-mocked credits + credit-transactions + webhook-dedup tables.

    Plan 1 (Stripe webhook event dedup, merged in main as `c9113ca`) makes
    the Stripe webhook handler call record_event_or_skip first; that helper
    fails fast if WEBHOOK_DEDUP_TABLE is empty. The credit-top-up webhook
    test routes through that path, so the fixture also provisions the
    dedup table.
    """
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="test-credits",
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        client.create_table(
            TableName="test-credit-txns",
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "tx_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "tx_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        client.create_table(
            TableName="test-webhook-event-dedup",
            KeySchema=[{"AttributeName": "event_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "event_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        monkeypatch.setenv("CREDITS_TABLE", "test-credits")
        monkeypatch.setenv("CREDIT_TRANSACTIONS_TABLE", "test-credit-txns")
        monkeypatch.setenv("WEBHOOK_DEDUP_TABLE", "test-webhook-event-dedup")
        yield


@pytest.mark.asyncio
async def test_get_balance_returns_microcents(async_client, credit_ledger_tables):
    with patch(
        "routers.billing.credit_ledger.get_balance",
        new=AsyncMock(return_value=12_345_678),
    ):
        resp = await async_client.get("/api/v1/billing/credits/balance")
    assert resp.status_code == 200
    assert resp.json() == {
        "balance_microcents": 12_345_678,
        "balance_dollars": "12.35",
    }


@pytest.mark.asyncio
async def test_top_up_creates_payment_intent(async_client, credit_ledger_tables):
    fake_pi = type("PI", (), {"id": "pi_test", "client_secret": "secret_test"})()
    with (
        patch(
            "routers.billing.billing_repo.get_by_owner_id",
            new=AsyncMock(return_value={"stripe_customer_id": "cus_test"}),
        ),
        patch("stripe.PaymentIntent.create", return_value=fake_pi) as mock_pi,
    ):
        resp = await async_client.post(
            "/api/v1/billing/credits/top_up",
            json={"amount_cents": 2000},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["client_secret"] == "secret_test"
    assert body["payment_intent_id"] == "pi_test"
    _, kwargs = mock_pi.call_args
    assert kwargs["amount"] == 2000
    assert kwargs["currency"] == "usd"
    assert kwargs["customer"] == "cus_test"
    assert kwargs["metadata"]["purpose"] == "credit_top_up"
    assert kwargs["metadata"]["user_id"] == "user_test_123"
    assert "idempotency_key" in kwargs


@pytest.mark.asyncio
async def test_top_up_below_minimum_rejected(async_client, credit_ledger_tables):
    resp = await async_client.post(
        "/api/v1/billing/credits/top_up",
        json={"amount_cents": 100},
    )
    # 422 when Pydantic ge=500 catches it before the handler body runs.
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_set_auto_reload_persists(async_client, credit_ledger_tables):
    with patch("routers.billing.credit_ledger.set_auto_reload", new=AsyncMock()) as mock_set:
        resp = await async_client.put(
            "/api/v1/billing/credits/auto_reload",
            json={"enabled": True, "threshold_cents": 500, "amount_cents": 5000},
        )
    assert resp.status_code == 200
    _, kwargs = mock_set.call_args
    assert kwargs["enabled"] is True
    assert kwargs["threshold_cents"] == 500
    assert kwargs["amount_cents"] == 5000


@pytest.mark.asyncio
async def test_payment_intent_succeeded_credits_ledger(async_client, monkeypatch, credit_ledger_tables):
    fake_event = {
        "id": "evt_pi_credit_1",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_test",
                "amount": 2000,  # $20
                "metadata": {
                    "purpose": "credit_top_up",
                    "user_id": "u_buyer",
                },
            }
        },
    }
    monkeypatch.setattr(
        "stripe.Webhook.construct_event",
        lambda body, sig, secret: fake_event,
    )

    with patch("routers.billing.credit_ledger.top_up", new=AsyncMock(return_value=20_000_000)) as mock_top_up:
        resp = await async_client.post(
            "/api/v1/billing/webhooks/stripe",
            content=json.dumps(fake_event),
            headers={"stripe-signature": "ignored"},
        )

    assert resp.status_code == 200
    _, kwargs = mock_top_up.call_args
    assert kwargs["amount_microcents"] == 20_000_000
    assert kwargs["stripe_payment_intent_id"] == "pi_test"
