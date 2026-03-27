"""Tests for config patcher — EFS openclaw.json patching."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")


@pytest.fixture
def efs_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        user_dir = os.path.join(tmpdir, "user_1")
        os.makedirs(user_dir)
        config = {
            "gateway": {"mode": "local", "bind": "lan"},
            "agents": {
                "defaults": {
                    "model": {"primary": "amazon-bedrock/minimax.minimax-m2.1"},
                    "models": {
                        "amazon-bedrock/minimax.minimax-m2.1": {"alias": "MiniMax M2.1"},
                    },
                }
            },
            "tools": {"profile": "full"},
        }
        with open(os.path.join(user_dir, "openclaw.json"), "w") as f:
            json.dump(config, f)

        with patch("core.services.config_patcher._efs_mount_path", tmpdir):
            yield tmpdir


@pytest.mark.asyncio
async def test_patch_updates_model(efs_dir):
    from core.services.config_patcher import patch_openclaw_config

    await patch_openclaw_config(
        "user_1", {"agents": {"defaults": {"model": {"primary": "amazon-bedrock/moonshotai.kimi-k2.5"}}}}
    )
    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        result = json.load(f)
    assert result["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/moonshotai.kimi-k2.5"


@pytest.mark.asyncio
async def test_patch_preserves_gateway(efs_dir):
    from core.services.config_patcher import patch_openclaw_config

    await patch_openclaw_config("user_1", {"agents": {"defaults": {"model": {"primary": "new-model"}}}})
    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        result = json.load(f)
    assert result["gateway"]["mode"] == "local"
    assert result["gateway"]["bind"] == "lan"


@pytest.mark.asyncio
async def test_patch_preserves_tools(efs_dir):
    from core.services.config_patcher import patch_openclaw_config

    await patch_openclaw_config("user_1", {"agents": {"defaults": {"model": {"primary": "new-model"}}}})
    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        result = json.load(f)
    assert result["tools"]["profile"] == "full"


@pytest.mark.asyncio
async def test_patch_creates_backup(efs_dir):
    from core.services.config_patcher import patch_openclaw_config

    await patch_openclaw_config("user_1", {"agents": {"defaults": {"model": {"primary": "new-model"}}}})
    backup = os.path.join(efs_dir, "user_1", "openclaw.json.bak")
    assert os.path.exists(backup)
    with open(backup) as f:
        original = json.load(f)
    assert original["agents"]["defaults"]["model"]["primary"] == "amazon-bedrock/minimax.minimax-m2.1"


@pytest.mark.asyncio
async def test_patch_deep_merges_models(efs_dir):
    from core.services.config_patcher import patch_openclaw_config

    await patch_openclaw_config(
        "user_1",
        {"agents": {"defaults": {"models": {"amazon-bedrock/moonshotai.kimi-k2.5": {"alias": "Kimi K2.5"}}}}},
    )
    with open(os.path.join(efs_dir, "user_1", "openclaw.json")) as f:
        result = json.load(f)
    models = result["agents"]["defaults"]["models"]
    assert "amazon-bedrock/moonshotai.kimi-k2.5" in models
    assert "amazon-bedrock/minimax.minimax-m2.1" in models


@pytest.mark.asyncio
async def test_patch_nonexistent_owner_raises(efs_dir):
    from core.services.config_patcher import patch_openclaw_config, ConfigPatchError

    with pytest.raises(ConfigPatchError, match="not found"):
        await patch_openclaw_config("nonexistent_user", {"agents": {}})
