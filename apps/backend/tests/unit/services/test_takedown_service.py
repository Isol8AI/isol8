"""Tests for takedown_service."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from core.services import takedown_service  # noqa: E402


@pytest.mark.asyncio
@patch("core.services.takedown_service._purchases_table")
@patch("core.services.takedown_service._listings_table")
@patch("core.services.takedown_service._takedowns_table")
@patch("core.services.takedown_service.license_service.revoke", new=AsyncMock())
async def test_execute_full_takedown_revokes_all_licenses(mock_takedowns, mock_listings, mock_purchases):
    mock_purchases.return_value.query.return_value = {
        "Items": [
            {"buyer_id": "b1", "purchase_id": "p1"},
            {"buyer_id": "b2", "purchase_id": "p2"},
            {"buyer_id": "b3", "purchase_id": "p3"},
        ]
    }
    mock_listings.return_value.update_item = MagicMock()
    mock_takedowns.return_value.update_item = MagicMock()

    await takedown_service.execute_full_takedown(listing_id="l1", takedown_id="t1", decided_by="admin_xyz")

    assert takedown_service.license_service.revoke.await_count == 3
    mock_listings.return_value.update_item.assert_called_once()
    update_kwargs = mock_listings.return_value.update_item.call_args.kwargs
    assert ":taken" in update_kwargs["ExpressionAttributeValues"]


@pytest.mark.asyncio
@patch("core.services.takedown_service._takedowns_table")
async def test_file_takedown_creates_row(mock_table):
    mock_table.return_value.put_item = MagicMock()
    tid = await takedown_service.file_takedown(
        listing_id="l1",
        reason="dmca",
        claimant_name="Alice",
        claimant_email="alice@example.com",
        basis_md="...",
    )
    assert tid is not None
    mock_table.return_value.put_item.assert_called_once()


@pytest.mark.asyncio
@patch("core.services.takedown_service._purchases_table")
@patch("core.services.takedown_service._listings_table")
@patch("core.services.takedown_service._takedowns_table")
@patch("core.services.takedown_service.license_service.revoke", new=AsyncMock())
async def test_execute_admin_initiated_takedown(mock_takedowns, mock_listings, mock_purchases):
    """Admin-initiated takedown writes the row + cascades all four side effects."""
    # Reset the shared AsyncMock so other tests' await counts don't leak in.
    takedown_service.license_service.revoke.reset_mock()

    mock_purchases.return_value.query.return_value = {
        "Items": [
            {"buyer_id": "b1", "purchase_id": "p1"},
            {"buyer_id": "b2", "purchase_id": "p2"},
        ]
    }
    mock_takedowns.return_value.put_item = MagicMock()
    mock_takedowns.return_value.update_item = MagicMock()
    mock_listings.return_value.update_item = MagicMock()

    result = await takedown_service.execute_admin_initiated_takedown(
        listing_id="l-abc",
        reason="policy",
        basis_md="Listing violates platform policy section 4.",
        decided_by="user_admin1",
    )

    # 1. Returned envelope is well-formed.
    assert result["listing_id"] == "l-abc"
    assert result["affected_purchases"] == 2
    assert isinstance(result["takedown_id"], str) and result["takedown_id"]

    # 2. Takedown row was written as `pending` with admin sentinel email —
    #    the cascade flips it to `granted` + stamps `decided_by/decided_at`
    #    in a single update_item, so the put intentionally omits decision
    #    metadata to avoid a double-write.
    mock_takedowns.return_value.put_item.assert_called_once()
    put_item = mock_takedowns.return_value.put_item.call_args.kwargs["Item"]
    assert put_item["listing_id"] == "l-abc"
    assert put_item["decision"] == "pending"
    assert "decided_by" not in put_item
    assert "decided_at" not in put_item
    assert put_item["filed_by_name"] == "admin"
    assert put_item["filed_by_email"] == takedown_service.ADMIN_FILED_BY_EMAIL
    assert put_item["reason"] == "policy"
    assert put_item["basis_md"] == "Listing violates platform policy section 4."
    assert put_item["takedown_id"] == result["takedown_id"]

    # 3. Every purchase had its license revoked.
    assert takedown_service.license_service.revoke.await_count == 2

    # 4. Listing status flipped to taken_down.
    mock_listings.return_value.update_item.assert_called_once()
    update_kwargs = mock_listings.return_value.update_item.call_args.kwargs
    assert update_kwargs["ExpressionAttributeValues"][":taken"] == "taken_down"

    # 5. Takedown row stamped with affected_purchases count.
    mock_takedowns.return_value.update_item.assert_called_once()
    stamp_kwargs = mock_takedowns.return_value.update_item.call_args.kwargs
    assert stamp_kwargs["ExpressionAttributeValues"][":n"] == 2
    assert stamp_kwargs["ExpressionAttributeValues"][":granted"] == "granted"
    assert stamp_kwargs["ExpressionAttributeValues"][":by"] == "user_admin1"
