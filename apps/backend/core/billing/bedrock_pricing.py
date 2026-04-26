"""Bedrock Claude pricing constants - input/output token rates per model.

Rates sourced from AWS Bedrock list price (us-east-1, 2026-04). Update
this file when AWS changes pricing; no other code should hardcode rates.
Per spec §6.3.

Microcents arithmetic is used everywhere in the credit ledger so we
avoid float drift on deduction. 1 dollar = 100 cents = 1,000,000
microcents.
"""

from __future__ import annotations


class UnknownModelError(KeyError):
    """Raised when a model id has no entry in the rate table."""


# (input_per_mtok_usd, output_per_mtok_usd)
_RATES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "anthropic.claude-sonnet-4-6": (3.0, 15.0),
    "anthropic.claude-opus-4-7": (15.0, 75.0),
}


def cost_microcents(*, model_id: str, input_tokens: int, output_tokens: int) -> int:
    """Compute the un-marked-up cost in microcents for an inference call.

    Args:
        model_id: bare Bedrock model id (e.g. "anthropic.claude-sonnet-4-6").
            Pass without the "amazon-bedrock/" prefix.
        input_tokens: prompt tokens consumed.
        output_tokens: completion tokens produced.

    Returns:
        Integer microcents. Markup is applied separately by credit_ledger.deduct.

    Raises:
        UnknownModelError: model_id has no rate entry.
    """
    try:
        in_rate, out_rate = _RATES_USD_PER_MTOK[model_id]
    except KeyError:
        raise UnknownModelError(model_id) from None

    in_microcents = int(input_tokens * in_rate)
    out_microcents = int(output_tokens * out_rate)
    return in_microcents + out_microcents
