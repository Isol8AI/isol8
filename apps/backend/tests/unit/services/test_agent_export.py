"""Tests for agent_export — Path B (snapshot agent from EFS)."""

import io
import json
import os
import tarfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CLERK_ISSUER", "https://test.clerk.accounts.dev")

import pytest  # noqa: E402

from core.services import agent_export  # noqa: E402


@pytest.fixture
def fake_efs(tmp_path: Path):
    """Builds /tmp/<root>/users/<seller>/agents/<agent-id>/ with sample files
    and patches get_workspace() to return a Workspace anchored at <root>.
    """
    seller_id = "user_seller_abc"
    agent_id = "my-agent-001"

    user_root = tmp_path / "users" / seller_id
    agent_dir = user_root / "agents" / agent_id
    agent_dir.mkdir(parents=True)

    (agent_dir / "openclaw.json").write_text(
        json.dumps(
            {
                "identity": {"name": "MyAgent", "vibe": "helpful", "description": "An agent"},
                "tools": {"foo": {}, "bar": {}},
            }
        ),
        encoding="utf-8",
    )
    (agent_dir / "README.md").write_text("# Hello\n", encoding="utf-8")
    (agent_dir / "scripts").mkdir()
    (agent_dir / "scripts" / "run.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")

    # Junk dirs that should be skipped.
    (agent_dir / "__pycache__").mkdir()
    (agent_dir / "__pycache__" / "ignored.pyc").write_bytes(b"junk")
    (agent_dir / ".git").mkdir()
    (agent_dir / ".git" / "HEAD").write_bytes(b"junk")

    # Patch get_workspace() to anchor at tmp_path/users (matches the
    # production EFS_MOUNT_PATH convention which already ends in /users).
    from core.containers import workspace as workspace_module

    fake_ws = workspace_module.Workspace(mount_path=str(tmp_path / "users"))
    with patch.object(agent_export, "get_workspace", return_value=fake_ws):
        yield seller_id, agent_id, agent_dir


def _list_tar_names(tar_bytes: bytes) -> list[str]:
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tf:
        return [m.name for m in tf.getmembers()]


def test_export_happy_path(fake_efs):
    seller_id, agent_id, _ = fake_efs
    pkg = agent_export.export_agent_from_efs(seller_id=seller_id, agent_id=agent_id)
    assert pkg.format == "openclaw"
    assert pkg.manifest["name"] == "MyAgent"
    assert pkg.manifest["agent_id"] == agent_id
    names = _list_tar_names(pkg.tarball_bytes)
    assert any("openclaw.json" in n for n in names)
    assert any("README.md" in n for n in names)
    assert any("scripts/run.sh" in n for n in names)


def test_export_skips_junk_dirs(fake_efs):
    seller_id, agent_id, _ = fake_efs
    pkg = agent_export.export_agent_from_efs(seller_id=seller_id, agent_id=agent_id)
    names = _list_tar_names(pkg.tarball_bytes)
    assert not any("__pycache__" in n for n in names)
    assert not any(".git" in n for n in names)


def test_export_invalid_agent_id_format(fake_efs):
    seller_id, _, _ = fake_efs
    with pytest.raises(agent_export.InvalidAgentIdError):
        agent_export.export_agent_from_efs(seller_id=seller_id, agent_id="../escape")


def test_export_path_traversal_attempt_rejected(fake_efs):
    seller_id, _, _ = fake_efs
    # The regex covers basic ../ — but also ensure resolved-path check
    # rejects clever encodings. agent_id with embedded slash should fail
    # the regex first.
    with pytest.raises(agent_export.InvalidAgentIdError):
        agent_export.export_agent_from_efs(seller_id=seller_id, agent_id="abc/def")


def test_export_missing_agent_dir_raises_not_found(fake_efs):
    seller_id, _, _ = fake_efs
    with pytest.raises(agent_export.AgentNotFoundError):
        agent_export.export_agent_from_efs(seller_id=seller_id, agent_id="never-existed")


def test_export_snapshot_is_deterministic(fake_efs):
    seller_id, agent_id, _ = fake_efs
    a = agent_export.export_agent_from_efs(seller_id=seller_id, agent_id=agent_id)
    b = agent_export.export_agent_from_efs(seller_id=seller_id, agent_id=agent_id)
    # Identical content → identical bytes (mtimes/uids zeroed).
    assert a.tarball_bytes == b.tarball_bytes


def test_export_invalid_seller_id_rejected(tmp_path):
    with pytest.raises(agent_export.InvalidAgentIdError):
        # WorkspaceError wraps to InvalidAgentIdError.
        agent_export.export_agent_from_efs(seller_id="../bad", agent_id="x")
