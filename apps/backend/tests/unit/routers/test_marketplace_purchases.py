"""Tests for marketplace_purchases router."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


@patch("routers.marketplace_purchases.stripe.Webhook.construct_event")
@patch("routers.marketplace_purchases.webhook_dedup.record_event_or_skip")
@patch("routers.marketplace_purchases.license_service.generate", return_value="iml_test")
@patch("routers.marketplace_purchases._purchases_table")
@patch("routers.marketplace_purchases._payout_accounts_table")
def test_webhook_checkout_completed_grants_license(
    mock_pa_table, mock_purchases_table, mock_gen, mock_dedup, mock_construct, client
):
    from core.services.webhook_dedup import WebhookDedupResult

    mock_dedup.return_value = WebhookDedupResult.RECORDED
    mock_construct.return_value = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_1",
                "metadata": {
                    "listing_id": "l1",
                    "buyer_id": "b1",
                    "seller_id": "s1",
                    "version": "1",
                },
                "amount_total": 2000,
                "payment_intent": "pi_1",
            }
        },
    }
    mock_purchases_table.return_value.put_item = MagicMock()
    mock_pa_table.return_value.update_item = MagicMock()

    resp = client.post(
        "/api/v1/marketplace/webhooks/stripe-marketplace",
        headers={"stripe-signature": "test"},
        content=b'{"id":"evt_1","type":"checkout.session.completed"}',
    )
    assert resp.status_code == 200
    mock_purchases_table.return_value.put_item.assert_called_once()


@patch("routers.marketplace_purchases.webhook_dedup.record_event_or_skip")
@patch("routers.marketplace_purchases.stripe.Webhook.construct_event")
def test_webhook_idempotent_on_replay(mock_construct, mock_dedup, client):
    from core.services.webhook_dedup import WebhookDedupResult

    mock_dedup.return_value = WebhookDedupResult.ALREADY_SEEN
    mock_construct.return_value = {
        "id": "evt_1",
        "type": "checkout.session.completed",
        "data": {"object": {}},
    }
    resp = client.post(
        "/api/v1/marketplace/webhooks/stripe-marketplace",
        headers={"stripe-signature": "test"},
        content=b'{"id":"evt_1"}',
    )
    assert resp.status_code == 200


def test_cli_auth_start_returns_device_code(client):
    resp = client.post("/api/v1/marketplace/cli/auth/start")
    assert resp.status_code == 200
    body = resp.json()
    assert "device_code" in body
    assert "browser_url" in body
    assert body["expires_in_seconds"] == 300
