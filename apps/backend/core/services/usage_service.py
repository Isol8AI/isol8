"""Usage tracking — counter writes for analytics. Billing flows through credit_ledger."""

import logging
from datetime import datetime, timezone

from core.observability.metrics import put_metric
from core.repositories import usage_repo
from core.services.bedrock_pricing import get_model_price

logger = logging.getLogger(__name__)


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
    """Record a single LLM usage event for analytics.

    Writes per-period + lifetime + per-member counters to DynamoDB. The
    credit ledger (core/services/credit_ledger.py) handles authoritative
    billing for card-3 (bedrock_claude) users; this is a counter-only
    side-write surfaced via the admin /usage endpoint.
    """
    pricing = get_model_price(model)
    if pricing is None:
        put_metric("billing.pricing.missing_model")
        logger.warning("No pricing for model %s — skipping for owner %s", model, owner_id)
        return

    raw_cost_usd = (
        input_tokens * pricing["input"]
        + output_tokens * pricing["output"]
        + cache_read * pricing["cache_read"]
        + cache_write * pricing["cache_write"]
    )
    spend_microdollars = int(raw_cost_usd * 1_000_000)
    if spend_microdollars <= 0:
        return

    period = _current_period()

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


async def get_usage_summary(owner_id: str) -> dict:
    """Get current period usage summary for the admin /usage endpoint."""
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
