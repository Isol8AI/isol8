"""Tests for ToolPricing model."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from models.billing import ToolPricing


class TestToolPricing:
    @pytest.mark.asyncio
    async def test_tool_pricing_creation(self, db_session):
        pricing = ToolPricing(
            id=uuid.uuid4(),
            tool_id="perplexity_search",
            display_name="Web Search (Perplexity)",
            unit="request",
            cost_per_unit=Decimal("0.005"),
            is_active=True,
        )
        db_session.add(pricing)
        await db_session.commit()

        result = await db_session.execute(select(ToolPricing).where(ToolPricing.tool_id == "perplexity_search"))
        saved = result.scalar_one()
        assert saved.tool_id == "perplexity_search"
        assert saved.display_name == "Web Search (Perplexity)"
        assert saved.unit == "request"
        assert saved.cost_per_unit == Decimal("0.005")
        assert saved.is_active is True
        assert saved.created_at is not None
        assert repr(saved) == "<ToolPricing(tool_id=perplexity_search, active=True)>"

    @pytest.mark.asyncio
    async def test_tool_pricing_defaults(self, db_session):
        pricing = ToolPricing(
            id=uuid.uuid4(),
            tool_id="edge_tts",
            display_name="Text-to-Speech (Edge)",
            unit="request",
            cost_per_unit=Decimal("0"),
        )
        db_session.add(pricing)
        await db_session.commit()
        assert pricing.is_active is True
        assert pricing.effective_from is not None
