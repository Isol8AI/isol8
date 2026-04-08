"""Tests for billing Pydantic schemas."""

import pytest

from schemas.billing import (
    BillingAccountResponse,
    CheckoutRequest,
    UsageSummary,
    MemberUsage,
    PricingResponse,
    ModelPriceResponse,
    OverageToggleRequest,
    PlanTier,
)


class TestBillingSchemas:
    """Test billing schema validation."""

    def test_billing_account_response(self):
        """Should serialize billing account data."""
        resp = BillingAccountResponse(
            tier="starter",
            is_subscribed=True,
            current_spend=11.42,
            included_budget=15.00,
            budget_percent=76.1,
            lifetime_spend=50.0,
            overage_enabled=False,
            overage_limit=None,
            within_included=True,
        )
        data = resp.model_dump()
        assert data["tier"] == "starter"
        assert data["included_budget"] == 15.00
        assert data["current_spend"] == 11.42
        assert data["budget_percent"] == 76.1
        assert data["within_included"] is True

    def test_checkout_request_validation(self):
        """Should validate tier is one of allowed values."""
        req = CheckoutRequest(tier="starter")
        assert req.tier == PlanTier.STARTER

    def test_checkout_request_invalid_tier(self):
        """Should reject invalid tier."""
        with pytest.raises(ValueError):
            CheckoutRequest(tier="diamond")

    def test_usage_summary(self):
        """Should serialize usage summary."""
        resp = UsageSummary(
            period="2026-03",
            total_spend=11.42,
            total_input_tokens=50000,
            total_output_tokens=25000,
            total_cache_read_tokens=1000,
            total_cache_write_tokens=500,
            request_count=847,
            lifetime_spend=50.0,
            by_member=[
                MemberUsage(
                    user_id="user_1",
                    display_name="Test User",
                    email="test@example.com",
                    total_spend=5.0,
                    total_input_tokens=25000,
                    total_output_tokens=12000,
                    request_count=400,
                ),
            ],
        )
        data = resp.model_dump()
        assert data["request_count"] == 847
        assert len(data["by_member"]) == 1
        assert data["by_member"][0]["display_name"] == "Test User"

    def test_pricing_response(self):
        """Should serialize pricing data."""
        resp = PricingResponse(
            models={
                "minimax.minimax-m2.5": ModelPriceResponse(
                    input=0.42e-6,
                    output=1.68e-6,
                    cache_read=0.0,
                    cache_write=0.0,
                ),
            },
            markup=1.4,
            tier_model="minimax.minimax-m2.5",
            subagent_model="minimax.minimax-m2.5",
        )
        data = resp.model_dump()
        assert data["markup"] == 1.4
        assert "minimax.minimax-m2.5" in data["models"]

    def test_overage_toggle_request(self):
        """Should accept overage toggle with optional limit."""
        req = OverageToggleRequest(enabled=True, limit_dollars=50.0)
        assert req.enabled is True
        assert req.limit_dollars == 50.0

        req_no_limit = OverageToggleRequest(enabled=False)
        assert req_no_limit.limit_dollars is None
