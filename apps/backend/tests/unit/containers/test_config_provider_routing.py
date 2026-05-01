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
    # OpenClaw's openai-codex provider has no JSON config knob for the
    # auth dir — it reads the CODEX_HOME env var (set on the per-user ECS
    # task in ecs_manager). The provider block is omitted entirely so the
    # base schema validator (which requires baseUrl + models on a populated
    # entry) doesn't reject the empty `{}` we'd otherwise emit.
    assert "openai-codex" not in cfg["models"].get("providers", {})


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
    fallbacks = cfg["agents"]["defaults"]["model"]["fallbacks"]
    assert primary == "anthropic/claude-opus-4-7"
    assert fallbacks == ["anthropic/claude-sonnet-4-6"]
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
async def test_chatgpt_oauth_writes_cli_backend_for_codex(tmp_path):
    """Without `cliBackends['openai-codex']` in agents.defaults, upstream's
    isConfiguredCliBackendPrimary returns false and prewarmConfiguredPrimaryModel
    falls through to a network-bound model resolver that hangs ~5min on cold
    start (ChatGPT OAuth tokens aren't accepted by api.openai.com). Empty
    `{}` is enough — upstream only iterates the keys."""
    out = tmp_path / "openclaw.json"
    await write_openclaw_config(
        config_path=out,
        gateway_token="test-token",
        provider_choice="chatgpt_oauth",
        user_id="u_1",
    )
    cfg = json.loads(out.read_text())
    cli_backends = cfg["agents"]["defaults"].get("cliBackends", {})
    assert "openai-codex" in cli_backends, (
        "chatgpt_oauth must register openai-codex as a CLI backend so the "
        "gateway's isCliProvider check short-circuits prewarm before its "
        "5-min model-resolution hang"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_choice,byo_provider,expected_provider,expected_model",
    [
        ("chatgpt_oauth", None, "openai", "text-embedding-3-small"),
        ("byo_key", "openai", "openai", "text-embedding-3-small"),
        ("byo_key", "anthropic", "bedrock", "amazon.titan-embed-text-v2:0"),
        ("bedrock_claude", None, "bedrock", "amazon.titan-embed-text-v2:0"),
    ],
)
async def test_memory_search_provider_matches_auth_path(
    tmp_path, provider_choice, byo_provider, expected_provider, expected_model
):
    """memorySearch must NEVER be left at upstream default (provider='local')
    because that requires a GGUF model file we don't ship — qmd then hangs
    ~3min (120s embed timeout + 60s backoff) on first embed call."""
    kwargs = {
        "config_path": tmp_path / "openclaw.json",
        "gateway_token": "test-token",
        "provider_choice": provider_choice,
        "user_id": "u_1",
    }
    if byo_provider is not None:
        kwargs["byo_provider"] = byo_provider
    await write_openclaw_config(**kwargs)
    cfg = json.loads((tmp_path / "openclaw.json").read_text())
    memory_search = cfg["agents"]["defaults"]["memorySearch"]
    assert memory_search["enabled"] is True
    assert memory_search["provider"] == expected_provider
    assert memory_search["model"] == expected_model


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


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_token", ["", None])
async def test_empty_gateway_token_raises(tmp_path, bad_token):
    """Empty/None gateway_token must fail fast — never silently write a null auth."""
    out = tmp_path / "openclaw.json"
    with pytest.raises(ValueError, match="gateway_token must be a non-empty string"):
        await write_openclaw_config(
            config_path=out,
            gateway_token=bad_token,
            provider_choice="bedrock_claude",
            user_id="u_1",
        )
