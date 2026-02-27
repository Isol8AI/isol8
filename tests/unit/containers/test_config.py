"""Tests for OpenClaw container config generation."""

import json


from core.containers.config import (
    write_openclaw_config,
    patch_openclaw_config,
    _deep_merge,
)


class TestWriteOpenclawConfig:
    """Test openclaw.json generation."""

    def test_generates_valid_json(self):
        """Config output is valid JSON."""
        result = write_openclaw_config()
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_default_region(self):
        """Default region is us-east-1."""
        config = json.loads(write_openclaw_config())
        bedrock = config["models"]["providers"]["amazon-bedrock"]
        assert "us-east-1" in bedrock["baseUrl"]

    def test_custom_region(self):
        """Custom region is reflected in Bedrock URL."""
        config = json.loads(write_openclaw_config(region="eu-west-1"))
        bedrock = config["models"]["providers"]["amazon-bedrock"]
        assert "eu-west-1" in bedrock["baseUrl"]

    def test_brave_search_disabled_by_default(self):
        """Brave search is disabled when no API key provided."""
        config = json.loads(write_openclaw_config())
        assert config["tools"]["web"]["search"]["enabled"] is False

    def test_brave_search_enabled_with_key(self):
        """Brave search is enabled when API key is provided."""
        config = json.loads(write_openclaw_config(brave_api_key="test-key"))
        assert config["tools"]["web"]["search"]["enabled"] is True
        assert config["tools"]["web"]["search"]["provider"] == "brave"

    def test_gateway_mode_local(self):
        """Gateway mode is local with no auth."""
        config = json.loads(write_openclaw_config())
        assert config["gateway"]["mode"] == "local"
        assert config["gateway"]["auth"]["mode"] == "none"

    def test_chat_completions_enabled(self):
        """Chat completions endpoint is enabled."""
        config = json.loads(write_openclaw_config())
        endpoints = config["gateway"]["http"]["endpoints"]
        assert endpoints["chatCompletions"]["enabled"] is True

    def test_bedrock_discovery_disabled(self):
        """Bedrock discovery is disabled (we configure models explicitly)."""
        config = json.loads(write_openclaw_config())
        assert config["models"]["bedrockDiscovery"]["enabled"] is False

    def test_memory_search_enabled(self):
        """Memory search is enabled by default."""
        config = json.loads(write_openclaw_config())
        mem = config["agents"]["defaults"]["memorySearch"]
        assert mem["enabled"] is True
        assert mem["provider"] == "bedrock"
        assert "memory" in mem["sources"]
        assert "sessions" in mem["sources"]

    def test_browser_disabled(self):
        """Browser automation is disabled by default."""
        config = json.loads(write_openclaw_config())
        assert config["browser"]["enabled"] is False

    def test_update_check_disabled(self):
        """Auto-update check is disabled."""
        config = json.loads(write_openclaw_config())
        assert config["update"]["checkOnStart"] is False

    def test_custom_primary_model(self):
        """Custom primary model is set."""
        config = json.loads(write_openclaw_config(primary_model="amazon-bedrock/us.anthropic.claude-3-5-sonnet-v2"))
        model = config["agents"]["defaults"]["model"]["primary"]
        assert model == "amazon-bedrock/us.anthropic.claude-3-5-sonnet-v2"

    def test_bedrock_auth_is_aws_sdk(self):
        """Bedrock provider uses aws-sdk auth (IAM role)."""
        config = json.loads(write_openclaw_config())
        bedrock = config["models"]["providers"]["amazon-bedrock"]
        assert bedrock["auth"] == "aws-sdk"


class TestPatchOpenclawConfig:
    """Test config patching/merging."""

    def test_shallow_override(self):
        """Top-level keys are replaced."""
        base = {"gateway": {"mode": "local"}, "browser": {"enabled": False}}
        patch = {"browser": {"enabled": True}}
        result = patch_openclaw_config(base, patch)
        assert result["browser"]["enabled"] is True
        assert result["gateway"]["mode"] == "local"  # unchanged

    def test_deep_merge_nested(self):
        """Nested dicts are deep-merged."""
        base = {
            "tools": {
                "web": {"search": {"enabled": False, "provider": "brave"}},
                "media": {"image": {"enabled": False}},
            }
        }
        patch = {
            "tools": {
                "web": {"search": {"enabled": True}},
            }
        }
        result = patch_openclaw_config(base, patch)
        assert result["tools"]["web"]["search"]["enabled"] is True
        assert result["tools"]["web"]["search"]["provider"] == "brave"  # preserved
        assert result["tools"]["media"]["image"]["enabled"] is False  # preserved

    def test_new_key_added(self):
        """New keys in patch are added."""
        base = {"gateway": {"mode": "local"}}
        patch = {"newSection": {"key": "value"}}
        result = patch_openclaw_config(base, patch)
        assert result["newSection"]["key"] == "value"

    def test_original_not_mutated(self):
        """Original config dict is not mutated."""
        base = {"gateway": {"mode": "local"}}
        patch = {"gateway": {"mode": "remote"}}
        result = patch_openclaw_config(base, patch)
        assert result["gateway"]["mode"] == "remote"
        assert base["gateway"]["mode"] == "local"  # unchanged


class TestDeepMerge:
    """Test _deep_merge helper."""

    def test_flat_merge(self):
        """Flat dicts are merged."""
        assert _deep_merge({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    def test_override_value(self):
        """Override values replace base values."""
        assert _deep_merge({"a": 1}, {"a": 2}) == {"a": 2}

    def test_nested_merge(self):
        """Nested dicts are recursively merged."""
        base = {"a": {"b": 1, "c": 2}}
        override = {"a": {"c": 3, "d": 4}}
        result = _deep_merge(base, override)
        assert result == {"a": {"b": 1, "c": 3, "d": 4}}

    def test_non_dict_override(self):
        """Non-dict values replace entire base."""
        assert _deep_merge({"a": {"b": 1}}, {"a": "string"}) == {"a": "string"}
