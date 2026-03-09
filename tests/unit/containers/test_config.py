"""Tests for OpenClaw container config generation."""

import json


from core.containers.config import (
    write_openclaw_config,
    write_mcporter_config,
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

    def test_config_search_disabled_without_token(self):
        """Search disabled when no gateway token."""
        config = json.loads(write_openclaw_config(gateway_token=""))
        search = config["tools"]["web"]["search"]
        assert search["enabled"] is False

    def test_config_uses_perplexity_proxy_for_search(self):
        """Search uses Perplexity provider with proxy baseUrl."""
        config = json.loads(
            write_openclaw_config(
                gateway_token="tok_abc123",
            )
        )
        search = config["tools"]["web"]["search"]
        assert search["enabled"] is True
        assert search["provider"] == "perplexity"
        assert search["perplexity"]["apiKey"] == "tok_abc123"
        assert "proxy/search" in search["perplexity"]["baseUrl"]

    def test_config_full_profile_denies_canvas_nodes(self):
        """Tools profile is full and canvas/nodes are denied."""
        config = json.loads(write_openclaw_config())
        assert config["tools"]["profile"] == "full"
        assert "canvas" in config["tools"]["deny"]
        assert "nodes" in config["tools"]["deny"]

    def test_no_root_tts_key(self):
        """TTS config is not at root level (OpenClaw doesn't support it there)."""
        config = json.loads(write_openclaw_config())
        assert "tts" not in config

    def test_config_image_understanding_enabled(self):
        """Image understanding is enabled in media tools."""
        config = json.loads(write_openclaw_config())
        assert config["tools"]["media"]["image"]["enabled"] is True

    def test_gateway_mode_local(self):
        """Gateway mode is local with no auth when no token provided."""
        config = json.loads(write_openclaw_config())
        assert config["gateway"]["mode"] == "local"
        assert config["gateway"]["auth"]["mode"] == "none"

    def test_gateway_auth_token(self):
        """Gateway auth uses token mode when token is provided."""
        config = json.loads(write_openclaw_config(gateway_token="my-secret"))
        assert config["gateway"]["auth"]["mode"] == "token"
        assert config["gateway"]["auth"]["token"] == "my-secret"

    def test_control_ui_disabled(self):
        """Control UI is disabled in production containers."""
        config = json.loads(write_openclaw_config())
        assert config["gateway"]["controlUi"]["enabled"] is False

    def test_chat_completions_disabled(self):
        """Chat completions HTTP endpoint is disabled (we use WebSocket RPC)."""
        config = json.loads(write_openclaw_config())
        endpoints = config["gateway"]["http"]["endpoints"]
        assert endpoints["chatCompletions"]["enabled"] is False

    def test_bedrock_discovery_enabled(self):
        """Bedrock discovery is enabled for runtime model discovery."""
        config = json.loads(write_openclaw_config())
        assert config["models"]["bedrockDiscovery"]["enabled"] is True

    def test_models_catalog_populated(self):
        """Models catalog has entries for the default models."""
        config = json.loads(write_openclaw_config())
        models = config["agents"]["defaults"]["models"]
        assert len(models) >= 3
        primary = config["agents"]["defaults"]["model"]["primary"]
        assert primary in models

    def test_multiple_bedrock_models_configured(self):
        """Multiple Bedrock models are pre-configured with inference profile IDs."""
        config = json.loads(write_openclaw_config())
        models = config["models"]["providers"]["amazon-bedrock"]["models"]
        assert len(models) >= 4
        model_ids = [m["id"] for m in models]
        assert "us.anthropic.claude-opus-4-6-v1" in model_ids
        assert "us.anthropic.claude-opus-4-5-20251101-v1:0" in model_ids
        assert "us.anthropic.claude-sonnet-4-5-20250929-v1:0" in model_ids
        assert "us.anthropic.claude-haiku-4-5-20251001-v1:0" in model_ids

    def test_memory_search_local_embeddings(self):
        """Memory search uses local GGUF embeddings."""
        config = json.loads(write_openclaw_config())
        mem = config["agents"]["defaults"]["memorySearch"]
        assert mem["enabled"] is False

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

    def test_memory_lancedb_plugin_enabled(self):
        """memory-lancedb plugin is configured with embedding proxy."""
        config = json.loads(write_openclaw_config(gateway_token="tok_abc"))
        plugins = config["plugins"]
        assert plugins["slots"]["memory"] == "memory-lancedb"
        entry = plugins["entries"]["memory-lancedb"]
        assert entry["enabled"] is True
        embed = entry["config"]["embedding"]
        assert embed["apiKey"] == "tok_abc"
        assert "proxy/embeddings" in embed["baseUrl"]
        assert embed["dimensions"] == 1024

    def test_memory_lancedb_auto_capture_enabled(self):
        """memory-lancedb has autoCapture and autoRecall enabled."""
        config = json.loads(write_openclaw_config(gateway_token="tok_abc"))
        entry = config["plugins"]["entries"]["memory-lancedb"]
        assert entry["config"]["autoCapture"] is True
        assert entry["config"]["autoRecall"] is True

    def test_memory_lancedb_disabled_without_token(self):
        """memory-lancedb not enabled without gateway token."""
        config = json.loads(write_openclaw_config(gateway_token=""))
        plugins = config["plugins"]
        entry = plugins["entries"]["memory-lancedb"]
        assert entry["enabled"] is False

    def test_skills_no_allowlist(self):
        """Skills section has no allowBundled (all bundled skills allowed)."""
        config = json.loads(write_openclaw_config())
        assert "skills" in config
        assert "allowBundled" not in config["skills"]

    def test_skills_node_manager(self):
        """Skills install uses npm as node manager."""
        config = json.loads(write_openclaw_config())
        assert config["skills"]["install"]["nodeManager"] == "npm"


class TestWriteMcporterConfig:
    """Test mcporter.json generation."""

    def test_generates_valid_json(self):
        """Config output is valid JSON."""
        result = write_mcporter_config()
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_default_empty_servers(self):
        """Default config has empty servers dict."""
        config = json.loads(write_mcporter_config())
        assert config["servers"] == {}

    def test_custom_servers(self):
        """Custom servers are included in output."""
        servers = {
            "github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_test"},
            }
        }
        config = json.loads(write_mcporter_config(servers=servers))
        assert "github" in config["servers"]
        assert config["servers"]["github"]["command"] == "npx"
        assert config["servers"]["github"]["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"] == "ghp_test"

    def test_none_servers_returns_empty(self):
        """None servers argument returns empty servers dict."""
        config = json.loads(write_mcporter_config(servers=None))
        assert config["servers"] == {}


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
                "web": {"search": {"enabled": False, "provider": "perplexity"}},
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
        assert result["tools"]["web"]["search"]["provider"] == "perplexity"  # preserved
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
