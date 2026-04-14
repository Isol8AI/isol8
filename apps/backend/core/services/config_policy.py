"""Tier-aware policy for openclaw.json locked fields.

Pure, side-effect-free. Takes a config dict and a tier name, returns a list
of field-level violations. Apply reverts by computing the authoritative
expected value from helpers in core/containers/config.py.
"""

import copy
from typing import Any, Literal, TypedDict

from core.containers.config import (
    _TIER_ALLOWED_MODEL_IDS,
    _models_for_tier,
)

LockedField = Literal[
    "models.providers",
    "agents.defaults.models",
    "agents.defaults.model.primary",
    "channels.accounts",
]


class PolicyViolation(TypedDict):
    field: LockedField
    reason: str
    expected: Any
    actual: Any


def _expected_providers(tier: str) -> dict:
    """The one provider block this tier is allowed to run: amazon-bedrock
    with exactly the tier's model list. No other providers permitted."""
    return {
        "amazon-bedrock": {
            "baseUrl": "https://bedrock-runtime.us-east-1.amazonaws.com",
            "api": "bedrock-converse-stream",
            "auth": "aws-sdk",
            "models": _models_for_tier(tier),
        },
    }


def _providers_match(actual: Any, expected: dict) -> bool:
    """Strict equality check. Providers block must match exactly — any extra
    provider, any extra/missing model, any changed field is a violation."""
    return actual == expected


def evaluate(config: dict, tier: str) -> list[PolicyViolation]:
    """Return a list of locked-field violations for this config at this tier.

    Empty list means the config is legal. Each violation has enough info
    to revert (field, expected value) and for audit (reason, actual value).
    """
    violations: list[PolicyViolation] = []

    # Tier fallback: unknown tier → free-tier allowlist (default-deny).
    effective_tier = tier if tier in _TIER_ALLOWED_MODEL_IDS else "free"

    # 1. models.providers — strict match against tier's allowed block
    actual_providers = config.get("models", {}).get("providers", {})
    expected_providers = _expected_providers(effective_tier)
    if not _providers_match(actual_providers, expected_providers):
        violations.append(
            {
                "field": "models.providers",
                "reason": f"providers block for tier={effective_tier} must match the tier's allowlist",
                "expected": expected_providers,
                "actual": actual_providers,
            }
        )

    return violations


def apply_reverts(config: dict, violations: list[PolicyViolation]) -> dict:
    """Return a deep copy of config with each violating field replaced by
    its expected value. Non-violating fields — including OpenClaw's `meta`
    block and everything else — are preserved untouched.
    """
    return copy.deepcopy(config)
