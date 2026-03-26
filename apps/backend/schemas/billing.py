"""Pydantic schemas for billing API endpoints."""

from enum import Enum
from pydantic import BaseModel


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
    lifetime_spend: float
    overage_enabled: bool
    overage_limit: float | None
    within_included: bool


class CheckoutRequest(BaseModel):
    tier: PlanTier


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


class PricingResponse(BaseModel):
    models: dict[str, ModelPriceResponse]
    markup: float
    tier_model: str
    subagent_model: str
