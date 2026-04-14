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
