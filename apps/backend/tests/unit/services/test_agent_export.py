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


def test_export_skips_dotfiles_anywhere_in_tree(fake_efs, tmp_path):
    """Regression: hidden files / hidden dirs at any depth must NOT ship in
    the marketplace artifact. Sellers commonly have .env, .ssh/*, .aws/
    credentials, .openclaw/secrets in their workspace; bundling them
    would deliver secrets directly to buyers
    (Codex P1 round 13, commit fc0581bd).
    """
    seller_id, agent_id, agent_dir = fake_efs
    # Plant a bunch of dotfile / dotdir scenarios.
    (agent_dir / ".env").write_text("OPENAI_API_KEY=sk-secret\n", encoding="utf-8")
    (agent_dir / ".ssh").mkdir()
    (agent_dir / ".ssh" / "id_rsa").write_text("-----BEGIN PRIVATE KEY-----\n", encoding="utf-8")
    # Hidden file nested inside an otherwise-allowed directory.
    (agent_dir / "scripts" / ".secret").write_text("password=hunter2\n", encoding="utf-8")

    pkg = agent_export.export_agent_from_efs(seller_id=seller_id, agent_id=agent_id)
    names = _list_tar_names(pkg.tarball_bytes)
    # None of the dotfile paths show up.
    assert not any(".env" in n.split("/")[-1] for n in names if n != "."), names
    assert not any(".ssh" in n for n in names), names
    assert not any(".secret" in n for n in names), names


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
