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
