"""
Bedrock model pricing — AWS Pricing API primary, hardcoded fallback.

Prices are per-token in USD. AWS Pricing API is the primary source; fallback dict used when API is unavailable.
"""

import logging
import time
from typing import TypedDict

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 86400  # 24 hours
_cached_pricing: dict[str, "ModelPrice"] = {}
_cache_expires_at: float = 0


class ModelPrice(TypedDict):
    input: float
    output: float
    cache_read: float
    cache_write: float


# Per-token USD. Source: aws.amazon.com/bedrock/pricing/ — verified 2026-04-08
FALLBACK_PRICING: dict[str, ModelPrice] = {
    "minimax.minimax-m2.5": {
        "input": 0.30 / 1e6,
        "output": 1.20 / 1e6,
        "cache_read": 0.0,
        "cache_write": 0.0,
    },
    "us.amazon.nova-lite-v1:0": {
        "input": 0.06 / 1e6,
        "output": 0.24 / 1e6,
        "cache_read": 0.006 / 1e6,
        "cache_write": 0.06 / 1e6,
    },
    "us.amazon.nova-pro-v1:0": {
        "input": 0.80 / 1e6,
        "output": 3.20 / 1e6,
        "cache_read": 0.08 / 1e6,
        "cache_write": 0.80 / 1e6,
    },
    "us.anthropic.claude-haiku-4-5-20251001-v1:0": {
        "input": 1.0 / 1e6,
        "output": 5.0 / 1e6,
        "cache_read": 0.1 / 1e6,
        "cache_write": 1.25 / 1e6,
    },
    "us.meta.llama3-3-70b-instruct-v1:0": {
        "input": 0.72 / 1e6,
        "output": 0.72 / 1e6,
        "cache_read": 0.0,
        "cache_write": 0.0,
    },
    "us.deepseek.r1-v1:0": {
        "input": 1.35 / 1e6,
        "output": 5.40 / 1e6,
        "cache_read": 0.135 / 1e6,
        "cache_write": 1.35 / 1e6,
    },
    "us.mistral.mistral-large-2512-v1:0": {
        "input": 2.0 / 1e6,
        "output": 6.0 / 1e6,
        "cache_read": 0.2 / 1e6,
        "cache_write": 2.0 / 1e6,
    },
    "us.qwen.qwen3-235b-a22b-2507-v1:0": {
        "input": 0.80 / 1e6,
        "output": 2.00 / 1e6,
        "cache_read": 0.0,
        "cache_write": 0.0,
    },
    "us.qwen.qwen3-32b-v1:0": {
        "input": 0.15 / 1e6,
        "output": 0.60 / 1e6,
        "cache_read": 0.0,
        "cache_write": 0.0,
    },
}


def _reset_cache_for_test() -> None:
    global _cached_pricing, _cache_expires_at
    _cached_pricing = {}
    _cache_expires_at = 0


def refresh_pricing_cache(region: str = "us-east-1") -> None:
    """Refresh pricing from AWS Pricing API. Falls back to hardcoded on failure."""
    global _cached_pricing, _cache_expires_at
    try:
        client = boto3.client("pricing", region_name="us-east-1")
        import json as json_mod

        updated: dict[str, ModelPrice] = dict(FALLBACK_PRICING)
        for page in client.get_paginator("get_products").paginate(
            ServiceCode="AmazonBedrock",
            Filters=[{"Type": "TERM_MATCH", "Field": "regionCode", "Value": region}],
        ):
            for price_str in page.get("PriceList", []):
                try:
                    _parse_price_item(json_mod.loads(price_str), updated)
                except Exception:
                    continue
        _cached_pricing = updated
        _cache_expires_at = time.time() + _CACHE_TTL_SECONDS
        logger.info("Refreshed Bedrock pricing cache: %d models", len(updated))
    except (ClientError, Exception) as e:
        logger.warning("Failed to refresh Bedrock pricing (using fallback): %s", e)
        if not _cached_pricing:
            _cached_pricing = dict(FALLBACK_PRICING)
            _cache_expires_at = time.time() + _CACHE_TTL_SECONDS


def _parse_price_item(price_item: dict, updated: dict[str, ModelPrice]) -> None:
    """Parse a single AWS Pricing API response item."""
    try:
        attrs = price_item.get("product", {}).get("attributes", {})
        model_id = attrs.get("model", "")
        inference_type = attrs.get("inferenceType", "").lower()
        if not model_id or "token" not in attrs.get("usagetype", "").lower():
            return
        terms = price_item.get("terms", {}).get("OnDemand", {})
        for term in terms.values():
            for dim in term.get("priceDimensions", {}).values():
                if dim.get("unit") != "1K tokens":
                    continue
                price_str = dim.get("pricePerUnit", {}).get("USD", "0")
                price_per_1k = float(price_str)
                price_per_token = price_per_1k / 1000
                if model_id not in updated:
                    updated[model_id] = ModelPrice(
                        input=0,
                        output=0,
                        cache_read=0,
                        cache_write=0,
                    )
                if "input" in inference_type:
                    updated[model_id]["input"] = price_per_token
                elif "output" in inference_type:
                    updated[model_id]["output"] = price_per_token
    except Exception:
        pass


def get_model_price(model_id: str) -> ModelPrice | None:
    """Get per-token pricing for a model. Returns None if unknown."""
    if not _cached_pricing or time.time() > _cache_expires_at:
        refresh_pricing_cache()
    return _cached_pricing.get(model_id)


def get_all_prices() -> dict[str, ModelPrice]:
    """Get all cached model prices."""
    if not _cached_pricing:
        get_model_price("")
    return dict(_cached_pricing)
