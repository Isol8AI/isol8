# Config Protection Implementation Plan

**Status:** Draft

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce tier-based restrictions on `openclaw.json` at the filesystem level via backend reconciliation, so agents cannot bypass policy by writing the file directly (either via gateway RPC or direct file tools).

**Architecture:** Pure-policy module (`config_policy.py`) that evaluates a config dict against a tier and returns a list of field violations. A polling reconciler (`config_reconciler.py`) runs as a FastAPI lifespan task, mtime-gates its work, reads each active user's `openclaw.json` under the existing `fcntl.lockf` primitive, and reverts locked-field drift within ~1 second. Backend PATCH endpoint at `routers/config.py` shares the same policy for frontend/admin writes. Admin emergency endpoints set a 5s DDB grace window that the reconciler respects.

**Tech Stack:** Python 3 / FastAPI / asyncio / boto3 DynamoDB / pytest / existing `config_patcher.py` locking primitives.

**Spec:** `docs/superpowers/specs/2026-04-14-config-protection-design.md`

---

## File Map

**Create:**
- `apps/backend/core/services/config_policy.py` — pure policy module (evaluate + apply_reverts)
- `apps/backend/core/services/config_reconciler.py` — asyncio polling loop
- `apps/backend/scripts/reconcile_all_configs.py` — one-shot fleet cleanup
- `apps/backend/tests/unit/services/test_config_policy.py`
- `apps/backend/tests/unit/services/test_config_reconciler.py`
- `apps/backend/tests/integration/test_config_reconciliation.py`

**Modify:**
- `apps/backend/core/config.py` — add `CONFIG_RECONCILER_MODE` setting
- `apps/backend/core/repositories/container_repo.py` — add grace field helpers
- `apps/backend/main.py` — start reconciler in lifespan
- `apps/backend/routers/config.py` — swap custom channel check for policy eval on merged
- `apps/backend/routers/updates.py` — set grace on admin patches
- `apps/backend/tests/unit/routers/test_config_router.py` — update tests for new error shape + add model/provider cases

---

## Task 1: Policy module skeleton + clean-config test

**Files:**
- Create: `apps/backend/core/services/config_policy.py`
- Create: `apps/backend/tests/unit/services/test_config_policy.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/services/test_config_policy.py`:

```python
"""Tests for config_policy module."""
import json

import pytest

from core.containers.config import write_openclaw_config
from core.services import config_policy


class TestEvaluate:
    """Tests for config_policy.evaluate()."""

    def test_clean_free_tier_config_has_no_violations(self):
        raw = write_openclaw_config(
            region="us-east-1",
            gateway_token="t",
            tier="free",
        )
        config = json.loads(raw)
        assert config_policy.evaluate(config, "free") == []

    def test_clean_starter_tier_config_has_no_violations(self):
        raw = write_openclaw_config(
            region="us-east-1",
            gateway_token="t",
            tier="starter",
        )
        config = json.loads(raw)
        assert config_policy.evaluate(config, "starter") == []

    def test_clean_pro_tier_config_has_no_violations(self):
        raw = write_openclaw_config(
            region="us-east-1",
            gateway_token="t",
            tier="pro",
        )
        config = json.loads(raw)
        assert config_policy.evaluate(config, "pro") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.services.config_policy'`

- [ ] **Step 3: Write the minimal implementation**

Create `apps/backend/core/services/config_policy.py`:

```python
"""Tier-aware policy for openclaw.json locked fields.

Pure, side-effect-free. Takes a config dict and a tier name, returns a list
of field-level violations. Apply reverts by computing the authoritative
expected value from helpers in core/containers/config.py.
"""

import copy
from typing import Any, Literal, TypedDict

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


def evaluate(config: dict, tier: str) -> list[PolicyViolation]:
    """Return a list of locked-field violations for this config at this tier.

    Empty list means the config is legal. Each violation has enough info
    to revert (field, expected value) and for audit (reason, actual value).
    """
    return []


def apply_reverts(config: dict, violations: list[PolicyViolation]) -> dict:
    """Return a deep copy of config with each violating field replaced by
    its expected value. Non-violating fields — including OpenClaw's `meta`
    block and everything else — are preserved untouched.
    """
    return copy.deepcopy(config)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v`
Expected: All three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/config_policy.py apps/backend/tests/unit/services/test_config_policy.py
git commit -m "feat(config-policy): module skeleton with clean-config regression tests"
```

---

## Task 2: Policy — detect `models.providers` drift

**Files:**
- Modify: `apps/backend/core/services/config_policy.py`
- Modify: `apps/backend/tests/unit/services/test_config_policy.py`

- [ ] **Step 1: Write the failing tests**

Append to `apps/backend/tests/unit/services/test_config_policy.py` inside `TestEvaluate`:

```python
    def test_extra_provider_added_is_violation(self):
        raw = write_openclaw_config(gateway_token="t", tier="starter")
        config = json.loads(raw)
        # Agent tries to add openai as a provider
        config["models"]["providers"]["openai"] = {
            "baseUrl": "https://api.openai.com",
            "api": "openai",
            "models": [{"id": "gpt-4o", "name": "GPT-4o"}],
        }
        violations = config_policy.evaluate(config, "starter")
        fields = [v["field"] for v in violations]
        assert "models.providers" in fields

    def test_unauthorized_model_in_bedrock_is_violation(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        # Agent adds qwen to a free-tier provider list
        config["models"]["providers"]["amazon-bedrock"]["models"].append({
            "id": "qwen.qwen3-vl-235b-a22b",
            "name": "Qwen3 VL 235B",
            "contextWindow": 128000,
            "maxTokens": 8192,
            "reasoning": False,
            "input": ["text", "image"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        })
        violations = config_policy.evaluate(config, "free")
        assert any(v["field"] == "models.providers" for v in violations)

    def test_unknown_tier_falls_back_to_free(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        # Add qwen — illegal for free
        config["models"]["providers"]["amazon-bedrock"]["models"].append({
            "id": "qwen.qwen3-vl-235b-a22b", "name": "X", "contextWindow": 1,
            "maxTokens": 1, "reasoning": False, "input": ["text"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        })
        violations = config_policy.evaluate(config, "bogus-tier")
        assert any(v["field"] == "models.providers" for v in violations)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v`
Expected: Three new tests FAIL (evaluate returns `[]` always).

- [ ] **Step 3: Implement `models.providers` check**

Replace the `evaluate()` function body in `apps/backend/core/services/config_policy.py`:

```python
from core.config import TIER_CONFIG
from core.containers.config import (
    _TIER_ALLOWED_MODEL_IDS,
    _models_for_tier,
)


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
```

- [ ] **Step 4: Run all tests to verify pass**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v`
Expected: All tests PASS (clean configs still clean, drift tests catch violations).

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/config_policy.py apps/backend/tests/unit/services/test_config_policy.py
git commit -m "feat(config-policy): detect models.providers drift with strict allowlist match"
```

---

## Task 3: Policy — detect `agents.defaults.model.primary` drift

**Files:**
- Modify: `apps/backend/core/services/config_policy.py`
- Modify: `apps/backend/tests/unit/services/test_config_policy.py`

- [ ] **Step 1: Write the failing tests**

Append to `TestEvaluate`:

```python
    def test_free_tier_primary_changed_to_qwen_is_violation(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        config["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
        violations = config_policy.evaluate(config, "free")
        assert any(v["field"] == "agents.defaults.model.primary" for v in violations)

    def test_paid_tier_primary_allowed_model_no_violation(self):
        raw = write_openclaw_config(gateway_token="t", tier="pro")
        config = json.loads(raw)
        # Pro tier's primary is already Qwen from write_openclaw_config, but
        # swapping to MiniMax (also allowed on pro) should not be a violation.
        config["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/minimax.minimax-m2.5"
        violations = config_policy.evaluate(config, "pro")
        assert not any(v["field"] == "agents.defaults.model.primary" for v in violations)

    def test_paid_tier_primary_unknown_model_is_violation(self):
        raw = write_openclaw_config(gateway_token="t", tier="pro")
        config = json.loads(raw)
        config["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/claude-opus-4"
        violations = config_policy.evaluate(config, "pro")
        assert any(v["field"] == "agents.defaults.model.primary" for v in violations)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v -k primary`
Expected: 2 of 3 new tests FAIL (paid-tier allowed-swap happens to pass coincidentally until we enforce).

- [ ] **Step 3: Add primary-model check to `evaluate()`**

In `apps/backend/core/services/config_policy.py`, after the `models.providers` block inside `evaluate()`, append:

```python
    # 2. agents.defaults.model.primary — must be in tier allowlist
    primary = (
        config.get("agents", {})
        .get("defaults", {})
        .get("model", {})
        .get("primary", "")
    )
    bare_primary = primary.removeprefix("amazon-bedrock/")
    if bare_primary not in _TIER_ALLOWED_MODEL_IDS[effective_tier]:
        expected_primary = f"amazon-bedrock/{TIER_CONFIG[effective_tier]['primary_model'].removeprefix('amazon-bedrock/')}"
        violations.append(
            {
                "field": "agents.defaults.model.primary",
                "reason": f"primary model {primary!r} is not allowed for tier={effective_tier}",
                "expected": expected_primary,
                "actual": primary,
            }
        )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/config_policy.py apps/backend/tests/unit/services/test_config_policy.py
git commit -m "feat(config-policy): detect primary-model drift against tier allowlist"
```

---

## Task 4: Policy — detect `agents.defaults.models` key drift

**Files:**
- Modify: `apps/backend/core/services/config_policy.py`
- Modify: `apps/backend/tests/unit/services/test_config_policy.py`

- [ ] **Step 1: Write the failing test**

Append to `TestEvaluate`:

```python
    def test_free_tier_agents_models_with_qwen_is_violation(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        config["agents"]["defaults"]["models"]["amazon-bedrock/qwen.qwen3-vl-235b-a22b"] = {
            "alias": "Qwen3 VL 235B",
        }
        violations = config_policy.evaluate(config, "free")
        assert any(v["field"] == "agents.defaults.models" for v in violations)

    def test_paid_tier_agents_models_within_allowlist_no_violation(self):
        raw = write_openclaw_config(gateway_token="t", tier="pro")
        config = json.loads(raw)
        # Pro tier generator already includes both MiniMax and Qwen — clean.
        violations = config_policy.evaluate(config, "pro")
        assert not any(v["field"] == "agents.defaults.models" for v in violations)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v -k "agents_models"`
Expected: First test FAILS.

- [ ] **Step 3: Add `agents.defaults.models` check**

Append inside `evaluate()` in `apps/backend/core/services/config_policy.py` after the primary-model block:

```python
    # 3. agents.defaults.models — keys must all be in tier allowlist
    models_map = (
        config.get("agents", {}).get("defaults", {}).get("models", {})
    )
    if isinstance(models_map, dict):
        illegal_keys = [
            k for k in models_map
            if k.removeprefix("amazon-bedrock/")
            not in _TIER_ALLOWED_MODEL_IDS[effective_tier]
        ]
        if illegal_keys:
            # Build expected: filter out illegal entries, ensure primary is present.
            # Reuse write_openclaw_config's helper via a direct import.
            from core.containers.config import _agent_models_for_tier

            expected_primary = f"amazon-bedrock/{TIER_CONFIG[effective_tier]['primary_model'].removeprefix('amazon-bedrock/')}"
            expected_models = _agent_models_for_tier(effective_tier, expected_primary)
            violations.append(
                {
                    "field": "agents.defaults.models",
                    "reason": f"agents.defaults.models contains non-allowlisted keys for tier={effective_tier}: {illegal_keys}",
                    "expected": expected_models,
                    "actual": models_map,
                }
            )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/config_policy.py apps/backend/tests/unit/services/test_config_policy.py
git commit -m "feat(config-policy): detect agents.defaults.models drift against tier allowlist"
```

---

## Task 5: Policy — detect free-tier `channels.{p}.accounts` drift

**Files:**
- Modify: `apps/backend/core/services/config_policy.py`
- Modify: `apps/backend/tests/unit/services/test_config_policy.py`

- [ ] **Step 1: Write the failing tests**

Append to `TestEvaluate`:

```python
    def test_free_tier_telegram_account_is_violation(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        config["channels"]["telegram"]["accounts"] = {
            "my-agent": {"botToken": "1:abc"},
        }
        violations = config_policy.evaluate(config, "free")
        fields = [v["field"] for v in violations]
        assert "channels.accounts" in fields

    def test_paid_tier_telegram_account_no_violation(self):
        raw = write_openclaw_config(gateway_token="t", tier="starter")
        config = json.loads(raw)
        config["channels"]["telegram"]["accounts"] = {
            "my-agent": {"botToken": "1:abc"},
        }
        violations = config_policy.evaluate(config, "starter")
        assert not any(v["field"] == "channels.accounts" for v in violations)

    def test_free_tier_scaffold_channels_no_violation(self):
        # write_openclaw_config ships enabled/dmPolicy flags for all providers
        # but no accounts — should be clean on free.
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        violations = config_policy.evaluate(config, "free")
        assert not any(v["field"] == "channels.accounts" for v in violations)

    def test_free_tier_channels_with_empty_accounts_no_violation(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        config["channels"]["telegram"]["accounts"] = {}
        violations = config_policy.evaluate(config, "free")
        assert not any(v["field"] == "channels.accounts" for v in violations)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v -k channels`
Expected: First test FAILS.

- [ ] **Step 3: Implement channels check**

Append inside `evaluate()`:

```python
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/config_policy.py apps/backend/tests/unit/services/test_config_policy.py
git commit -m "feat(config-policy): detect free-tier channel-account drift"
```

---

## Task 6: Policy — `apply_reverts` implementation

**Files:**
- Modify: `apps/backend/core/services/config_policy.py`
- Modify: `apps/backend/tests/unit/services/test_config_policy.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_config_policy.py`:

```python
class TestApplyReverts:
    """Tests for config_policy.apply_reverts()."""

    def test_revert_providers_restores_tier_allowlist(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        config["models"]["providers"]["openai"] = {"api": "openai", "models": []}
        violations = config_policy.evaluate(config, "free")
        reverted = config_policy.apply_reverts(config, violations)
        assert "openai" not in reverted["models"]["providers"]
        assert "amazon-bedrock" in reverted["models"]["providers"]

    def test_revert_primary_restores_tier_default(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        config["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
        violations = config_policy.evaluate(config, "free")
        reverted = config_policy.apply_reverts(config, violations)
        assert reverted["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/minimax.minimax-m2.5"

    def test_revert_channels_empties_accounts_for_violating_providers_only(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        config["channels"]["telegram"]["accounts"] = {"a": {"botToken": "x"}}
        config["channels"]["discord"]["accounts"] = {"b": {"botToken": "y"}}
        violations = config_policy.evaluate(config, "free")
        reverted = config_policy.apply_reverts(config, violations)
        assert reverted["channels"]["telegram"]["accounts"] == {}
        assert reverted["channels"]["discord"]["accounts"] == {}
        # Scaffold flags preserved
        assert reverted["channels"]["telegram"]["enabled"] is True
        assert reverted["channels"]["telegram"]["dmPolicy"] == "pairing"

    def test_apply_reverts_preserves_meta_and_unrelated_keys(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        config["meta"] = {"lastTouchedVersion": "2026.4.5", "lastTouchedAt": "2026-04-12T19:43:24Z"}
        config["tools"]["deny"].append("some-new-tool")
        config["models"]["providers"]["openai"] = {"api": "openai"}
        violations = config_policy.evaluate(config, "free")
        reverted = config_policy.apply_reverts(config, violations)
        # Meta preserved
        assert reverted["meta"] == {"lastTouchedVersion": "2026.4.5", "lastTouchedAt": "2026-04-12T19:43:24Z"}
        # Agent-mutable tool change preserved
        assert "some-new-tool" in reverted["tools"]["deny"]
        # Provider reverted
        assert "openai" not in reverted["models"]["providers"]

    def test_apply_reverts_empty_violations_is_identity(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        reverted = config_policy.apply_reverts(config, [])
        assert reverted == config
        assert reverted is not config  # deep-copy
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py::TestApplyReverts -v`
Expected: All tests in `TestApplyReverts` except the last FAIL (the current impl just deep-copies without applying anything).

- [ ] **Step 3: Implement `apply_reverts`**

Replace the `apply_reverts` function body in `apps/backend/core/services/config_policy.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_policy.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/config_policy.py apps/backend/tests/unit/services/test_config_policy.py
git commit -m "feat(config-policy): apply_reverts with dotted-path + channels special case"
```

---

## Task 7: Container repo — `reconciler_grace_until` helpers

**Files:**
- Modify: `apps/backend/core/repositories/container_repo.py`
- Create: `apps/backend/tests/unit/repositories/test_container_repo_grace.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/repositories/test_container_repo_grace.py`:

```python
"""Tests for container_repo grace-window helpers."""
import time
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_set_reconciler_grace_writes_epoch_seconds():
    from core.repositories import container_repo

    with (
        patch.object(container_repo, "get_by_owner_id", AsyncMock(return_value={"owner_id": "u1", "id": "i", "created_at": "x"})),
        patch.object(container_repo, "update_fields", AsyncMock(return_value={})) as mock_update,
    ):
        before = int(time.time())
        await container_repo.set_reconciler_grace("u1", seconds=5)
        after = int(time.time())

    mock_update.assert_awaited_once()
    args, _ = mock_update.call_args
    owner_id, fields = args
    assert owner_id == "u1"
    assert "reconciler_grace_until" in fields
    assert before + 5 <= fields["reconciler_grace_until"] <= after + 6


@pytest.mark.asyncio
async def test_get_reconciler_grace_returns_zero_when_unset():
    from core.repositories import container_repo

    with patch.object(container_repo, "get_by_owner_id", AsyncMock(return_value={"owner_id": "u1"})):
        grace = await container_repo.get_reconciler_grace("u1")
    assert grace == 0


@pytest.mark.asyncio
async def test_get_reconciler_grace_returns_stored_value():
    from core.repositories import container_repo

    with patch.object(container_repo, "get_by_owner_id", AsyncMock(return_value={"owner_id": "u1", "reconciler_grace_until": 1234567890})):
        grace = await container_repo.get_reconciler_grace("u1")
    assert grace == 1234567890
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_container_repo_grace.py -v`
Expected: FAIL (`set_reconciler_grace` / `get_reconciler_grace` not defined).

- [ ] **Step 3: Add helpers to container_repo**

Append to `apps/backend/core/repositories/container_repo.py`:

```python
async def set_reconciler_grace(owner_id: str, seconds: int = 5) -> dict | None:
    """Write `reconciler_grace_until = now + seconds` to this owner's container
    row. The reconciler checks this before reverting so admin / backend-initiated
    writes aren't immediately undone by a concurrent reconciler tick.

    No-op if the row doesn't exist (returns None).
    """
    import time

    return await update_fields(owner_id, {"reconciler_grace_until": int(time.time()) + seconds})


async def get_reconciler_grace(owner_id: str) -> int:
    """Return the reconciler_grace_until timestamp (epoch seconds) for this
    owner, or 0 if unset or the row doesn't exist."""
    existing = await get_by_owner_id(owner_id)
    if existing is None:
        return 0
    value = existing.get("reconciler_grace_until")
    if value is None:
        return 0
    # DDB returns numbers as Decimal — coerce to int.
    return int(value)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_container_repo_grace.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/repositories/container_repo.py apps/backend/tests/unit/repositories/test_container_repo_grace.py
git commit -m "feat(container-repo): reconciler_grace_until get/set helpers"
```

---

## Task 8: Settings — `CONFIG_RECONCILER_MODE`

**Files:**
- Modify: `apps/backend/core/config.py`
- Modify: `apps/backend/tests/conftest.py` (if needed for env isolation — check first)

- [ ] **Step 1: Read the current settings module**

Run: `grep -n 'class Settings\|ENVIRONMENT\|pydantic' apps/backend/core/config.py | head -20`

Confirm this is a pydantic `BaseSettings` class. If it is, the new field will be picked up via env var `CONFIG_RECONCILER_MODE`.

- [ ] **Step 2: Add the setting**

In `apps/backend/core/config.py`, inside the `Settings` class (alongside other env-driven fields), add:

```python
    # Config reconciler mode:
    #   "off"      -- disabled entirely
    #   "report"   -- evaluate + log + metric, but do not revert (rollout phase A)
    #   "enforce"  -- evaluate + revert on drift (rollout phase B, steady-state)
    CONFIG_RECONCILER_MODE: str = "off"
```

Place it near other mode-like settings (e.g. near `BEDROCK_ENABLED` or `ENVIRONMENT`). Exact placement is stylistic — just keep it with other top-level flags.

- [ ] **Step 3: Verify settings loads and default is 'off'**

Run: `cd apps/backend && uv run python -c "from core.config import settings; print(settings.CONFIG_RECONCILER_MODE)"`
Expected: prints `off`.

Also run: `cd apps/backend && CONFIG_RECONCILER_MODE=report uv run python -c "from core.config import settings; print(settings.CONFIG_RECONCILER_MODE)"`
Expected: prints `report`.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/config.py
git commit -m "feat(config): CONFIG_RECONCILER_MODE setting (off/report/enforce)"
```

---

## Task 9: Reconciler skeleton + shutdown behavior

**Files:**
- Create: `apps/backend/core/services/config_reconciler.py`
- Create: `apps/backend/tests/unit/services/test_config_reconciler.py`

- [ ] **Step 1: Write the failing test**

Create `apps/backend/tests/unit/services/test_config_reconciler.py`:

```python
"""Tests for ConfigReconciler lifecycle + tick logic."""
import asyncio

import pytest


@pytest.mark.asyncio
async def test_reconciler_run_forever_exits_when_stop_set():
    from core.services.config_reconciler import ConfigReconciler

    r = ConfigReconciler(efs_mount="/tmp/does-not-exist-for-test")
    task = asyncio.create_task(r.run_forever())

    # Give it a moment to enter the loop, then stop it.
    await asyncio.sleep(0.05)
    r.stop()

    # It should exit within one tick interval + a small margin.
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_reconciler_swallows_tick_exceptions(monkeypatch, caplog):
    """A raised exception inside _tick must not kill run_forever."""
    from core.services.config_reconciler import ConfigReconciler

    r = ConfigReconciler(efs_mount="/tmp")

    call_count = 0

    async def boom():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("synthetic tick failure")

    monkeypatch.setattr(r, "_tick", boom)

    task = asyncio.create_task(r.run_forever())
    await asyncio.sleep(2.2)  # enough for multiple tick attempts
    r.stop()
    await asyncio.wait_for(task, timeout=2.0)
    assert call_count >= 2  # loop kept going despite exceptions
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_reconciler.py -v`
Expected: FAIL (`config_reconciler` module doesn't exist).

- [ ] **Step 3: Write reconciler skeleton**

Create `apps/backend/core/services/config_reconciler.py`:

```python
"""Backend reconciliation loop for openclaw.json tier policy.

Polls every active user's config on EFS at ~1s cadence, evaluates it
against the tier policy (core.services.config_policy), and reverts drift
on locked fields only. Non-locked fields are never touched.

Ships in three modes via CONFIG_RECONCILER_MODE:
  - off: reconciler never starts
  - report: reads + evaluates + logs, never writes (rollout phase A)
  - enforce: reads + evaluates + reverts (rollout phase B, steady state)
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


class ConfigReconciler:
    def __init__(
        self,
        efs_mount: str,
        tier_cache_ttl: float = 60.0,
        tick_interval: float = 1.0,
    ):
        self._efs_mount = efs_mount
        self._tier_cache_ttl = tier_cache_ttl
        self._tick_interval = tick_interval
        self._stop = asyncio.Event()
        self._last_seen_mtime: dict[str, float] = {}
        self._tier_cache: dict[str, tuple[str, float]] = {}

    def stop(self) -> None:
        """Signal the loop to exit after its current tick."""
        self._stop.set()

    async def run_forever(self) -> None:
        logger.info("config_reconciler started")
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("config_reconciler tick failed")
            # Sleep until tick_interval elapses OR stop is set (whichever first).
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick_interval)
            except asyncio.TimeoutError:
                pass
        logger.info("config_reconciler stopped")

    async def _tick(self) -> None:
        """One pass over the active-owner set. No-op in the skeleton."""
        return
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_reconciler.py -v`
Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/config_reconciler.py apps/backend/tests/unit/services/test_config_reconciler.py
git commit -m "feat(config-reconciler): module skeleton with run_forever + graceful shutdown"
```

---

## Task 10: Reconciler — mtime-gated per-user check (no revert yet)

**Files:**
- Modify: `apps/backend/core/services/config_reconciler.py`
- Modify: `apps/backend/tests/unit/services/test_config_reconciler.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_config_reconciler.py`:

```python
@pytest.mark.asyncio
async def test_tick_skips_user_when_mtime_unchanged(tmp_path, monkeypatch):
    from core.services.config_reconciler import ConfigReconciler

    user_dir = tmp_path / "user_A"
    user_dir.mkdir()
    cfg = user_dir / "openclaw.json"
    cfg.write_text('{"models":{"providers":{}}}')

    r = ConfigReconciler(efs_mount=str(tmp_path))

    from unittest.mock import AsyncMock
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=["user_A"]),
    )

    read_count = 0
    original_open = open
    def tracked_open(path, *a, **kw):
        nonlocal read_count
        if str(path).endswith("openclaw.json"):
            read_count += 1
        return original_open(path, *a, **kw)
    monkeypatch.setattr("builtins.open", tracked_open)

    # First tick — mtime unseen, should read.
    await r._tick()
    first_reads = read_count

    # Second tick — mtime unchanged, should skip read.
    await r._tick()
    assert read_count == first_reads, "second tick must not re-read unchanged file"


@pytest.mark.asyncio
async def test_tick_handles_missing_config_file(tmp_path, monkeypatch):
    from core.services.config_reconciler import ConfigReconciler
    from unittest.mock import AsyncMock

    r = ConfigReconciler(efs_mount=str(tmp_path))
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=["ghost_user"]),
    )

    # Should not raise.
    await r._tick()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_reconciler.py -v -k mtime`
Expected: FAIL (`list_active_owners` does not exist; `_tick` does nothing).

- [ ] **Step 3: Add `list_active_owners` to container_repo**

In `apps/backend/core/repositories/container_repo.py`, append:

```python
async def list_active_owners() -> list[str]:
    """Return owner_ids for containers with status='running'. Used by the
    config reconciler to enumerate targets.

    Deliberately excludes 'provisioning' — during that phase the backend
    itself is writing openclaw.json, and the reconciler must not race with
    it. The reconciler starts caring once the container is fully running.
    """
    rows = await get_by_status("running")
    return [r["owner_id"] for r in rows if "owner_id" in r]
```

- [ ] **Step 4: Add mtime-gated per-user check to reconciler**

Replace the `_tick` method in `apps/backend/core/services/config_reconciler.py`:

```python
    async def _tick(self) -> None:
        from core.repositories import container_repo

        owners = await container_repo.list_active_owners()
        if not owners:
            return

        sem = asyncio.Semaphore(20)

        async def _one(owner_id: str):
            async with sem:
                try:
                    await self._check_one(owner_id)
                except Exception:
                    logger.exception("config_reconciler failed for owner %s", owner_id)

        await asyncio.gather(*[_one(o) for o in owners])

    async def _check_one(self, owner_id: str) -> None:
        import os

        path = os.path.join(self._efs_mount, owner_id, "openclaw.json")
        try:
            mtime = await asyncio.to_thread(os.path.getmtime, path)
        except FileNotFoundError:
            # Container row says running but file not yet there; skip.
            return

        if self._last_seen_mtime.get(owner_id) == mtime:
            return

        # File changed (or first time seeing it); in this task, only record
        # the mtime. Actual read + policy + revert lands in Task 11.
        self._last_seen_mtime[owner_id] = mtime
```

- [ ] **Step 5: Run tests to verify pass**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_reconciler.py tests/unit/repositories/test_container_repo_grace.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/core/services/config_reconciler.py apps/backend/core/repositories/container_repo.py apps/backend/tests/unit/services/test_config_reconciler.py
git commit -m "feat(config-reconciler): mtime-gated per-user check + list_active_owners helper"
```

---

## Task 11: Reconciler — read, evaluate, and revert in enforce mode

**Files:**
- Modify: `apps/backend/core/services/config_reconciler.py`
- Modify: `apps/backend/tests/unit/services/test_config_reconciler.py`

- [ ] **Step 1: Write the failing tests**

Append to `test_config_reconciler.py`:

```python
@pytest.mark.asyncio
async def test_tick_reverts_drift_in_enforce_mode(tmp_path, monkeypatch):
    import json
    from unittest.mock import AsyncMock

    from core.containers.config import write_openclaw_config
    from core.services.config_reconciler import ConfigReconciler

    user = "user_drift"
    udir = tmp_path / user
    udir.mkdir()
    cfg_path = udir / "openclaw.json"
    # Start with a clean free-tier config, then mutate it in-file.
    base = json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    base["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
    cfg_path.write_text(json.dumps(base, indent=2))

    r = ConfigReconciler(efs_mount=str(tmp_path))
    monkeypatch.setattr("core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE", "enforce", raising=False)
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=[user]),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": "free"}),
    )

    await r._tick()

    on_disk = json.loads(cfg_path.read_text())
    assert on_disk["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/minimax.minimax-m2.5"


@pytest.mark.asyncio
async def test_tick_report_mode_does_not_write(tmp_path, monkeypatch):
    import json
    from unittest.mock import AsyncMock

    from core.containers.config import write_openclaw_config
    from core.services.config_reconciler import ConfigReconciler

    user = "user_report"
    udir = tmp_path / user
    udir.mkdir()
    cfg_path = udir / "openclaw.json"
    base = json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    base["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
    cfg_path.write_text(json.dumps(base, indent=2))
    drift_mtime = cfg_path.stat().st_mtime

    r = ConfigReconciler(efs_mount=str(tmp_path))
    monkeypatch.setattr("core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE", "report", raising=False)
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=[user]),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": "free"}),
    )

    await r._tick()

    # mtime unchanged → no write happened
    assert cfg_path.stat().st_mtime == drift_mtime


@pytest.mark.asyncio
async def test_tick_honors_grace_window(tmp_path, monkeypatch):
    import json
    import time
    from unittest.mock import AsyncMock

    from core.containers.config import write_openclaw_config
    from core.services.config_reconciler import ConfigReconciler

    user = "user_grace"
    udir = tmp_path / user
    udir.mkdir()
    cfg_path = udir / "openclaw.json"
    base = json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    base["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
    cfg_path.write_text(json.dumps(base, indent=2))
    pre_mtime = cfg_path.stat().st_mtime

    r = ConfigReconciler(efs_mount=str(tmp_path))
    monkeypatch.setattr("core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE", "enforce", raising=False)
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=[user]),
    )
    # Grace is in the future → skip revert.
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        AsyncMock(return_value=int(time.time()) + 30),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": "free"}),
    )

    await r._tick()
    assert cfg_path.stat().st_mtime == pre_mtime
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_reconciler.py -v -k "enforce or report or grace"`
Expected: FAIL (no tier lookup, no revert path).

- [ ] **Step 3: Replace the reconciler body with the full implementation**

Replace the entire contents of `apps/backend/core/services/config_reconciler.py`:

```python
"""Backend reconciliation loop for openclaw.json tier policy.

Polls every active user's config on EFS at ~1s cadence, evaluates it
against the tier policy (core.services.config_policy), and reverts drift
on locked fields only. Non-locked fields are never touched.

Ships in three modes via CONFIG_RECONCILER_MODE:
  - off: reconciler never starts
  - report: reads + evaluates + logs, never writes (rollout phase A)
  - enforce: reads + evaluates + reverts (rollout phase B, steady state)
"""

import asyncio
import json
import logging
import os
import time

from core.config import settings
from core.constants import SYSTEM_ACTOR_ID
from core.observability.metrics import put_metric
from core.repositories import billing_repo, container_repo
from core.services import config_policy
from core.services.config_patcher import _locked_rmw

logger = logging.getLogger(__name__)


class ConfigReconciler:
    def __init__(
        self,
        efs_mount: str,
        tier_cache_ttl: float = 60.0,
        tick_interval: float = 1.0,
    ):
        self._efs_mount = efs_mount
        self._tier_cache_ttl = tier_cache_ttl
        self._tick_interval = tick_interval
        self._stop = asyncio.Event()
        self._last_seen_mtime: dict[str, float] = {}
        self._tier_cache: dict[str, tuple[str, float]] = {}

    def stop(self) -> None:
        self._stop.set()

    async def run_forever(self) -> None:
        logger.info("config_reconciler started mode=%s", settings.CONFIG_RECONCILER_MODE)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:
                logger.exception("config_reconciler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._tick_interval)
            except asyncio.TimeoutError:
                pass
        logger.info("config_reconciler stopped")

    async def _tick(self) -> None:
        if settings.CONFIG_RECONCILER_MODE == "off":
            return
        owners = await container_repo.list_active_owners()
        if not owners:
            return

        sem = asyncio.Semaphore(20)

        async def _one(owner_id: str):
            async with sem:
                try:
                    await self._check_one(owner_id)
                except Exception:
                    logger.exception("config_reconciler failed for owner %s", owner_id)

        started = time.monotonic()
        await asyncio.gather(*[_one(o) for o in owners])
        put_metric(
            "config.reconciler.tick.duration",
            value=(time.monotonic() - started) * 1000.0,
            dimensions={"mode": settings.CONFIG_RECONCILER_MODE},
        )

    async def _check_one(self, owner_id: str) -> None:
        path = os.path.join(self._efs_mount, owner_id, "openclaw.json")
        try:
            mtime = await asyncio.to_thread(os.path.getmtime, path)
        except FileNotFoundError:
            return

        if self._last_seen_mtime.get(owner_id) == mtime:
            return

        tier = await self._resolve_tier(owner_id)
        if tier is None:
            # Fail-open: don't lock a user out of their own plan due to our DDB error.
            return

        grace_until = await container_repo.get_reconciler_grace(owner_id)
        if grace_until > int(time.time()):
            # Admin just wrote; don't fight them.
            return

        mode = settings.CONFIG_RECONCILER_MODE

        if mode == "report":
            # Read without a lock (we're not writing); evaluate; log.
            try:
                config = await asyncio.to_thread(_read_json, path)
            except (OSError, json.JSONDecodeError) as e:
                logger.warning("reconciler: failed to read %s: %s", path, e)
                put_metric("config.reconciler.errors", dimensions={"kind": "read"})
                return
            violations = config_policy.evaluate(config, tier)
            if violations:
                put_metric("config.drift.reported", dimensions={"tier": tier})
                logger.info(
                    "reconciler(report) drift for owner=%s tier=%s fields=%s",
                    owner_id, tier, [v["field"] for v in violations],
                )
            self._last_seen_mtime[owner_id] = mtime
            return

        if mode == "enforce":
            reverted_fields: list[str] = []

            def _mutate(current: dict) -> bool:
                violations = config_policy.evaluate(current, tier)
                if not violations:
                    return False
                reverted = config_policy.apply_reverts(current, violations)
                current.clear()
                current.update(reverted)
                reverted_fields.extend(v["field"] for v in violations)
                return True

            try:
                await _locked_rmw(owner_id, _mutate, "policy_revert")
            except Exception as e:
                logger.exception("reconciler: revert failed for owner=%s: %s", owner_id, e)
                put_metric("config.reconciler.errors", dimensions={"kind": "revert"})
                return

            if reverted_fields:
                put_metric("config.drift.reverted", dimensions={"tier": tier})
                logger.info(
                    "reconciler(enforce) reverted owner=%s tier=%s fields=%s",
                    owner_id, tier, reverted_fields,
                )
                await _write_audit(owner_id, tier, reverted_fields)
            # Mtime moved from our own write; refresh cache from the fresh stat.
            try:
                self._last_seen_mtime[owner_id] = await asyncio.to_thread(os.path.getmtime, path)
            except FileNotFoundError:
                self._last_seen_mtime.pop(owner_id, None)
            return

        # Unknown mode — behave as off.
        logger.warning("unknown CONFIG_RECONCILER_MODE=%r, treating as off", mode)

    async def _resolve_tier(self, owner_id: str) -> str | None:
        cached = self._tier_cache.get(owner_id)
        now = time.monotonic()
        if cached and now - cached[1] < self._tier_cache_ttl:
            return cached[0]
        try:
            account = await billing_repo.get_by_owner_id(owner_id)
        except Exception:
            logger.exception("reconciler: billing_repo lookup failed for owner=%s", owner_id)
            put_metric("config.reconciler.errors", dimensions={"kind": "tier_lookup"})
            return None
        tier = (account or {}).get("plan_tier", "free")
        self._tier_cache[owner_id] = (tier, now)
        return tier


def _read_json(path: str) -> dict:
    with open(path, "r") as f:
        return json.load(f)


async def _write_audit(owner_id: str, tier: str, fields: list[str]) -> None:
    """Best-effort audit log; swallow failures (audit should never break the loop)."""
    try:
        from core.repositories import audit_log_repo  # type: ignore
        await audit_log_repo.create(
            actor_id=SYSTEM_ACTOR_ID,
            action="config_policy_revert",
            owner_id=owner_id,
            metadata={"tier": tier, "fields": fields},
        )
    except Exception:
        logger.debug("audit log write failed", exc_info=True)
```

- [ ] **Step 4: Confirm audit_log_repo exists (or stub its absence)**

Run: `ls apps/backend/core/repositories/ | grep -i audit`

If there's no `audit_log_repo.py`, the `_write_audit` call is already wrapped in a try/except that only logs at debug level — so nothing breaks. That's fine; a future task can formalize the audit write. Move on.

- [ ] **Step 5: Run all reconciler and policy tests**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_config_reconciler.py tests/unit/services/test_config_policy.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/core/services/config_reconciler.py apps/backend/tests/unit/services/test_config_reconciler.py
git commit -m "feat(config-reconciler): read/evaluate/revert with enforce+report modes, tier cache, grace window"
```

---

## Task 12: Integration test — real EFS path, real fcntl lock

**Files:**
- Create: `apps/backend/tests/integration/test_config_reconciliation.py`

- [ ] **Step 1: Write the integration tests**

Create `apps/backend/tests/integration/test_config_reconciliation.py`:

```python
"""Integration tests for the config reconciler against a real tmp filesystem
and real fcntl.lockf locking (no mocks around the lock/IO layer).

These catch bugs that unit mocks miss: lock semantics, atomic rename,
concurrent writer races.
"""

import asyncio
import json
import time
from unittest.mock import AsyncMock

import pytest

from core.containers.config import write_openclaw_config
from core.services.config_reconciler import ConfigReconciler


@pytest.mark.asyncio
async def test_reconciler_reverts_drift_end_to_end(tmp_path, monkeypatch):
    user = "user_e2e"
    udir = tmp_path / user
    udir.mkdir()
    cfg = udir / "openclaw.json"
    base = json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    base["agents"]["defaults"]["model"]["primary"] = "amazon-bedrock/qwen.qwen3-vl-235b-a22b"
    base["channels"]["telegram"]["accounts"] = {"bot1": {"botToken": "x"}}
    cfg.write_text(json.dumps(base, indent=2))

    # Patch the module-level _efs_mount_path used inside _locked_rmw.
    monkeypatch.setattr("core.services.config_patcher._efs_mount_path", str(tmp_path))
    monkeypatch.setattr(
        "core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE",
        "enforce",
        raising=False,
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=[user]),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": "free"}),
    )

    r = ConfigReconciler(efs_mount=str(tmp_path), tick_interval=0.1)
    await r._tick()

    restored = json.loads(cfg.read_text())
    assert restored["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/minimax.minimax-m2.5"
    assert restored["channels"]["telegram"]["accounts"] == {}


@pytest.mark.asyncio
async def test_reconciler_serializes_with_config_patcher(tmp_path, monkeypatch):
    """Fire a reconciler tick and a config_patcher patch in parallel.
    The result must be a single valid JSON file (no interleaved writes)."""
    import json as _json
    from core.services import config_patcher

    user = "user_par"
    udir = tmp_path / user
    udir.mkdir()
    cfg = udir / "openclaw.json"
    base = _json.loads(write_openclaw_config(gateway_token="t", tier="free"))
    cfg.write_text(_json.dumps(base, indent=2))

    monkeypatch.setattr("core.services.config_patcher._efs_mount_path", str(tmp_path))
    monkeypatch.setattr(
        "core.services.config_reconciler.settings.CONFIG_RECONCILER_MODE",
        "enforce",
        raising=False,
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.list_active_owners",
        AsyncMock(return_value=[user]),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.container_repo.get_reconciler_grace",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        "core.services.config_reconciler.billing_repo.get_by_owner_id",
        AsyncMock(return_value={"plan_tier": "free"}),
    )

    r = ConfigReconciler(efs_mount=str(tmp_path))
    await asyncio.gather(
        r._tick(),
        config_patcher.patch_openclaw_config(user, {"tools": {"web": {"fetch": {"enabled": False}}}}),
    )

    # File must still parse and contain both changes' non-conflicting pieces.
    result = _json.loads(cfg.read_text())
    assert result["tools"]["web"]["fetch"]["enabled"] is False
```

- [ ] **Step 2: Run tests**

Run: `cd apps/backend && uv run pytest tests/integration/test_config_reconciliation.py -v`
Expected: Both tests PASS.

- [ ] **Step 3: Commit**

```bash
git add apps/backend/tests/integration/test_config_reconciliation.py
git commit -m "test(config-reconciler): end-to-end + fcntl-lock concurrency integration tests"
```

---

## Task 13: Router — swap `routers/config.py` to use policy module

**Files:**
- Modify: `apps/backend/routers/config.py`
- Modify: `apps/backend/tests/unit/routers/test_config_router.py`

- [ ] **Step 1: Update existing tests for new error shape**

Open `apps/backend/tests/unit/routers/test_config_router.py`.

Replace `test_patch_config_free_tier_channels_rejected` (around line 94-106) with:

```python
def test_patch_config_free_tier_channels_rejected(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch("routers.config.read_openclaw_config_from_efs", AsyncMock(return_value={
                "channels": {"telegram": {"enabled": True, "dmPolicy": "pairing"}},
                "models": {"providers": _free_providers()},
                "agents": {"defaults": {"model": {"primary": "amazon-bedrock/minimax.minimax-m2.5"}, "models": {"amazon-bedrock/minimax.minimax-m2.5": {"alias": "MiniMax M2.5"}}}},
            })),
            _mock_billing("free"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"channels": {"telegram": {"accounts": {"a": {"botToken": "x"}}}}}},
            )
        assert resp.status_code == 403
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "policy_violation"
        assert "channels.accounts" in detail.get("fields", [])
        mock_patch.assert_not_called()
    finally:
        cleanup()
```

At the top of the test file, after the imports, add the helper:

```python
def _free_providers():
    from core.containers.config import _models_for_tier
    return {
        "amazon-bedrock": {
            "baseUrl": "https://bedrock-runtime.us-east-1.amazonaws.com",
            "api": "bedrock-converse-stream",
            "auth": "aws-sdk",
            "models": _models_for_tier("free"),
        },
    }
```

- [ ] **Step 2: Add new tests for model/provider enforcement**

Append to `test_config_router.py`:

```python
def test_patch_config_rejects_unauthorized_provider_any_tier(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch("routers.config.read_openclaw_config_from_efs", AsyncMock(return_value={
                "models": {"providers": _free_providers()},
                "agents": {"defaults": {"model": {"primary": "amazon-bedrock/minimax.minimax-m2.5"}, "models": {"amazon-bedrock/minimax.minimax-m2.5": {"alias": "MiniMax M2.5"}}}},
            })),
            _mock_billing("pro"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"models": {"providers": {"openai": {"api": "openai", "baseUrl": "x", "models": []}}}}},
            )
        assert resp.status_code == 403
        detail = resp.json().get("detail", {})
        assert detail.get("code") == "policy_violation"
        assert "models.providers" in detail.get("fields", [])
        mock_patch.assert_not_called()
    finally:
        cleanup()


def test_patch_config_accepts_non_locked_field_change(client):
    cleanup = _patch_auth(_personal_auth())
    try:
        with (
            patch("routers.config.patch_openclaw_config", AsyncMock()) as mock_patch,
            patch("routers.config.read_openclaw_config_from_efs", AsyncMock(return_value={
                "models": {"providers": _free_providers()},
                "agents": {"defaults": {"model": {"primary": "amazon-bedrock/minimax.minimax-m2.5"}, "models": {"amazon-bedrock/minimax.minimax-m2.5": {"alias": "MiniMax M2.5"}}}},
            })),
            _mock_billing("free"),
        ):
            resp = client.patch(
                "/api/v1/config",
                json={"patch": {"tools": {"web": {"search": {"enabled": False}}}}},
            )
        assert resp.status_code == 200
        mock_patch.assert_awaited_once()
    finally:
        cleanup()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_config_router.py -v`
Expected: New and updated tests FAIL (router still uses the old check).

- [ ] **Step 4: Swap the router implementation**

Replace the `patch_config` endpoint body in `apps/backend/routers/config.py` (currently lines ~102-138) with:

```python
@router.patch(
    "",
    summary="Patch the caller's openclaw.json config",
    description=(
        "Deep-merges the patch into the caller's owner_id openclaw.json on EFS. "
        "Derives owner_id from auth context (org_id if org, else user_id). "
        "Requires org_admin for org callers. Tier-gates locked fields via config_policy."
    ),
)
async def patch_config(
    body: ConfigPatchBody,
    auth: AuthContext = Depends(get_current_user),
):
    require_org_admin(auth)
    owner_id = resolve_owner_id(auth)

    # Resolve tier and simulate the merged config to apply policy to the
    # final state, not to the isolated patch (which might only toggle a
    # scaffold flag while keeping the locked field legal).
    account = await billing_repo.get_by_owner_id(owner_id)
    tier = account.get("plan_tier", "free") if isinstance(account, dict) else "free"

    current = await read_openclaw_config_from_efs(owner_id) or {}
    merged = _deep_merge_for_policy(current, body.patch)

    from core.services import config_policy

    violations = config_policy.evaluate(merged, tier)
    if violations:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "policy_violation",
                "fields": [v["field"] for v in violations],
                "reason": violations[0]["reason"],
            },
        )

    # Bot-token collision pre-check (channels-specific; runs only if patch touches channels).
    if _patch_touches_channels(body.patch):
        await _check_token_collision(owner_id, body.patch)

    try:
        await patch_openclaw_config(owner_id, body.patch)
    except ConfigPatchError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"status": "patched", "owner_id": owner_id}


def _deep_merge_for_policy(base: dict, patch: dict) -> dict:
    """Local deep-merge matching config_patcher._deep_merge semantics —
    dicts merge recursively, non-dict values replace. Kept local to avoid
    importing a private helper."""
    import copy

    result = copy.deepcopy(base) if not isinstance(base, dict) else dict(base)
    if not isinstance(patch, dict):
        return patch
    for k, v in patch.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge_for_policy(result[k], v)
        else:
            import copy as _c
            result[k] = _c.deepcopy(v)
    return result
```

Keep the existing `_patch_touches_channels` and `_check_token_collision` helpers — they still run for the collision check. Do NOT keep the old tier-gate channel block; `config_policy.evaluate` now handles it.

- [ ] **Step 5: Run tests to verify pass**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_config_router.py -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add apps/backend/routers/config.py apps/backend/tests/unit/routers/test_config_router.py
git commit -m "refactor(routers/config): delegate locked-field enforcement to config_policy"
```

---

## Task 14: Admin patch endpoints set grace window

**Files:**
- Modify: `apps/backend/routers/updates.py`
- Create: `apps/backend/tests/unit/routers/test_updates_grace.py`

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/unit/routers/test_updates_grace.py`:

```python
"""Tests for admin-patch grace window on routers/updates.py."""
import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _patch_auth():
    from core.auth import AuthContext, get_current_user
    from main import app
    app.dependency_overrides[get_current_user] = lambda: AuthContext(user_id="u_admin")
    return lambda: app.dependency_overrides.pop(get_current_user, None)


def test_admin_single_config_patch_sets_grace(client):
    cleanup = _patch_auth()
    try:
        with (
            patch("routers.updates.patch_openclaw_config", AsyncMock()),
            patch("routers.updates.container_repo.set_reconciler_grace", AsyncMock()) as set_grace,
        ):
            resp = client.patch("/api/v1/container/config/owner_1", json={"patch": {"tools": {}}})
        assert resp.status_code == 200
        set_grace.assert_awaited_once_with("owner_1", seconds=5)
    finally:
        cleanup()
```

- [ ] **Step 2: Run test to verify failure**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_updates_grace.py -v`
Expected: FAIL (grace isn't set).

- [ ] **Step 3: Update `patch_single_config` in `routers/updates.py`**

In `apps/backend/routers/updates.py`, update the import line near the top:

```python
from core.repositories import container_repo, update_repo
```

Then modify `patch_single_config` (around line 148) to set the grace before the patch:

```python
async def patch_single_config(
    owner_id: str,
    body: ConfigPatchRequest,
    auth: AuthContext = Depends(get_current_user),
):
    if auth.is_org_context:
        require_org_admin(auth)

    # Tell the reconciler to stand down for 5s while we apply an admin override.
    await container_repo.set_reconciler_grace(owner_id, seconds=5)

    try:
        await patch_openclaw_config(owner_id, body.patch)
    except ConfigPatchError as e:
        raise HTTPException(status_code=404, detail=str(e))

    put_metric("update.config_patch.applied", dimensions={"scope": "single"})
    return {"status": "patched", "owner_id": owner_id, "keys": list(body.patch.keys())}
```

Do the same inside the fleet patch loop (`patch_fleet_config`, around line 171 — for each `oid` iterated):

```python
    for oid in owners:
        try:
            await container_repo.set_reconciler_grace(oid, seconds=5)
            await patch_openclaw_config(oid, body.patch)
            patched += 1
        except ConfigPatchError:
            failed += 1
            logger.warning("Skipped config patch for owner %s (no config file)", oid)
        except Exception:
            failed += 1
            logger.exception("Failed to patch config for owner %s", oid)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd apps/backend && uv run pytest tests/unit/routers/test_updates_grace.py tests/unit/routers/test_config_router.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/routers/updates.py apps/backend/tests/unit/routers/test_updates_grace.py
git commit -m "feat(routers/updates): set reconciler grace window on admin config patches"
```

---

## Task 15: Lifespan — start reconciler in `main.py`

**Files:**
- Modify: `apps/backend/main.py`

- [ ] **Step 1: Add startup + shutdown hooks**

In `apps/backend/main.py`, modify the `lifespan` async context manager (currently around lines 44-80):

Add this block inside `lifespan` right after the `idle_checker_task = asyncio.create_task(_safe_idle_checker())` line (around line 64):

```python
    from core.services.config_reconciler import ConfigReconciler

    reconciler = ConfigReconciler(efs_mount=settings.EFS_MOUNT_PATH)

    async def _safe_reconciler():
        if settings.CONFIG_RECONCILER_MODE == "off":
            logger.info("config_reconciler disabled (CONFIG_RECONCILER_MODE=off)")
            return
        try:
            await reconciler.run_forever()
        except Exception:
            logger.exception("config_reconciler crashed")

    reconciler_task = asyncio.create_task(_safe_reconciler())
```

And add the shutdown block before `await shutdown_containers()` (around line 80):

```python
    reconciler.stop()
    try:
        await reconciler_task
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 2: Verify startup logs**

Run: `cd apps/backend && uv run python -c "from main import app; print('ok')"`
Expected: prints `ok` with no exceptions.

- [ ] **Step 3: Quick smoke: import reconciler module**

Run: `cd apps/backend && uv run python -c "from core.services.config_reconciler import ConfigReconciler; r = ConfigReconciler('/tmp'); print(r)"`
Expected: prints the reconciler object, no import errors.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/main.py
git commit -m "feat(main): start config reconciler in lifespan task"
```

---

## Task 16: Fleet cleanup script

**Files:**
- Create: `apps/backend/scripts/reconcile_all_configs.py`

- [ ] **Step 1: Write the script**

Create `apps/backend/scripts/reconcile_all_configs.py`:

```python
"""One-shot fleet cleanup for config policy drift.

Runs synchronously. Walks every active container, evaluates its openclaw.json
against the tier policy, and reverts drift on locked fields. Prints a
summary report at the end.

Usage (from apps/backend/):
    uv run python scripts/reconcile_all_configs.py [--dry-run]

Dry-run prints what WOULD be reverted without writing. Use before flipping
CONFIG_RECONCILER_MODE to enforce to confirm the blast radius.
"""

import argparse
import asyncio
import json
import logging
import os

from core.config import settings
from core.containers.config import read_openclaw_config_from_efs
from core.repositories import billing_repo, container_repo
from core.services import config_policy
from core.services.config_patcher import _locked_rmw

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("reconcile_all")


async def reconcile_owner(owner_id: str, dry_run: bool) -> tuple[str, list[str]]:
    account = await billing_repo.get_by_owner_id(owner_id)
    tier = account.get("plan_tier", "free") if isinstance(account, dict) else "free"

    config = await read_openclaw_config_from_efs(owner_id)
    if config is None:
        return ("no_config", [])

    violations = config_policy.evaluate(config, tier)
    if not violations:
        return ("clean", [])

    fields = [v["field"] for v in violations]
    if dry_run:
        return ("would_revert", fields)

    def _mutate(current: dict) -> bool:
        vs = config_policy.evaluate(current, tier)
        if not vs:
            return False
        reverted = config_policy.apply_reverts(current, vs)
        current.clear()
        current.update(reverted)
        return True

    await _locked_rmw(owner_id, _mutate, "fleet_cleanup")
    return ("reverted", fields)


async def main(dry_run: bool) -> None:
    owners = await container_repo.list_active_owners()
    logger.info("found %d active containers", len(owners))

    counts = {"clean": 0, "no_config": 0, "would_revert": 0, "reverted": 0, "error": 0}
    for owner_id in owners:
        try:
            status, fields = await reconcile_owner(owner_id, dry_run)
            counts[status] = counts.get(status, 0) + 1
            if fields:
                logger.info("%s owner=%s fields=%s", status, owner_id, fields)
        except Exception as e:
            counts["error"] += 1
            logger.exception("error on owner=%s: %s", owner_id, e)

    logger.info("summary: %s", counts)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Report what would be reverted, do not write.")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
```

- [ ] **Step 2: Verify it imports cleanly**

Run: `cd apps/backend && uv run python -c "import scripts.reconcile_all_configs as m; print(m.__doc__[:60])"`
Expected: prints the first ~60 chars of the docstring, no import error.

- [ ] **Step 3: Run against empty local (expect no-op summary)**

If you have a local backend mount available, run:
`cd apps/backend && EFS_MOUNT_PATH=/tmp/empty uv run python scripts/reconcile_all_configs.py --dry-run`
Expected: prints `found 0 active containers` (assuming local DDB has no containers) and `summary: {'clean': 0, ...}`.

If you don't have a local env configured, skip this — the script is tested transitively by the reconciler unit + integration tests.

- [ ] **Step 4: Commit**

```bash
git add apps/backend/scripts/reconcile_all_configs.py
git commit -m "feat(scripts): one-shot fleet reconciliation with --dry-run"
```

---

## Task 17: E2E — Playwright test for agent-driven drift revert

**Files:**
- Modify: `apps/frontend/tests/e2e/` (exact test file naming follows existing conventions — check `apps/frontend/tests/e2e/` for patterns first)

- [ ] **Step 1: Locate the existing E2E test directory**

Run: `ls apps/frontend/tests/e2e/ 2>/dev/null || ls apps/frontend/e2e/ 2>/dev/null || find apps/frontend -name '*.spec.ts' -type f | head -10`

Note the naming convention and any helpers used (e.g. login fixture, agent-chat page object).

- [ ] **Step 2: Write the failing test**

Create (or append to the appropriate existing file) an e2e test following the existing conventions. Minimum coverage:

```typescript
// Near existing e2e specs, e.g. apps/frontend/tests/e2e/config-policy.spec.ts
import { test, expect } from "@playwright/test";

test("agent config edits to non-locked fields persist", async ({ page }) => {
  // Login + navigate to chat. Use your existing test-login fixture.
  await loginAsTestUser(page);
  await page.goto("/chat");

  // Ask agent to add a cron job (non-locked field).
  await page.getByPlaceholder(/message your agent/i).fill(
    "Please add a cron job that runs daily at 9am. Just confirm you've done it."
  );
  await page.keyboard.press("Enter");

  // Wait for the agent's response confirming the change.
  await expect(page.getByText(/cron|scheduled|added/i)).toBeVisible({ timeout: 60_000 });

  // Small wait past the reconciler tick so any revert would have fired.
  await page.waitForTimeout(2500);

  // Re-open the config panel; confirm cron is still there.
  await page.getByRole("button", { name: /config|settings/i }).click();
  await expect(page.getByText(/cron/i)).toBeVisible();
});

test("agent attempt to switch primary model gets reverted", async ({ page }) => {
  await loginAsTestUser(page);
  await page.goto("/chat");

  await page.getByPlaceholder(/message your agent/i).fill(
    "Switch your primary model to amazon-bedrock/qwen.qwen3-vl-235b-a22b and confirm."
  );
  await page.keyboard.press("Enter");

  // Wait for the agent's attempt to resolve.
  await page.waitForTimeout(5_000);

  // Send a follow-up — the reconciler should have reverted the primary by now.
  // We verify via the gateway RPC snapshot if the UI exposes it, OR by asking
  // the agent which model it's about to use. (Pick whichever matches your
  // existing E2E conventions — both are valid.)

  await page.getByPlaceholder(/message your agent/i).fill(
    "What model are you currently using as your primary?"
  );
  await page.keyboard.press("Enter");

  await expect(page.getByText(/minimax/i)).toBeVisible({ timeout: 60_000 });
});
```

Replace `loginAsTestUser` with the project's existing login helper.

- [ ] **Step 3: Run the test**

Run: `cd apps/frontend && pnpm run test:e2e`
Expected: Both tests PASS against a deployment with `CONFIG_RECONCILER_MODE=enforce`.

Note: These E2E tests implicitly depend on the reconciler being in `enforce` mode. In CI, ensure the test env has `CONFIG_RECONCILER_MODE=enforce` set; in other environments they're expected to be skipped or run against a staging deploy with the mode enabled.

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/tests/e2e/config-policy.spec.ts
git commit -m "test(e2e): config policy enforcement (non-locked persists, locked reverts)"
```

---

## Task 18: Rollout — phase A deploy, phase B enforce

This is the deploy/ops task, not a code task. Checklist for the operator:

- [ ] **Step 1: Deploy with `CONFIG_RECONCILER_MODE=report`**

Set `CONFIG_RECONCILER_MODE=report` in the backend service env (CDK service-stack or wherever env vars live for the backend ECS service). Deploy.

- [ ] **Step 2: Observe ~24 hours of `report`-mode telemetry**

Check CloudWatch for:
- `config.drift.reported` metric emission — any owner drifts?
- `config.reconciler.tick.duration` — loop latency at real fleet size (should be well under the 1s interval)
- `config.reconciler.errors` by `kind` — should be near-zero

Investigate any spikes. False positives (legal configs flagged as illegal) must be fixed in `config_policy.evaluate` before advancing.

- [ ] **Step 3: Run the fleet cleanup script (dry-run first)**

```bash
cd apps/backend && uv run python scripts/reconcile_all_configs.py --dry-run
```

Review the report. If blast radius is acceptable, run for real:

```bash
cd apps/backend && uv run python scripts/reconcile_all_configs.py
```

- [ ] **Step 4: Flip `CONFIG_RECONCILER_MODE=enforce` and redeploy**

After the cleanup run, flip the env var and redeploy. Post-flip, monitor:
- `config.drift.reverted` by `tier` — expected to be near-zero on steady state; spikes indicate agent tampering attempts.
- Support tickets / user reports of "my agent can't change X" — confirm that X is a non-locked field (should never happen by design).

---

## Spec coverage check

Every requirement from the spec maps to a task:

- `core/services/config_policy.py` → Tasks 1-6
- `core/services/config_reconciler.py` → Tasks 9-11 (+12 integration)
- `routers/config.py` shared policy → Task 13
- `routers/updates.py` admin grace → Task 14
- `main.py` lifespan → Task 15
- `core/config.py` `CONFIG_RECONCILER_MODE` → Task 8
- `scripts/reconcile_all_configs.py` → Task 16
- `containers.reconciler_grace_until` DDB field → Task 7
- Unit tests (policy) → Tasks 1-6
- Unit tests (reconciler) → Tasks 9-11
- Integration tests → Task 12
- API tests → Task 13
- E2E tests → Task 17
- Rollout phase A / B → Task 18

No spec items left unimplemented.
