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


# ----------------------------------------------------------------------
# /my-purchases
# ----------------------------------------------------------------------


@pytest.fixture
def auth_buyer():
    from core.auth import AuthContext, get_current_user
    from main import app

    async def _mock():
        return AuthContext(user_id="user_buyer_xyz")

    app.dependency_overrides[get_current_user] = _mock
    yield "user_buyer_xyz"
    app.dependency_overrides.pop(get_current_user, None)


def _purchases_table_mock(items):
    table = MagicMock()
    table.query.return_value = {"Items": items}
    return table


def _listings_table_get_item(slug_by_listing_id):
    table = MagicMock()

    def _get_item(Key):
        lid = Key["listing_id"]
        slug = slug_by_listing_id.get(lid)
        if slug is None:
            return {"Item": None}
        return {"Item": {"listing_id": lid, "version": 1, "slug": slug}}

    table.get_item.side_effect = _get_item
    return table


def test_my_purchases_returns_buyer_items(client, auth_buyer):
    purchases = [
        {
            "buyer_id": auth_buyer,
            "purchase_id": "p1",
            "listing_id": "L1",
            "license_key": "iml_aaa",
            "price_paid_cents": 500,
            "status": "paid",
            "created_at": "2026-04-30T12:00:00Z",
        },
        {
            "buyer_id": auth_buyer,
            "purchase_id": "p2",
            "listing_id": "L2",
            "license_key": "iml_bbb",
            "price_paid_cents": 1500,
            "status": "refunded",
            "created_at": "2026-04-29T08:30:00Z",
        },
    ]
    purchases_table = _purchases_table_mock(purchases)
    listings_table = _listings_table_get_item({"L1": "skill-a", "L2": "skill-b"})

    with patch("routers.marketplace_purchases._purchases_table", return_value=purchases_table):
        with patch("routers.marketplace_purchases.boto3.resource") as mock_resource:
            mock_resource.return_value.Table.return_value = listings_table
            resp = client.get("/api/v1/marketplace/my-purchases")

    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert items[0]["purchase_id"] == "p1"
    assert items[0]["listing_slug"] == "skill-a"
    assert items[1]["status"] == "refunded"


def test_my_purchases_empty_for_new_buyer(client, auth_buyer):
    purchases_table = _purchases_table_mock([])
    with patch("routers.marketplace_purchases._purchases_table", return_value=purchases_table):
        resp = client.get("/api/v1/marketplace/my-purchases")
    assert resp.status_code == 200
    assert resp.json()["items"] == []


def test_my_purchases_only_returns_caller_items(client, auth_buyer):
    """The DDB query is keyed by buyer_id == caller; verify the query call uses it."""
    purchases_table = _purchases_table_mock([])
    with patch("routers.marketplace_purchases._purchases_table", return_value=purchases_table):
        resp = client.get("/api/v1/marketplace/my-purchases")
    assert resp.status_code == 200
    purchases_table.query.assert_called_once()
    kwargs = purchases_table.query.call_args.kwargs
    assert kwargs["ExpressionAttributeValues"][":b"] == auth_buyer
