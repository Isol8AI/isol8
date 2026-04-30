"""Tests for marketplace_search."""

import os

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from unittest.mock import MagicMock, patch  # noqa: E402

import pytest  # noqa: E402

from core.services import marketplace_search  # noqa: E402


@pytest.mark.asyncio
@patch("core.services.marketplace_search._search_index_table")
async def test_search_ranks_by_tag_match_count_then_recency(mock_table):
    items = [
        {"listing_id": "a", "tags": ["sales", "outreach"], "published_at": "2026-04-29T10:00:00Z"},
        {"listing_id": "b", "tags": ["sales"], "published_at": "2026-04-30T10:00:00Z"},
        {"listing_id": "c", "tags": ["outreach"], "published_at": "2026-04-30T12:00:00Z"},
        {"listing_id": "d", "tags": ["unrelated"], "published_at": "2026-04-30T13:00:00Z"},
    ]
    mock_table.return_value.scan = MagicMock(return_value={"Items": items, "Count": len(items)})
    results = await marketplace_search.search(query_tags=["sales", "outreach"], limit=10)
    # Ranking: a (2 matches) → c (1 match, newer) → b (1 match, older). d filtered.
    assert [r["listing_id"] for r in results] == ["a", "c", "b"]


@pytest.mark.asyncio
@patch("core.services.marketplace_search._search_index_table")
async def test_browse_returns_recent_published(mock_table):
    items = [
        {"listing_id": "a", "published_at": "2026-04-30T13:00:00Z"},
        {"listing_id": "b", "published_at": "2026-04-29T10:00:00Z"},
    ]
    mock_table.return_value.scan = MagicMock(return_value={"Items": items, "Count": 2})
    results = await marketplace_search.browse(limit=10)
    assert [r["listing_id"] for r in results] == ["a", "b"]


@pytest.mark.asyncio
@patch("core.services.marketplace_search._search_index_table")
async def test_search_with_empty_query_falls_back_to_browse(mock_table):
    items = [{"listing_id": "x", "tags": ["a"], "published_at": "2026-04-30T10:00:00Z"}]
    mock_table.return_value.scan = MagicMock(return_value={"Items": items, "Count": 1})
    results = await marketplace_search.search(query_tags=[], limit=10)
    assert results == items
