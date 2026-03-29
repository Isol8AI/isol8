"""Pydantic schemas for billing API endpoints."""

from enum import Enum
from pydantic import BaseModel, field_validator


class PlanTier(str, Enum):
    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class BillingAccountResponse(BaseModel):
    tier: str
    is_subscribed: bool
    current_spend: float
    included_budget: float
    budget_percent: float
    lifetime_spend: float
    overage_enabled: bool
    overage_limit: float | None
    within_included: bool


class CheckoutRequest(BaseModel):
    tier: PlanTier

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: PlanTier) -> PlanTier:
        if v == PlanTier.FREE:
            raise ValueError("Cannot checkout for free tier")
        return v


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class OverageToggleRequest(BaseModel):
    enabled: bool
    limit_dollars: float | None = None


class SpendLimitRequest(BaseModel):
    limit_dollars: float | None


class MemberUsage(BaseModel):
    user_id: str
    display_name: str | None = None
    email: str | None = None
    total_spend: float
    total_input_tokens: int
    total_output_tokens: int
    request_count: int


class UsageSummary(BaseModel):
    period: str
    total_spend: float
    total_input_tokens: int
    total_output_tokens: int
    total_cache_read_tokens: int
    total_cache_write_tokens: int
    request_count: int
    lifetime_spend: float
    by_member: list[MemberUsage] = []


class ModelPriceResponse(BaseModel):
    input: float
    output: float
    cache_read: float
    cache_write: float


class MyUsageResponse(BaseModel):
    period: str
    total_spend: float
    total_input_tokens: int
    total_output_tokens: int
    request_count: int


class PricingResponse(BaseModel):
    models: dict[str, ModelPriceResponse]
    markup: float
    tier_model: str
    subagent_model: str
