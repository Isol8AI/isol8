"""Tests for the EFS pre-staging of OpenClaw's Codex auth.json file."""

import json

import pytest

from core.containers.workspace import pre_stage_codex_auth


@pytest.fixture
def fake_efs_root(tmp_path, monkeypatch):
    monkeypatch.setenv("EFS_MOUNT_PATH", str(tmp_path))
    return tmp_path


@pytest.mark.asyncio
async def test_pre_stage_writes_codex_auth_json(fake_efs_root):
    tokens = {
        "access_token": "eyJ.access",
        "refresh_token": "rt_opaque",
        "account_id": "acc_1",
    }
    await pre_stage_codex_auth(user_id="u_1", oauth_tokens=tokens)

    expected_path = fake_efs_root / "u_1" / "codex" / "auth.json"
    assert expected_path.exists(), f"Expected {expected_path} to exist"
    written = json.loads(expected_path.read_text())
    assert written["auth_mode"] == "chatgpt"
    assert written["tokens"]["access_token"] == "eyJ.access"
    assert written["tokens"]["refresh_token"] == "rt_opaque"
    assert written["tokens"]["account_id"] == "acc_1"


@pytest.mark.asyncio
async def test_pre_stage_overwrites_existing(fake_efs_root):
    """Re-OAuth: rewrite the file with new tokens, no merge needed."""
    await pre_stage_codex_auth(
        user_id="u_1",
        oauth_tokens={"access_token": "old", "refresh_token": "old_rt", "account_id": "x"},
    )
    await pre_stage_codex_auth(
        user_id="u_1",
        oauth_tokens={"access_token": "new", "refresh_token": "new_rt", "account_id": "x"},
    )
    written = json.loads((fake_efs_root / "u_1" / "codex" / "auth.json").read_text())
    assert written["tokens"]["access_token"] == "new"
    assert written["tokens"]["refresh_token"] == "new_rt"


@pytest.mark.asyncio
async def test_pre_stage_creates_parent_dirs(fake_efs_root):
    """The codex/ subdir doesn't exist yet — helper must mkdir -p."""
    await pre_stage_codex_auth(
        user_id="brand_new_user",
        oauth_tokens={"access_token": "x", "refresh_token": "y", "account_id": "z"},
    )
    assert (fake_efs_root / "brand_new_user" / "codex").is_dir()


@pytest.mark.asyncio
async def test_pre_stage_omits_account_id_when_missing(fake_efs_root):
    """account_id is optional; if not provided, don't write a null."""
    await pre_stage_codex_auth(
        user_id="u_no_acc",
        oauth_tokens={"access_token": "a", "refresh_token": "b"},
    )
    written = json.loads((fake_efs_root / "u_no_acc" / "codex" / "auth.json").read_text())
    assert "account_id" not in written["tokens"]
