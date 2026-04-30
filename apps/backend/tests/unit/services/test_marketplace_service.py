"""Tests for marketplace_service."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from core.services import marketplace_service  # noqa: E402


@pytest.mark.asyncio
@patch("core.services.marketplace_service._listings_table")
@patch("core.services.marketplace_service._versions_table")
@patch(
    "core.services.marketplace_service._upload_artifact_to_s3",
    new=AsyncMock(return_value=("listings/abc/v1/", "sha-1")),
)
async def test_create_draft_listing(mock_versions, mock_listings):
    mock_listings.return_value.query.return_value = {"Items": []}  # no slug collision
    mock_listings.return_value.put_item = MagicMock()
    mock_versions.return_value.put_item = MagicMock()
    listing = await marketplace_service.create_draft(
        seller_id="user_abc",
        slug="my-agent",
        name="My Agent",
        description_md="cool",
        format="openclaw",
        delivery_method="cli",
        price_cents=2000,
        tags=["sales"],
        artifact_bytes=b"tar bytes",
        manifest={"name": "My Agent"},
    )
    assert listing["status"] == "draft"
    assert listing["seller_id"] == "user_abc"
    assert listing["slug"] == "my-agent"
    assert listing["version"] == 1


@pytest.mark.asyncio
@patch("core.services.marketplace_service._listings_table")
async def test_create_draft_rejects_duplicate_slug(mock_listings):
    mock_listings.return_value.query.return_value = {"Items": [{"slug": "my-agent"}]}
    with pytest.raises(marketplace_service.SlugCollisionError):
        await marketplace_service.create_draft(
            seller_id="user_abc",
            slug="my-agent",
            name="My Agent",
            description_md="cool",
            format="openclaw",
            delivery_method="cli",
            price_cents=2000,
            tags=["sales"],
            artifact_bytes=b"x",
            manifest={"name": "x"},
        )


@pytest.mark.asyncio
@patch("core.services.marketplace_service._listings_table")
async def test_submit_listing_transitions_draft_to_review(mock_listings):
    mock_listings.return_value.update_item = MagicMock(return_value={"Attributes": {"status": "review"}})
    result = await marketplace_service.submit_for_review(listing_id="l1", seller_id="user_abc")
    assert result["status"] == "review"
    kwargs = mock_listings.return_value.update_item.call_args.kwargs
    # ConditionExpression must require status='draft' to prevent
    # double-submit or submit from a wrong state.
    values = kwargs.get("ExpressionAttributeValues", {})
    assert ":draft" in values or "draft" in str(values)


@pytest.mark.asyncio
@patch("core.services.marketplace_service._listings_table")
async def test_submit_rejects_when_not_in_draft(mock_listings):
    from botocore.exceptions import ClientError

    mock_listings.return_value.update_item = MagicMock(
        side_effect=ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}},
            "UpdateItem",
        )
    )
    with pytest.raises(marketplace_service.InvalidStateError):
        await marketplace_service.submit_for_review(listing_id="l1", seller_id="user_abc")


@pytest.mark.asyncio
@patch("core.services.marketplace_service._dynamodb_client")
async def test_publish_v2_uses_transact_write_items(mock_client):
    """Publishing v2 must atomically write the new versions row + update LATEST."""
    mock_client.return_value.transact_write_items = MagicMock(return_value={})
    await marketplace_service.publish_v2(
        listing_id="l1",
        new_version=2,
        new_s3_prefix="listings/l1/v2/",
        new_manifest={"name": "x"},
        new_manifest_sha256="sha-2",
        approved_by="admin_xyz",
    )
    mock_client.return_value.transact_write_items.assert_called_once()
    items = mock_client.return_value.transact_write_items.call_args.kwargs["TransactItems"]
    assert len(items) == 2
    actions = sorted(list(item.keys())[0] for item in items)
    assert actions == ["Put", "Update"]
