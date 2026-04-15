"""Tier-aware policy for openclaw.json locked fields.

Pure, side-effect-free. Takes a config dict and a tier name, returns a list
of field-level violations. Apply reverts by computing the authoritative
expected value from helpers in core/containers/config.py.
"""

import copy
from typing import Any, Literal, TypedDict

from core.config import TIER_CONFIG
from core.containers.config import (
    _TIER_ALLOWED_MODEL_IDS,
    _agent_models_for_tier,
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
    # NOTE: hardcodes us-east-1 because Isol8 is single-region (see CLAUDE.md).
    # If we go multi-region, thread `region` through from caller.
    return {
        "amazon-bedrock": {
            "baseUrl": "https://bedrock-runtime.us-east-1.amazonaws.com",
            "api": "bedrock-converse-stream",
            "auth": "aws-sdk",
            "models": _models_for_tier(tier),
        },
    }


def _providers_match(actual: Any, expected: dict) -> bool:
    """Strict equality check against a canonical form. Providers block must
    match exactly — any extra provider, any extra/missing model, any changed
    field is a violation.

    Canonicalizes before comparison so list ordering of ``models`` does not
    matter: provider top-level keys compared as sets, per-provider non-``models``
    fields compared as dicts, ``models`` compared as ``{id: model}`` maps.
    Each model's full content is still strictly checked — only the list-order
    invariant is loosened.
    """
    if not isinstance(actual, dict):
        return False

    if set(actual.keys()) != set(expected.keys()):
        return False

    for provider, expected_cfg in expected.items():
        actual_cfg = actual.get(provider)
        if not isinstance(actual_cfg, dict) or not isinstance(expected_cfg, dict):
            return False

        # Non-models keys must match exactly (baseUrl, api, auth, ...).
        actual_non_models = {k: v for k, v in actual_cfg.items() if k != "models"}
        expected_non_models = {k: v for k, v in expected_cfg.items() if k != "models"}
        if actual_non_models != expected_non_models:
            return False

        # Models list: compare as {id: model} dict to ignore ordering but keep
        # content-strict comparison on every model entry.
        actual_models = actual_cfg.get("models", [])
        expected_models = expected_cfg.get("models", [])
        if not isinstance(actual_models, list) or not isinstance(expected_models, list):
            return False
        try:
            actual_by_id = {m["id"]: m for m in actual_models}
            expected_by_id = {m["id"]: m for m in expected_models}
        except (TypeError, KeyError):
            return False
        if actual_by_id != expected_by_id:
            return False

    return True


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

    # 2. agents.defaults.model.primary — must be in tier allowlist
    primary = config.get("agents", {}).get("defaults", {}).get("model", {}).get("primary", "")
    bare_primary = primary.removeprefix("amazon-bedrock/")
    if bare_primary not in _TIER_ALLOWED_MODEL_IDS[effective_tier]:
        expected_primary = (
            f"amazon-bedrock/{TIER_CONFIG[effective_tier]['primary_model'].removeprefix('amazon-bedrock/')}"
        )
        violations.append(
            {
                "field": "agents.defaults.model.primary",
                "reason": f"primary model {primary!r} is not allowed for tier={effective_tier}",
                "expected": expected_primary,
                "actual": primary,
            }
        )

    # 3. agents.defaults.models — keys must all be in tier allowlist
    models_map = config.get("agents", {}).get("defaults", {}).get("models", {})
    if isinstance(models_map, dict):
        illegal_keys = [
            k for k in models_map if k.removeprefix("amazon-bedrock/") not in _TIER_ALLOWED_MODEL_IDS[effective_tier]
        ]
        if illegal_keys:
            # Build expected: filter out illegal entries, ensure primary is present.
            expected_primary = (
                f"amazon-bedrock/{TIER_CONFIG[effective_tier]['primary_model'].removeprefix('amazon-bedrock/')}"
            )
            expected_models = _agent_models_for_tier(effective_tier, expected_primary)
            violations.append(
                {
                    "field": "agents.defaults.models",
                    "reason": f"agents.defaults.models contains non-allowlisted keys for tier={effective_tier}: {illegal_keys}",
                    "expected": expected_models,
                    "actual": models_map,
                }
            )

    # 4. channels.{provider}.accounts — free tier must have no accounts
    if effective_tier == "free":
        channels = config.get("channels", {})
        if isinstance(channels, dict):
            offending: dict[str, dict] = {}
            for provider, provider_cfg in channels.items():
                if not isinstance(provider_cfg, dict):
                    continue
                accounts = provider_cfg.get("accounts", {})
                if isinstance(accounts, dict) and accounts:
                    offending[provider] = accounts
            if offending:
                violations.append(
                    {
                        "field": "channels.accounts",
                        "reason": f"free tier cannot have channel accounts; found: {sorted(offending.keys())}",
                        "expected": {p: {} for p in offending},
                        "actual": offending,
                    }
                )

    return violations


def _set_dotted(target: dict, dotted: str, value: Any) -> None:
    """Set `target[a][b][c] = value` for dotted='a.b.c'. Creates intermediate
    dicts as needed."""
    parts = dotted.split(".")
    cursor = target
    for segment in parts[:-1]:
        if segment not in cursor or not isinstance(cursor[segment], dict):
            cursor[segment] = {}
        cursor = cursor[segment]
    cursor[parts[-1]] = value


def apply_reverts(config: dict, violations: list[PolicyViolation]) -> dict:
    """Return a deep copy of config with each violating field replaced by
    its expected value. Non-violating fields are preserved untouched.

    Special-cases `channels.accounts` since that's a collection of per-provider
    sub-fields, not a single dotted path.
    """
    result = copy.deepcopy(config)
    for v in violations:
        field = v["field"]
        expected = v["expected"]
        if field == "channels.accounts":
            # expected is {provider: {} ...}; write into channels.{provider}.accounts
            channels = result.setdefault("channels", {})
            for provider in expected:
                provider_cfg = channels.setdefault(provider, {})
                if isinstance(provider_cfg, dict):
                    provider_cfg["accounts"] = {}
        else:
            _set_dotted(result, field, copy.deepcopy(expected))
    return result
