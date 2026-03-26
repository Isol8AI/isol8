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

    def test_config_uses_perplexity_plugin_for_search(self):
        """Search uses Perplexity plugin with proxy baseUrl (v2026.3.22+ format)."""
        config = json.loads(
            write_openclaw_config(
                gateway_token="tok_abc123",
            )
        )
        # tools.web.search just enables + sets provider
        search = config["tools"]["web"]["search"]
        assert search["enabled"] is True
        assert search["provider"] == "perplexity"
        # Actual config lives in plugins.entries.perplexity
        plugin = config["plugins"]["entries"]["perplexity"]
        assert plugin["enabled"] is True
        assert plugin["config"]["webSearch"]["apiKey"] == "tok_abc123"
        assert "proxy/search" in plugin["config"]["webSearch"]["baseUrl"]

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
        """Gateway mode is local with trusted-proxy auth."""
        config = json.loads(write_openclaw_config())
        assert config["gateway"]["mode"] == "local"
        assert config["gateway"]["auth"]["mode"] == "trusted-proxy"
        assert config["gateway"]["auth"]["trustedProxy"]["userHeader"] == "x-forwarded-user"
        assert config["gateway"]["trustedProxies"] == ["10.0.0.0/8", "127.0.0.1", "::1"]

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

    def test_free_tier_single_model_catalog(self):
        """Free tier catalog has only MiniMax model."""
        config = json.loads(write_openclaw_config())
        models = config["agents"]["defaults"]["models"]
        assert len(models) == 1
        primary = config["agents"]["defaults"]["model"]["primary"]
        assert primary in models
        assert "minimax" in primary

    def test_enterprise_tier_models_catalog_populated(self):
        """Enterprise tier catalog has entries for all models."""
        config = json.loads(write_openclaw_config(tier="enterprise"))
        models = config["agents"]["defaults"]["models"]
        assert len(models) >= 3
        primary = config["agents"]["defaults"]["model"]["primary"]
        assert primary in models

    def test_multiple_bedrock_models_configured(self):
        """Multiple Bedrock models are pre-configured with inference profile IDs (enterprise tier)."""
        config = json.loads(write_openclaw_config(tier="enterprise"))
        models = config["models"]["providers"]["amazon-bedrock"]["models"]
        assert len(models) >= 4
        model_ids = [m["id"] for m in models]
        assert "us.anthropic.claude-opus-4-6-v1" in model_ids
        assert "us.anthropic.claude-opus-4-5-20251101-v1:0" in model_ids
        assert "us.anthropic.claude-sonnet-4-5-20250929-v1:0" in model_ids
        assert "us.anthropic.claude-haiku-4-5-20251001-v1:0" in model_ids

    def test_starter_tier_models(self):
        """Starter tier includes MiniMax and Kimi only."""
        config = json.loads(write_openclaw_config(tier="starter"))
        models = config["models"]["providers"]["amazon-bedrock"]["models"]
        model_ids = [m["id"] for m in models]
        assert "us.minimax.minimax-m2-1-v1:0" in model_ids
        assert "us.moonshotai.kimi-k2-5-v1:0" in model_ids
        assert len(models) == 2

    def test_memory_search_enabled(self):
        """Memory search is enabled (QMD handles embeddings locally)."""
        config = json.loads(write_openclaw_config())
        mem = config["agents"]["defaults"]["memorySearch"]
        assert mem["enabled"] is True

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

    def test_memory_qmd_backend(self):
        """Memory backend is QMD with proper config."""
        config = json.loads(write_openclaw_config())
        memory = config["memory"]
        assert memory["backend"] == "qmd"
        assert memory["citations"] == "auto"
        assert memory["qmd"]["command"] == "/home/node/.npm-global/bin/qmd"
        assert memory["qmd"]["includeDefaultMemory"] is True
        assert memory["qmd"]["searchMode"] == "search"

    def test_skills_no_allowlist(self):
        """Skills section has no allowBundled (all bundled skills allowed)."""
        config = json.loads(write_openclaw_config())
        assert "skills" in config
        assert "allowBundled" not in config["skills"]

    def test_skills_node_manager(self):
        """Skills install uses npm as node manager."""
        config = json.loads(write_openclaw_config())
        assert config["skills"]["install"]["nodeManager"] == "npm"

    def test_ollama_provider(self):
        """write_openclaw_config with provider='ollama' uses native Ollama config."""
        config_json = write_openclaw_config(
            provider="ollama",
            ollama_base_url="http://ollama:11434",
            primary_model="ollama/qwen2.5:14b",
            gateway_token="test-token",
        )
        config = json.loads(config_json)

        providers = config["models"]["providers"]
        assert "ollama" in providers
        assert "amazon-bedrock" not in providers

        ollama = providers["ollama"]
        assert ollama["baseUrl"] == "http://ollama:11434"
        assert ollama["api"] == "ollama"
        assert ollama["apiKey"] == "ollama-local"
        assert len(ollama["models"]) > 0

        assert config["agents"]["defaults"]["model"]["primary"] == "ollama/qwen2.5:14b"
        assert config["models"]["bedrockDiscovery"]["enabled"] is False

    def test_default_provider_is_bedrock(self):
        """write_openclaw_config without provider arg still uses Bedrock."""
        config_json = write_openclaw_config(gateway_token="test-token")
        config = json.loads(config_json)

        providers = config["models"]["providers"]
        assert "amazon-bedrock" in providers
        assert "ollama" not in providers


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
