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
