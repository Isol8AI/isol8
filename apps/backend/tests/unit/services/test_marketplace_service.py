"""Tests for marketplace_service."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from core.services import marketplace_service  # noqa: E402


@pytest.mark.asyncio
@patch("core.services.marketplace_service._listings_table")
@patch(
    "core.services.marketplace_service._upload_artifact_to_s3",
    new=AsyncMock(return_value=("listings/abc/v1/", "sha-1")),
)
async def test_create_draft_listing(mock_listings):
    mock_listings.return_value.query.return_value = {"Items": []}  # no slug collision
    mock_listings.return_value.put_item = MagicMock()
    listing = await marketplace_service.create_draft(
        seller_id="user_abc",
        slug="my-agent",
        name="My Agent",
        description_md="cool",
        format="openclaw",
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
async def test_submit_for_review_populates_published_at_for_moderation_gsi(mock_listings):
    """Regression: status-published-index has published_at as its sort key.
    DynamoDB sparse-GSI semantics exclude items whose sort key is None, so
    submit_for_review MUST set published_at or the moderation queue is
    structurally empty (Codex P1 on PR #517, commit 597f4a5d)."""
    mock_listings.return_value.update_item = MagicMock(return_value={"Attributes": {"status": "review"}})
    await marketplace_service.submit_for_review(listing_id="l1", seller_id="user_abc")
    kwargs = mock_listings.return_value.update_item.call_args.kwargs
    assert "published_at" in kwargs["UpdateExpression"]


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
@patch("core.services.marketplace_service._listings_table")
async def test_reject_uses_conditional_status_check(mock_listings):
    """Regression: reject must guard with ConditionExpression so a malformed
    admin request can't upsert a fabricated listing (DDB UpdateItem upserts
    by default) or transition a non-review row (Codex P1 on PR #517,
    commit bee2fa1c).
    """
    mock_listings.return_value.update_item = MagicMock()
    await marketplace_service.reject(listing_id="l1", version=1, notes="incomplete docs", rejected_by="admin_xyz")
    kwargs = mock_listings.return_value.update_item.call_args.kwargs
    assert "ConditionExpression" in kwargs
    assert ":review" in kwargs["ExpressionAttributeValues"]


@pytest.mark.asyncio
@patch("core.services.marketplace_service._listings_table")
async def test_reject_rejects_non_review_state(mock_listings):
    from botocore.exceptions import ClientError

    mock_listings.return_value.update_item = MagicMock(
        side_effect=ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}},
            "UpdateItem",
        )
    )
    with pytest.raises(marketplace_service.InvalidStateError):
        await marketplace_service.reject(listing_id="l1", version=1, notes="x", rejected_by="admin_xyz")


@pytest.mark.asyncio
@patch("core.services.marketplace_service._dynamodb_client")
async def test_publish_v2_atomically_retires_prev_and_publishes_new(mock_client):
    """Publishing v_new atomically flips prev_version -> retired AND
    new_version -> published in a single TransactWriteItems on the
    listings table."""
    mock_client.return_value.transact_write_items = MagicMock(return_value={})
    await marketplace_service.publish_v2(
        listing_id="l1",
        prev_version=1,
        new_version=2,
        approved_by="admin_xyz",
    )
    mock_client.return_value.transact_write_items.assert_called_once()
    items = mock_client.return_value.transact_write_items.call_args.kwargs["TransactItems"]
    assert len(items) == 2
    # Both items are Updates on the listings table (single-table design).
    actions = [list(item.keys())[0] for item in items]
    assert actions == ["Update", "Update"]
    # First update retires the previous version (UpdateExpression sets
    # status to :retired); second publishes the new version (UpdateExpression
    # sets status to :pub). Asserting on the UpdateExpression directly is
    # more reliable than reading ExpressionAttributeValues, since each item
    # carries multiple status values (one for the condition, one for the set).
    update_exprs = [item["Update"]["UpdateExpression"] for item in items]
    assert any(":retired" in expr for expr in update_exprs)
    assert any(":pub" in expr and ":retired" not in expr for expr in update_exprs)
    # Verify per-item key bindings.
    retire_item = next(item for item in items if ":retired" in item["Update"]["UpdateExpression"])
    publish_item = next(
        item
        for item in items
        if ":pub" in item["Update"]["UpdateExpression"] and ":retired" not in item["Update"]["UpdateExpression"]
    )
    assert retire_item["Update"]["ExpressionAttributeValues"][":retired"]["S"] == "retired"
    assert publish_item["Update"]["ExpressionAttributeValues"][":pub"]["S"] == "published"
