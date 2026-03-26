"""Usage tracking — records LLM usage, checks budgets/overage, reports to Stripe."""

import logging
import time
from datetime import datetime, timezone

import stripe

from core.config import settings, TIER_CONFIG
from core.repositories import billing_repo, usage_repo
from core.services.bedrock_pricing import get_model_price

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY
_MARKUP = settings.BILLING_MARKUP


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def record_usage(
    owner_id: str,
    user_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read: int,
    cache_write: int,
) -> None:
    """Record a single LLM usage event."""
    pricing = get_model_price(model)
    if pricing is None:
        logger.warning("No pricing for model %s — skipping for owner %s", model, owner_id)
        return

    raw_cost = (
        input_tokens * pricing["input"]
        + output_tokens * pricing["output"]
        + cache_read * pricing["cache_read"]
        + cache_write * pricing["cache_write"]
    )
    billable_cost = raw_cost * _MARKUP
    spend_microdollars = int(billable_cost * 1_000_000)
    if spend_microdollars <= 0:
        return

    period = _current_period()

    # Triple-write: monthly + lifetime + member
    await usage_repo.increment(
        owner_id,
        period,
        spend_microdollars,
        input_tokens,
        output_tokens,
        cache_read,
        cache_write,
    )
    await usage_repo.increment(
        owner_id,
        "lifetime",
        spend_microdollars,
        input_tokens,
        output_tokens,
        cache_read,
        cache_write,
    )
    await usage_repo.increment(
        owner_id,
        f"member:{user_id}:{period}",
        spend_microdollars,
        input_tokens,
        output_tokens,
        cache_read,
        cache_write,
    )

    # Report overage to Stripe (only if over included budget and overage enabled)
    try:
        account = await billing_repo.get_by_owner_id(owner_id)
        if not account:
            return

        tier = account.get("plan_tier", "free")
        tier_config = TIER_CONFIG.get(tier, TIER_CONFIG["free"])
        included_budget = tier_config["included_budget_microdollars"]
        budget_type = tier_config["budget_type"]

        if budget_type == "lifetime":
            current = await usage_repo.get_period_usage(owner_id, "lifetime")
        else:
            current = await usage_repo.get_period_usage(owner_id, period)

        current_spend = current["total_spend_microdollars"] if current else 0

        if (
            current_spend > included_budget
            and account.get("overage_enabled")
            and account.get("stripe_customer_id")
            and settings.STRIPE_METER_ID
        ):
            overage_amount = min(spend_microdollars, current_spend - included_budget)
            if overage_amount > 0:
                stripe.billing.MeterEvent.create(
                    event_name="llm_usage",
                    payload={
                        "stripe_customer_id": account["stripe_customer_id"],
                        "value": str(overage_amount),
                    },
                    identifier=f"{owner_id}_{int(time.time() * 1000)}",
                )
    except Exception as e:
        logger.warning("Failed to report usage to Stripe for %s: %s", owner_id, e)


async def check_budget(owner_id: str) -> dict:
    """Check if owner is within their budget.

    Returns dict with: allowed, within_included, overage_available,
    overage_enabled, current_spend, included_budget, is_subscribed, tier
    """
    account = await billing_repo.get_by_owner_id(owner_id)
    tier = account.get("plan_tier", "free") if account else "free"
    tier_config = TIER_CONFIG.get(tier, TIER_CONFIG["free"])
    included_budget = tier_config["included_budget_microdollars"]
    budget_type = tier_config["budget_type"]
    is_subscribed = bool(account and account.get("stripe_subscription_id"))

    if budget_type == "lifetime":
        usage = await usage_repo.get_period_usage(owner_id, "lifetime")
    else:
        usage = await usage_repo.get_period_usage(owner_id, _current_period())

    current_spend_micro = usage["total_spend_microdollars"] if usage else 0
    within_included = current_spend_micro < included_budget
    overage_enabled = bool(account and account.get("overage_enabled"))

    # Check overage limit if set
    overage_limit = account.get("overage_limit") if account else None
    if overage_enabled and overage_limit is not None:
        overage_spend = max(0, current_spend_micro - included_budget)
        if overage_spend >= int(overage_limit):
            overage_enabled = False

    allowed = within_included or overage_enabled

    return {
        "allowed": allowed,
        "within_included": within_included,
        "overage_available": tier != "free" and not within_included,
        "overage_enabled": overage_enabled,
        "current_spend": current_spend_micro / 1_000_000,
        "included_budget": included_budget / 1_000_000,
        "is_subscribed": is_subscribed,
        "tier": tier,
    }


async def get_usage_summary(owner_id: str) -> dict:
    """Get current period usage summary."""
    period = _current_period()
    usage = await usage_repo.get_period_usage(owner_id, period)
    lifetime = await usage_repo.get_period_usage(owner_id, "lifetime")

    empty = {
        "total_spend_microdollars": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_cache_read_tokens": 0,
        "total_cache_write_tokens": 0,
        "request_count": 0,
    }
    usage = usage or empty

    return {
        "period": period,
        "total_spend": usage["total_spend_microdollars"] / 1_000_000,
        "total_input_tokens": usage["total_input_tokens"],
        "total_output_tokens": usage["total_output_tokens"],
        "total_cache_read_tokens": usage["total_cache_read_tokens"],
        "total_cache_write_tokens": usage["total_cache_write_tokens"],
        "request_count": usage["request_count"],
        "lifetime_spend": (lifetime["total_spend_microdollars"] if lifetime else 0) / 1_000_000,
    }
