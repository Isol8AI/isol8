"""Tests for config_policy module."""

import json

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
        config["models"]["providers"]["amazon-bedrock"]["models"].append(
            {
                "id": "qwen.qwen3-vl-235b-a22b",
                "name": "Qwen3 VL 235B",
                "contextWindow": 128000,
                "maxTokens": 8192,
                "reasoning": False,
                "input": ["text", "image"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            }
        )
        violations = config_policy.evaluate(config, "free")
        assert any(v["field"] == "models.providers" for v in violations)

    def test_unknown_tier_falls_back_to_free(self):
        raw = write_openclaw_config(gateway_token="t", tier="free")
        config = json.loads(raw)
        # Add qwen — illegal for free
        config["models"]["providers"]["amazon-bedrock"]["models"].append(
            {
                "id": "qwen.qwen3-vl-235b-a22b",
                "name": "X",
                "contextWindow": 1,
                "maxTokens": 1,
                "reasoning": False,
                "input": ["text"],
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            }
        )
        violations = config_policy.evaluate(config, "bogus-tier")
        assert any(v["field"] == "models.providers" for v in violations)

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


class TestRegionDerivation:
    """Tests that _expected_providers derives region from settings.AWS_REGION
    instead of hardcoding us-east-1."""

    def test_providers_baseurl_derived_from_settings_region(self, monkeypatch):
        """If the deploy runs in eu-west-1 (so write_openclaw_config emits
        baseUrl=https://bedrock-runtime.eu-west-1.amazonaws.com), the policy
        expected-providers block must use the same region, otherwise every
        clean config would flip into `models.providers` drift."""
        from core.config import settings

        monkeypatch.setattr(settings, "AWS_REGION", "eu-west-1")

        raw = write_openclaw_config(
            region="eu-west-1",
            gateway_token="t",
            tier="starter",
        )
        config = json.loads(raw)

        violations = config_policy.evaluate(config, "starter")
        fields = [v["field"] for v in violations]
        assert "models.providers" not in fields, (
            f"clean eu-west-1 config should have no providers violation, got {violations}"
        )
