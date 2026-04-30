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
