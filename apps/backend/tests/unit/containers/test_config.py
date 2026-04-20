"""Tests for OpenClaw container config generation."""

import json


from core.containers.config import (
    write_openclaw_config,
    write_mcporter_config,
    merge_openclaw_config,
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

    def test_config_full_profile_denies_canvas_nodes(self):
        """Tools profile is full; canvas and nodes denied by default.

        The `nodes` tool is toggled to enabled at runtime by
        routers/node_proxy.py when a desktop node pairs; leaving it
        always-allowed here would expose it to users without the
        desktop app.
        """
        config = json.loads(write_openclaw_config())
        assert config["tools"]["profile"] == "full"
        assert "canvas" in config["tools"]["deny"]
        assert "nodes" in config["tools"]["deny"]

    def test_config_exec_approval_policy(self):
        """Exec uses allowlist + on-miss so the approval card can fire.

        Without this, OpenClaw's default security=deny blocks every exec
        call silently (exec-defaults.ts:98). See
        docs/superpowers/specs/2026-04-18-exec-approval-card-design.md.
        """
        config = json.loads(write_openclaw_config())
        exec_cfg = config["tools"]["exec"]
        assert exec_cfg["security"] == "allowlist"
        assert exec_cfg["ask"] == "on-miss"

    def test_build_backend_policy_patch_includes_exec(self):
        """The shared helper used by PATCH /debug/provision writes the
        same exec policy as the initial write — one source of truth."""
        from core.containers.config import build_backend_policy_patch

        patch = build_backend_policy_patch("starter")
        assert patch["tools"]["exec"]["security"] == "allowlist"
        assert patch["tools"]["exec"]["ask"] == "on-miss"
        # Must NOT include list-valued fields — deep-merge replaces
        # arrays wholesale, which would clobber node_proxy's dynamic
        # tools.deny toggling.
        assert "deny" not in patch["tools"]
        # Model + agent defaults are still carried.
        assert "providers" in patch["models"]
        assert "defaults" in patch["agents"]

    def test_no_root_tts_key(self):
        """TTS config is not at root level (OpenClaw doesn't support it there)."""
        config = json.loads(write_openclaw_config())
        assert "tts" not in config

    def test_config_image_understanding_enabled(self):
        """Image understanding is enabled in media tools."""
        config = json.loads(write_openclaw_config())
        assert config["tools"]["media"]["image"]["enabled"] is True

    def test_gateway_mode_local(self):
        """Gateway uses token auth (trusted-proxy blocks loopback — see #17761)."""
        config = json.loads(write_openclaw_config(gateway_token="test-token-123"))
        assert config["gateway"]["mode"] == "local"
        assert config["gateway"]["auth"]["mode"] == "token"
        assert config["gateway"]["auth"]["token"] == "test-token-123"
        assert "trustedProxy" not in config["gateway"]["auth"]
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

    def test_bedrock_discovery_disabled(self):
        """Bedrock discovery is disabled — we control the model catalog via config.

        OpenClaw 4.5 moved this from `models.bedrockDiscovery` to
        `plugins.entries.amazon-bedrock.config.discovery`.
        """
        config = json.loads(write_openclaw_config())
        plugin = config["plugins"]["entries"]["amazon-bedrock"]
        assert plugin["config"]["discovery"]["enabled"] is False
        # Legacy key must NOT be present — OpenClaw 4.5 doctor flags it as
        # "Unrecognized key" and the migration runs at startup.
        assert "bedrockDiscovery" not in config.get("models", {})

    def test_free_tier_single_model_catalog(self):
        """Free tier catalog has only MiniMax model."""
        config = json.loads(write_openclaw_config())
        models = config["agents"]["defaults"]["models"]
        assert len(models) == 1
        primary = config["agents"]["defaults"]["model"]["primary"]
        assert primary in models
        assert "minimax" in primary

    def test_enterprise_tier_models_catalog_populated(self):
        """Enterprise tier catalog has the supported models (MiniMax + Qwen3 VL)."""
        config = json.loads(write_openclaw_config(tier="enterprise"))
        models = config["agents"]["defaults"]["models"]
        # Post-2026-04-09 we trimmed the catalog to the two models we
        # actively ship. Enterprise no longer gets Claude/Llama/Nova/etc.
        assert len(models) == 2
        primary = config["agents"]["defaults"]["model"]["primary"]
        assert primary in models

    def test_catalog_has_only_minimax_and_qwen(self):
        """Enterprise tier exposes exactly the two supported models."""
        config = json.loads(write_openclaw_config(tier="enterprise"))
        models = config["models"]["providers"]["amazon-bedrock"]["models"]
        model_ids = sorted(m["id"] for m in models)
        assert model_ids == ["minimax.minimax-m2.5", "qwen.qwen3-vl-235b-a22b"]

    def test_no_claude_models_in_catalog(self):
        """Claude models were removed from the catalog on cost grounds (2026-04-09)."""
        config = json.loads(write_openclaw_config(tier="enterprise"))
        models = config["models"]["providers"]["amazon-bedrock"]["models"]
        model_ids = [m["id"] for m in models]
        assert not any("anthropic" in mid or "claude" in mid for mid in model_ids)

    def test_qwen_supports_image_input(self):
        """Qwen3 VL declares image input so OpenClaw doesn't silently drop
        chat attachments. The text-only variants get filtered at transport
        layer per `src/agents/google-transport-stream.ts:302` in the
        OpenClaw reference; we explicitly picked VL for chat."""
        config = json.loads(write_openclaw_config(tier="starter"))
        models = config["models"]["providers"]["amazon-bedrock"]["models"]
        qwen = next(m for m in models if m["id"] == "qwen.qwen3-vl-235b-a22b")
        assert "image" in qwen["input"]

    def test_minimax_declared_as_reasoning_model(self):
        """MiniMax M2.5 emits reasoningContent blocks — the flag tells
        OpenClaw to budget thinking tokens separately so short prompts
        don't exhaust the output cap mid-chain-of-thought."""
        config = json.loads(write_openclaw_config(tier="starter"))
        models = config["models"]["providers"]["amazon-bedrock"]["models"]
        minimax = next(m for m in models if m["id"] == "minimax.minimax-m2.5")
        assert minimax["reasoning"] is True

    def test_starter_tier_models(self):
        """Starter tier includes MiniMax M2.5 and Qwen3 VL 235B only."""
        config = json.loads(write_openclaw_config(tier="starter"))
        models = config["models"]["providers"]["amazon-bedrock"]["models"]
        model_ids = [m["id"] for m in models]
        assert "minimax.minimax-m2.5" in model_ids
        assert "qwen.qwen3-vl-235b-a22b" in model_ids
        assert len(models) == 2

    def test_memory_search_enabled(self):
        """Memory search is enabled (QMD handles embeddings locally)."""
        config = json.loads(write_openclaw_config())
        mem = config["agents"]["defaults"]["memorySearch"]
        assert mem["enabled"] is True

    def test_agents_defaults_workspace_routes_to_efs(self):
        """New agent workspaces must land under `.openclaw/` so they live on EFS."""
        config = json.loads(write_openclaw_config())
        assert config["agents"]["defaults"]["workspace"] == "/home/node/.openclaw/workspaces"

    def test_main_agent_has_absolute_workspace(self):
        """Main agent workspace must be absolute so path.resolve() returns it
        unchanged regardless of process cwd. Agent exec tools run with
        cwd=workspaceDir, which breaks relative resolution (skills install
        to a nested path instead of {workspace}/skills/).
        """
        config = json.loads(write_openclaw_config())
        main_entry = next(a for a in config["agents"]["list"] if a.get("id") == "main")
        assert main_entry.get("workspace") == "/home/node/.openclaw/workspaces/main"

    def test_config_browser_enabled_with_user_profile(self):
        """Browser tool uses the user profile (attach to real Chrome)."""
        config = json.loads(write_openclaw_config())
        browser = config["browser"]
        assert browser["enabled"] is True
        assert browser["defaultProfile"] == "user"
        assert browser["profiles"]["user"]["driver"] == "existing-session"

    def test_config_node_host_browser_proxy_enabled(self):
        """Gateway auto-routes browser tool calls to the paired node."""
        config = json.loads(write_openclaw_config())
        assert config["nodeHost"]["browserProxy"]["enabled"] is True

    def test_build_backend_policy_patch_includes_browser(self):
        """Refresh path carries the full browser block, not just scalars.

        Without `profiles.user.driver`, a deep-merge onto a pre-browser
        container leaves `defaultProfile = "user"` pointing at an
        undefined profile.
        """
        from core.containers.config import build_backend_policy_patch

        patch = build_backend_policy_patch("starter")
        assert patch["browser"]["enabled"] is True
        assert patch["browser"]["defaultProfile"] == "user"
        assert patch["browser"]["profiles"]["user"]["driver"] == "existing-session"
        assert patch["nodeHost"]["browserProxy"]["enabled"] is True

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
        # Plugin discovery stays disabled in ollama mode too (no AWS creds anyway).
        plugin = config["plugins"]["entries"]["amazon-bedrock"]
        assert plugin["config"]["discovery"]["enabled"] is False

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
        result = merge_openclaw_config(base, patch)
        assert result["browser"]["enabled"] is True
        assert result["gateway"]["mode"] == "local"  # unchanged

    def test_deep_merge_nested(self):
        """Nested dicts are deep-merged."""
        base = {
            "tools": {
                "web": {"fetch": {"enabled": False, "timeout": 30}},
                "media": {"image": {"enabled": False}},
            }
        }
        patch = {
            "tools": {
                "web": {"fetch": {"enabled": True}},
            }
        }
        result = merge_openclaw_config(base, patch)
        assert result["tools"]["web"]["fetch"]["enabled"] is True
        assert result["tools"]["web"]["fetch"]["timeout"] == 30  # preserved
        assert result["tools"]["media"]["image"]["enabled"] is False  # preserved

    def test_new_key_added(self):
        """New keys in patch are added."""
        base = {"gateway": {"mode": "local"}}
        patch = {"newSection": {"key": "value"}}
        result = merge_openclaw_config(base, patch)
        assert result["newSection"]["key"] == "value"

    def test_original_not_mutated(self):
        """Original config dict is not mutated."""
        base = {"gateway": {"mode": "local"}}
        patch = {"gateway": {"mode": "remote"}}
        result = merge_openclaw_config(base, patch)
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
