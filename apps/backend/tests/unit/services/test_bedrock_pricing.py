"""Tests for Bedrock pricing service."""

import os
from unittest.mock import patch, MagicMock

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from core.services.bedrock_pricing import (
    get_model_price,
    get_all_prices,
    FALLBACK_PRICING,
    _reset_cache_for_test,
)


class TestGetModelPrice:
    def setup_method(self):
        _reset_cache_for_test()

    def test_minimax_pricing(self):
        price = get_model_price("minimax.minimax-m2.5")
        assert price is not None
        assert price["input"] == pytest.approx(0.30 / 1e6)
        assert price["output"] == pytest.approx(1.20 / 1e6)

    def test_qwen3_pricing(self):
        # Qwen3 VL 235B (standard tier) — verified via `aws pricing
        # get-products --service-code AmazonBedrock` on 2026-04-09.
        price = get_model_price("qwen.qwen3-vl-235b-a22b")
        assert price is not None
        assert price["input"] == pytest.approx(0.53 / 1e6)
        assert price["output"] == pytest.approx(2.66 / 1e6)

    def test_unknown_model_returns_none(self):
        assert get_model_price("nonexistent-model") is None

    def test_all_fallback_models_have_four_fields(self):
        for model_id, pricing in FALLBACK_PRICING.items():
            for field in ("input", "output", "cache_read", "cache_write"):
                assert field in pricing, f"{model_id} missing {field}"

    def test_get_all_prices_returns_dict(self):
        prices = get_all_prices()
        assert isinstance(prices, dict)
        assert len(prices) > 0

    @patch("core.services.bedrock_pricing.boto3.client")
    def test_api_failure_uses_fallback(self, mock_boto):
        mock_client = MagicMock()
        mock_client.get_paginator.return_value.paginate.side_effect = Exception("API down")
        mock_boto.return_value = mock_client

        from core.services.bedrock_pricing import refresh_pricing_cache

        refresh_pricing_cache()

        price = get_model_price("qwen.qwen3-vl-235b-a22b")
        assert price is not None
