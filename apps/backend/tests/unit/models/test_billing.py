"""Tests for billing database models."""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from models.billing import ModelPricing, BillingAccount, UsageEvent, UsageDaily


class TestModelPricing:
    @pytest.mark.asyncio
    async def test_create_model_pricing(self, db_session):
        pricing = ModelPricing(
            model_id="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            display_name="Claude 3.5 Sonnet",
            input_cost_per_token=Decimal("0.000003"),
            output_cost_per_token=Decimal("0.000015"),
        )
        db_session.add(pricing)
        await db_session.commit()

        result = await db_session.execute(
            select(ModelPricing).where(ModelPricing.model_id == "us.anthropic.claude-3-5-sonnet-20241022-v2:0")
        )
        saved = result.scalar_one()
        assert saved.display_name == "Claude 3.5 Sonnet"
        assert saved.input_cost_per_token == Decimal("0.000003")
        assert saved.output_cost_per_token == Decimal("0.000015")
        assert saved.is_active is True
        assert saved.created_at is not None
        assert saved.id is not None

    @pytest.mark.asyncio
    async def test_model_pricing_defaults(self, db_session):
        pricing = ModelPricing(
            model_id="us.meta.llama3-3-70b-instruct-v1:0",
            display_name="Llama 3.3 70B",
            input_cost_per_token=Decimal("0.00000099"),
            output_cost_per_token=Decimal("0.00000099"),
        )
        db_session.add(pricing)
        await db_session.commit()
        assert pricing.is_active is True
        assert pricing.effective_from is not None


class TestBillingAccount:
    @pytest.mark.asyncio
    async def test_create_personal_billing_account(self, db_session):
        account = BillingAccount(
            clerk_user_id="user_test_billing_123",
            stripe_customer_id="cus_test_abc",
        )
        db_session.add(account)
        await db_session.commit()

        result = await db_session.execute(
            select(BillingAccount).where(BillingAccount.clerk_user_id == "user_test_billing_123")
        )
        saved = result.scalar_one()
        assert saved.stripe_customer_id == "cus_test_abc"
        assert saved.plan_tier == "free"
        assert saved.markup_multiplier == Decimal("1.400")
        assert saved.clerk_org_id is None

    @pytest.mark.asyncio
    async def test_create_org_billing_account(self, db_session):
        account = BillingAccount(
            clerk_org_id="org_test_456",
            stripe_customer_id="cus_test_def",
        )
        db_session.add(account)
        await db_session.commit()

        result = await db_session.execute(select(BillingAccount).where(BillingAccount.clerk_org_id == "org_test_456"))
        saved = result.scalar_one()
        assert saved.clerk_user_id is None
        assert saved.plan_tier == "free"


class TestUsageEvent:
    @pytest.mark.asyncio
    async def test_create_usage_event(self, db_session):
        account = BillingAccount(
            clerk_user_id="user_usage_test",
            stripe_customer_id="cus_usage_test",
        )
        db_session.add(account)
        await db_session.commit()

        event = UsageEvent(
            billing_account_id=account.id,
            clerk_user_id="user_usage_test",
            model_id="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            input_tokens=1200,
            output_tokens=800,
            input_cost=Decimal("0.0036"),
            output_cost=Decimal("0.012"),
            total_cost=Decimal("0.0156"),
            billable_amount=Decimal("0.02184"),
            source="chat",
            month_partition="2026-02",
        )
        db_session.add(event)
        await db_session.commit()

        result = await db_session.execute(select(UsageEvent).where(UsageEvent.billing_account_id == account.id))
        saved = result.scalar_one()
        assert saved.input_tokens == 1200
        assert saved.output_tokens == 800
        assert saved.source == "chat"
        assert saved.month_partition == "2026-02"

    @pytest.mark.asyncio
    async def test_usage_event_agent_source(self, db_session):
        account = BillingAccount(
            clerk_user_id="user_agent_usage",
            stripe_customer_id="cus_agent_usage",
        )
        db_session.add(account)
        await db_session.commit()

        event = UsageEvent(
            billing_account_id=account.id,
            clerk_user_id="user_agent_usage",
            model_id="us.meta.llama3-3-70b-instruct-v1:0",
            input_tokens=500,
            output_tokens=300,
            input_cost=Decimal("0.000495"),
            output_cost=Decimal("0.000297"),
            total_cost=Decimal("0.000792"),
            billable_amount=Decimal("0.001109"),
            source="agent",
            agent_id="luna",
            month_partition="2026-02",
        )
        db_session.add(event)
        await db_session.commit()
        assert event.agent_id == "luna"
        assert event.source == "agent"

    @pytest.mark.asyncio
    async def test_usage_event_tool_fields(self, db_session):
        """UsageEvent supports tool usage tracking fields."""
        account = BillingAccount(
            clerk_user_id="user_tool_fields_test",
            stripe_customer_id="cus_tool_fields",
        )
        db_session.add(account)
        await db_session.commit()

        event = UsageEvent(
            billing_account_id=account.id,
            clerk_user_id="user_tool_fields_test",
            model_id="perplexity_search",
            input_tokens=0,
            output_tokens=0,
            input_cost=Decimal("0"),
            output_cost=Decimal("0"),
            total_cost=Decimal("0.005"),
            billable_amount=Decimal("0.005"),
            source="tool",
            usage_type="tool",
            tool_id="perplexity_search",
            quantity=1,
            month_partition="2026-03",
        )
        db_session.add(event)
        await db_session.commit()

        result = await db_session.execute(select(UsageEvent).where(UsageEvent.tool_id == "perplexity_search"))
        saved = result.scalar_one()
        assert saved.usage_type == "tool"
        assert saved.tool_id == "perplexity_search"
        assert saved.quantity == 1

    @pytest.mark.asyncio
    async def test_usage_event_defaults_to_llm(self, db_session):
        """UsageEvent usage_type defaults to 'llm' when not specified."""
        account = BillingAccount(
            clerk_user_id="user_llm_default_test",
            stripe_customer_id="cus_llm_default",
        )
        db_session.add(account)
        await db_session.commit()

        event = UsageEvent(
            billing_account_id=account.id,
            clerk_user_id="user_llm_default_test",
            model_id="anthropic.claude-opus-4-6",
            input_tokens=100,
            output_tokens=50,
            input_cost=Decimal("0.0003"),
            output_cost=Decimal("0.00075"),
            total_cost=Decimal("0.00105"),
            billable_amount=Decimal("0.00147"),
            source="agent",
            month_partition="2026-03",
        )
        db_session.add(event)
        await db_session.commit()

        result = await db_session.execute(select(UsageEvent).where(UsageEvent.clerk_user_id == "user_llm_default_test"))
        saved = result.scalar_one()
        assert saved.usage_type == "llm"
        assert saved.tool_id is None
        assert saved.quantity is None


class TestUsageDaily:
    @pytest.mark.asyncio
    async def test_create_usage_daily(self, db_session):
        account = BillingAccount(
            clerk_user_id="user_daily_test",
            stripe_customer_id="cus_daily_test",
        )
        db_session.add(account)
        await db_session.commit()

        daily = UsageDaily(
            billing_account_id=account.id,
            date=date(2026, 2, 13),
            model_id="us.anthropic.claude-3-5-sonnet-20241022-v2:0",
            source="chat",
            total_input_tokens=50000,
            total_output_tokens=30000,
            total_cost=Decimal("0.60"),
            total_billable=Decimal("0.84"),
            request_count=25,
        )
        db_session.add(daily)
        await db_session.commit()

        result = await db_session.execute(select(UsageDaily).where(UsageDaily.billing_account_id == account.id))
        saved = result.scalar_one()
        assert saved.total_input_tokens == 50000
        assert saved.request_count == 25

    @pytest.mark.asyncio
    async def test_usage_daily_tool_type(self, db_session):
        """UsageDaily supports tool usage_type."""
        account = BillingAccount(
            clerk_user_id="user_daily_tool_test",
            stripe_customer_id="cus_daily_tool",
        )
        db_session.add(account)
        await db_session.commit()

        daily = UsageDaily(
            billing_account_id=account.id,
            date=date(2026, 3, 5),
            model_id="perplexity_search",
            source="tool",
            usage_type="tool",
            request_count=10,
        )
        db_session.add(daily)
        await db_session.commit()

        result = await db_session.execute(select(UsageDaily).where(UsageDaily.usage_type == "tool"))
        saved = result.scalar_one()
        assert saved.usage_type == "tool"
        assert saved.source == "tool"
