"""Bedrock Claude pricing constants - input/output/cache token rates per model.

Rates sourced from AWS Bedrock list price (us-east-1, 2026-04). Update
this file when AWS changes pricing; no other code should hardcode rates.
Per spec §6.3.

Microcents arithmetic is used everywhere in the credit ledger so we
avoid float drift on deduction. 1 dollar = 100 cents = 1,000,000
microcents. ``cost_microcents`` returns microcents directly; the
``get_all_rates`` helper returns USD-per-token floats for the
``/billing/pricing`` UI surface.
"""

from __future__ import annotations

from typing import TypedDict


class UnknownModelError(Exception):
    """Raised when a model id has no entry in the rate table.

    Deliberately NOT a KeyError subclass — pricing failures should never
    be silently swallowed by upstream `except KeyError:` clauses around
    dict access.
    """


class ModelRate(TypedDict):
    """Per-model token rates expressed in USD per million tokens.

    Used both by the cost helper (which collapses to microcents) and the
    pricing-UI endpoint (which surfaces raw USD per token).
    """

    input: float
    output: float
    cache_read: float
    cache_write: float


# Rates in USD per million tokens. Cache rates per Anthropic prompt-caching
# pricing on Bedrock: cache_write = 1.25× input rate, cache_read = 0.1× input
# rate. Reference: https://aws.amazon.com/bedrock/pricing/
_RATES: dict[str, ModelRate] = {
    "anthropic.claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_write": 3.75,
        "cache_read": 0.3,
    },
    "anthropic.claude-opus-4-7": {
        "input": 15.0,
        "output": 75.0,
        "cache_write": 18.75,
        "cache_read": 1.5,
    },
}


def get_rate(model_id: str) -> ModelRate:
    """Return the per-token rate entry for *model_id*.

    Raises:
        UnknownModelError: model_id has no rate entry.
    """
    try:
        return _RATES[model_id]
    except KeyError:
        raise UnknownModelError(model_id) from None


def get_all_rates() -> dict[str, ModelRate]:
    """Return all known model rates.

    Used by the ``/billing/pricing`` endpoint. Returned dict is a
    defensive copy so callers can't mutate the module-level constants.
    """
    return {model_id: dict(rate) for model_id, rate in _RATES.items()}


def cost_microcents(
    *,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> int:
    """Compute the un-marked-up cost in microcents for an inference call.

    Markup is applied separately by ``credit_ledger.deduct``. Cache tokens
    default to 0 so older callers that don't pass them keep working —
    new callers should pass them so cache-write surcharge and cache-read
    discount land in the ledger.

    Args:
        model_id: bare Bedrock model id (e.g. "anthropic.claude-sonnet-4-6").
            Pass without the "amazon-bedrock/" prefix.
        input_tokens: prompt tokens consumed.
        output_tokens: completion tokens produced.
        cache_read_tokens: tokens served from prompt cache (0.1× input rate).
        cache_write_tokens: tokens written to prompt cache (1.25× input rate).

    Returns:
        Integer microcents.

    Raises:
        UnknownModelError: model_id has no rate entry.
    """
    rate = get_rate(model_id)
    return (
        int(input_tokens * rate["input"])
        + int(output_tokens * rate["output"])
        + int(cache_read_tokens * rate["cache_read"])
        + int(cache_write_tokens * rate["cache_write"])
    )
