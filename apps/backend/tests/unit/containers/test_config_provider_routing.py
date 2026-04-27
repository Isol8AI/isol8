"""write_openclaw_config emits the correct provider block per provider_choice."""

import json

import pytest

from core.containers.config import write_openclaw_config


@pytest.mark.asyncio
async def test_chatgpt_oauth_branch(tmp_path):
    out = tmp_path / "openclaw.json"
    await write_openclaw_config(
        config_path=out,
        gateway_token="test-token",
        provider_choice="chatgpt_oauth",
        user_id="u_1",
    )
    cfg = json.loads(out.read_text())
    primary = cfg["agents"]["defaults"]["model"]["primary"]
    assert primary == "openai-codex/gpt-5.5"
    # CODEX_HOME points at the user's EFS auth dir.
    assert cfg["models"]["providers"]["openai-codex"]["codexHome"].endswith("/u_1/codex")


@pytest.mark.asyncio
async def test_byo_key_openai_branch(tmp_path):
    out = tmp_path / "openclaw.json"
    await write_openclaw_config(
        config_path=out,
        gateway_token="test-token",
        provider_choice="byo_key",
        byo_provider="openai",
        user_id="u_1",
    )
    cfg = json.loads(out.read_text())
    primary = cfg["agents"]["defaults"]["model"]["primary"]
    assert primary == "openai/gpt-5.4"
    # The OPENAI_API_KEY env var is injected via ECS task secret, not in this file.
    env_block = cfg.get("env", {})
    assert "OPENAI_API_KEY" not in env_block, "API key must NEVER be embedded in openclaw.json — comes from ECS secret"


@pytest.mark.asyncio
async def test_byo_key_anthropic_branch(tmp_path):
    out = tmp_path / "openclaw.json"
    await write_openclaw_config(
        config_path=out,
        gateway_token="test-token",
        provider_choice="byo_key",
        byo_provider="anthropic",
        user_id="u_1",
    )
    cfg = json.loads(out.read_text())
    primary = cfg["agents"]["defaults"]["model"]["primary"]
    subagent = cfg["agents"]["defaults"]["model"]["subagent"]
    assert primary == "anthropic/claude-opus-4-7"
    assert subagent == "anthropic/claude-sonnet-4-6"
    env_block = cfg.get("env", {})
    assert "ANTHROPIC_API_KEY" not in env_block


@pytest.mark.asyncio
async def test_bedrock_claude_branch(tmp_path):
    out = tmp_path / "openclaw.json"
    await write_openclaw_config(
        config_path=out,
        gateway_token="test-token",
        provider_choice="bedrock_claude",
        user_id="u_1",
    )
    cfg = json.loads(out.read_text())
    primary = cfg["agents"]["defaults"]["model"]["primary"]
    assert primary == "amazon-bedrock/anthropic.claude-opus-4-7"
    bedrock_cfg = cfg["plugins"]["entries"]["amazon-bedrock"]["config"]
    assert bedrock_cfg["discovery"]["enabled"] is True


@pytest.mark.asyncio
async def test_byo_key_requires_byo_provider(tmp_path):
    """byo_key without byo_provider raises ValueError."""
    out = tmp_path / "openclaw.json"
    with pytest.raises(ValueError, match="byo_provider"):
        await write_openclaw_config(
            config_path=out,
            gateway_token="test-token",
            provider_choice="byo_key",
            user_id="u_1",
        )


@pytest.mark.asyncio
async def test_unknown_provider_choice_raises(tmp_path):
    out = tmp_path / "openclaw.json"
    with pytest.raises(ValueError, match="Unknown provider_choice"):
        await write_openclaw_config(
            config_path=out,
            gateway_token="test-token",
            provider_choice="totally_made_up",
            user_id="u_1",
        )
