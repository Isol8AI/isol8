"""Unit tests for Bedrock Claude pricing constants and cost calc."""

import pytest

from core.billing.bedrock_pricing import (
    UnknownModelError,
    cost_microcents,
)


class TestCostMicrocents:
    def test_sonnet_4_6_cost(self):
        # Sonnet 4.6: $3 / MTok input, $15 / MTok output (Bedrock list price).
        # 1 MTok = 1,000,000 tokens. $1 = 100 cents = 1,000,000 microcents.
        # 1000 input + 500 output should cost:
        # (1000 / 1_000_000) * $3 = $0.003 = 3000 microcents (input)
        # (500 / 1_000_000) * $15 = $0.0075 = 7500 microcents (output)
        # Total: 10500 microcents
        result = cost_microcents(
            model_id="anthropic.claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
        )
        assert result == 10_500

    def test_opus_4_7_cost(self):
        # Opus 4.7: $15 / MTok input, $75 / MTok output.
        # 1000 input + 500 output:
        # (1000 / 1_000_000) * $15 = $0.015 = 15_000 microcents (input)
        # (500 / 1_000_000) * $75 = $0.0375 = 37_500 microcents (output)
        # Total: 52_500 microcents
        result = cost_microcents(
            model_id="anthropic.claude-opus-4-7",
            input_tokens=1000,
            output_tokens=500,
        )
        assert result == 52_500

    def test_unknown_model_raises(self):
        with pytest.raises(UnknownModelError) as exc:
            cost_microcents(model_id="anthropic.claude-fake-99", input_tokens=100, output_tokens=100)
        assert "anthropic.claude-fake-99" in str(exc.value)

    def test_zero_tokens_zero_cost(self):
        result = cost_microcents(
            model_id="anthropic.claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
        )
        assert result == 0

    def test_cost_is_integer(self):
        """Microcents are integers - no float drift in the deduct path."""
        result = cost_microcents(
            model_id="anthropic.claude-sonnet-4-6",
            input_tokens=1234,
            output_tokens=5678,
        )
        assert isinstance(result, int)
