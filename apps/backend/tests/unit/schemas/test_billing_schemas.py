"""Tests for billing Pydantic schemas — flat-fee model."""

from schemas.billing import (
    BillingAccountResponse,
    UsageSummary,
    MemberUsage,
    PricingResponse,
    ModelPriceResponse,
)


class TestBillingSchemas:
    def test_billing_account_response(self):
        resp = BillingAccountResponse(
            is_subscribed=True,
            current_spend=11.42,
            lifetime_spend=50.0,
            subscription_status="active",
            trial_end=None,
        )
        data = resp.model_dump()
        assert data["is_subscribed"] is True
        assert data["subscription_status"] == "active"
        assert data["current_spend"] == 11.42

    def test_billing_account_response_pre_signup(self):
        """Empty defaults for users with no billing row yet."""
        resp = BillingAccountResponse(
            is_subscribed=False,
            current_spend=0.0,
            lifetime_spend=0.0,
        )
        data = resp.model_dump()
        assert data["subscription_status"] is None
        assert data["trial_end"] is None

    def test_usage_summary(self):
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
        resp = PricingResponse(
            models={
                "anthropic.claude-sonnet-4-6": ModelPriceResponse(
                    input=3.0e-6,
                    output=15.0e-6,
                    cache_read=0.3e-6,
                    cache_write=3.75e-6,
                ),
            },
        )
        data = resp.model_dump()
        assert "anthropic.claude-sonnet-4-6" in data["models"]
        assert data["models"]["anthropic.claude-sonnet-4-6"]["input"] == 3.0e-6
