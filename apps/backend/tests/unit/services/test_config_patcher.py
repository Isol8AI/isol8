"""Tests for config patcher — EFS openclaw.json patching."""

import json
import os
import tempfile
from unittest.mock import patch

import pytest

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

from core.services.config_patcher import remove_from_openclaw_config_list  # noqa: E402
from core.services.config_patcher import delete_openclaw_config_path  # noqa: E402


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


@pytest.fixture
def tmp_efs_with_config(monkeypatch):
    """Write a minimal openclaw.json to a tmp 'EFS' dir and point the patcher at it."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr("core.services.config_patcher._efs_mount_path", d)
        owner_id = "user_test"
        owner_dir = os.path.join(d, owner_id)
        os.makedirs(owner_dir)
        config_path = os.path.join(owner_dir, "openclaw.json")
        with open(config_path, "w") as f:
            json.dump({"channels": {"telegram": {"accounts": {"main": {"allowFrom": ["111"]}}}}}, f)
        yield d, owner_id, config_path


@pytest.mark.asyncio
async def test_append_to_list_appends_to_existing(tmp_efs_with_config):
    from core.services.config_patcher import append_to_openclaw_config_list

    _, owner_id, config_path = tmp_efs_with_config
    await append_to_openclaw_config_list(
        owner_id,
        ["channels", "telegram", "accounts", "main", "allowFrom"],
        "222",
    )
    with open(config_path) as f:
        result = json.load(f)
    assert result["channels"]["telegram"]["accounts"]["main"]["allowFrom"] == ["111", "222"]


@pytest.mark.asyncio
async def test_append_to_list_creates_path_when_missing(tmp_efs_with_config):
    from core.services.config_patcher import append_to_openclaw_config_list

    _, owner_id, config_path = tmp_efs_with_config
    await append_to_openclaw_config_list(
        owner_id,
        ["channels", "discord", "accounts", "sales", "allowFrom"],
        "999",
    )
    with open(config_path) as f:
        result = json.load(f)
    assert result["channels"]["discord"]["accounts"]["sales"]["allowFrom"] == ["999"]


@pytest.mark.asyncio
async def test_append_to_list_dedups(tmp_efs_with_config):
    from core.services.config_patcher import append_to_openclaw_config_list

    _, owner_id, config_path = tmp_efs_with_config
    await append_to_openclaw_config_list(
        owner_id,
        ["channels", "telegram", "accounts", "main", "allowFrom"],
        "111",  # already present
    )
    with open(config_path) as f:
        result = json.load(f)
    assert result["channels"]["telegram"]["accounts"]["main"]["allowFrom"] == ["111"]


@pytest.mark.asyncio
async def test_append_to_list_missing_config_file_raises(monkeypatch):
    from core.services.config_patcher import append_to_openclaw_config_list, ConfigPatchError

    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr("core.services.config_patcher._efs_mount_path", d)
        with pytest.raises(ConfigPatchError):
            await append_to_openclaw_config_list(
                "user_doesnt_exist",
                ["channels", "telegram", "accounts", "main", "allowFrom"],
                "123",
            )


@pytest.fixture
def tmp_efs_with_bindings(monkeypatch):
    """Minimal openclaw.json with a bindings array for predicate-removal testing."""
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr("core.services.config_patcher._efs_mount_path", d)
        owner_id = "user_test"
        owner_dir = os.path.join(d, owner_id)
        os.makedirs(owner_dir)
        config_path = os.path.join(owner_dir, "openclaw.json")
        with open(config_path, "w") as f:
            json.dump(
                {
                    "channels": {"telegram": {"accounts": {"main": {"allowFrom": ["111", "222", "333"]}}}},
                    "bindings": [
                        {"match": {"channel": "telegram", "accountId": "main"}, "agentId": "main"},
                        {"match": {"channel": "telegram", "accountId": "sales"}, "agentId": "sales"},
                        {"match": {"channel": "discord", "accountId": "main"}, "agentId": "main"},
                    ],
                },
                f,
            )
        yield d, owner_id, config_path


@pytest.mark.asyncio
async def test_remove_from_list_value_match(tmp_efs_with_bindings):
    _, owner_id, config_path = tmp_efs_with_bindings
    await remove_from_openclaw_config_list(
        owner_id,
        ["channels", "telegram", "accounts", "main", "allowFrom"],
        predicate=lambda v: v == "222",
    )
    with open(config_path) as f:
        result = json.load(f)
    assert result["channels"]["telegram"]["accounts"]["main"]["allowFrom"] == ["111", "333"]


@pytest.mark.asyncio
async def test_remove_from_list_predicate_match_dict(tmp_efs_with_bindings):
    _, owner_id, config_path = tmp_efs_with_bindings
    await remove_from_openclaw_config_list(
        owner_id,
        ["bindings"],
        predicate=lambda b: (
            b.get("match", {}).get("channel") == "telegram" and b.get("match", {}).get("accountId") == "sales"
        ),
    )
    with open(config_path) as f:
        result = json.load(f)
    assert len(result["bindings"]) == 2
    assert all(b["match"]["accountId"] != "sales" for b in result["bindings"])


@pytest.mark.asyncio
async def test_remove_from_list_no_match_is_noop(tmp_efs_with_bindings):
    _, owner_id, config_path = tmp_efs_with_bindings
    await remove_from_openclaw_config_list(
        owner_id,
        ["channels", "telegram", "accounts", "main", "allowFrom"],
        predicate=lambda v: v == "nonexistent",
    )
    with open(config_path) as f:
        result = json.load(f)
    assert result["channels"]["telegram"]["accounts"]["main"]["allowFrom"] == ["111", "222", "333"]


@pytest.mark.asyncio
async def test_remove_from_list_missing_path_is_noop(tmp_efs_with_bindings):
    _, owner_id, config_path = tmp_efs_with_bindings
    await remove_from_openclaw_config_list(
        owner_id,
        ["channels", "slack", "accounts", "main", "allowFrom"],  # doesn't exist
        predicate=lambda v: True,
    )
    with open(config_path) as f:
        result = json.load(f)
    # Original bindings untouched
    assert len(result["bindings"]) == 3


@pytest.fixture
def tmp_efs_with_multi_accounts(monkeypatch):
    with tempfile.TemporaryDirectory() as d:
        monkeypatch.setattr("core.services.config_patcher._efs_mount_path", d)
        owner_id = "user_test"
        owner_dir = os.path.join(d, owner_id)
        os.makedirs(owner_dir)
        config_path = os.path.join(owner_dir, "openclaw.json")
        with open(config_path, "w") as f:
            json.dump(
                {
                    "channels": {
                        "telegram": {
                            "accounts": {
                                "main": {"botToken": "aaa", "allowFrom": ["111"]},
                                "sales": {"botToken": "bbb", "allowFrom": ["222"]},
                            },
                        },
                    },
                },
                f,
            )
        yield d, owner_id, config_path


@pytest.mark.asyncio
async def test_delete_path_removes_nested_key(tmp_efs_with_multi_accounts):
    _, owner_id, config_path = tmp_efs_with_multi_accounts
    await delete_openclaw_config_path(
        owner_id,
        ["channels", "telegram", "accounts", "sales"],
    )
    with open(config_path) as f:
        result = json.load(f)
    # sales removed, main preserved
    assert "sales" not in result["channels"]["telegram"]["accounts"]
    assert "main" in result["channels"]["telegram"]["accounts"]
    assert result["channels"]["telegram"]["accounts"]["main"]["botToken"] == "aaa"


@pytest.mark.asyncio
async def test_delete_path_leaves_empty_parent_as_empty_dict(tmp_efs_with_multi_accounts):
    _, owner_id, config_path = tmp_efs_with_multi_accounts
    await delete_openclaw_config_path(owner_id, ["channels", "telegram", "accounts", "main"])
    await delete_openclaw_config_path(owner_id, ["channels", "telegram", "accounts", "sales"])
    with open(config_path) as f:
        result = json.load(f)
    # The parent accounts dict is left as {} rather than being pruned
    assert result["channels"]["telegram"]["accounts"] == {}


@pytest.mark.asyncio
async def test_delete_path_missing_key_is_noop(tmp_efs_with_multi_accounts):
    _, owner_id, config_path = tmp_efs_with_multi_accounts
    await delete_openclaw_config_path(
        owner_id,
        ["channels", "telegram", "accounts", "does_not_exist"],
    )
    with open(config_path) as f:
        result = json.load(f)
    # Nothing removed
    assert "main" in result["channels"]["telegram"]["accounts"]
    assert "sales" in result["channels"]["telegram"]["accounts"]


@pytest.mark.asyncio
async def test_delete_path_missing_intermediate_is_noop(tmp_efs_with_multi_accounts):
    _, owner_id, config_path = tmp_efs_with_multi_accounts
    await delete_openclaw_config_path(
        owner_id,
        ["channels", "slack", "accounts", "main"],  # slack branch doesn't exist
    )
    with open(config_path) as f:
        result = json.load(f)
    assert "main" in result["channels"]["telegram"]["accounts"]
