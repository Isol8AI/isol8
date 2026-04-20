import io
import tarfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.services.catalog_service import CatalogService


def _tar_with(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def mock_s3():
    m = MagicMock()
    m.get_json.return_value = {
        "updated_at": "2026-04-19T00:00:00Z",
        "agents": [{"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"}],
    }
    return m


@pytest.fixture
def mock_workspace():
    m = MagicMock()
    m.read_openclaw_config.return_value = {}
    return m


@pytest.fixture
def mock_patch_config():
    return AsyncMock()


@pytest.fixture
def service(mock_s3, mock_workspace, mock_patch_config):
    return CatalogService(
        s3=mock_s3,
        workspace=mock_workspace,
        patch_openclaw_config=mock_patch_config,
    )


def test_list_returns_entries_with_manifest_preview(service, mock_s3):
    def _get_json(key, default=None):
        if key == "catalog.json":
            return {"agents": [{"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"}]}
        if key == "pitch/v3/manifest.json":
            return {
                "slug": "pitch",
                "version": 3,
                "name": "Pitch",
                "emoji": "🎯",
                "vibe": "Direct",
                "description": "Sales",
                "suggested_model": "qwen",
                "suggested_channels": ["telegram"],
                "required_skills": ["web-search"],
                "required_plugins": ["memory"],
                "required_tools": ["web-search"],
                "published_at": "2026-04-19T00:00:00Z",
                "published_by": "admin",
            }
        return default

    mock_s3.get_json.side_effect = _get_json

    entries = service.list()
    assert len(entries) == 1
    assert entries[0]["slug"] == "pitch"
    assert entries[0]["name"] == "Pitch"
    assert entries[0]["version"] == 3


@pytest.mark.asyncio
async def test_deploy_extracts_tar_merges_config_writes_sidecar(service, mock_s3, mock_workspace, mock_patch_config):
    def _get_json(key, default=None):
        if key == "catalog.json":
            return {"agents": [{"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"}]}
        if key == "pitch/v3/manifest.json":
            return {"slug": "pitch", "version": 3, "name": "Pitch"}
        if key == "pitch/v3/openclaw-slice.json":
            return {
                "agent": {"name": "Pitch", "skills": ["web-search"]},
                "plugins": {"memory": {"enabled": True}},
                "tools": {"allowed": ["web-search"]},
            }
        return default

    mock_s3.get_json.side_effect = _get_json
    mock_s3.get_bytes.return_value = _tar_with({"./IDENTITY.md": b"name: Pitch\n"})

    result = await service.deploy(user_id="user_u", slug="pitch")

    assert result["slug"] == "pitch"
    assert result["agent_id"]
    assert result["skills_added"] == ["web-search"]

    mock_workspace.extract_tarball_to_workspace.assert_called_once()
    _, kwargs = mock_workspace.extract_tarball_to_workspace.call_args
    assert kwargs["user_id"] == "user_u"

    mock_patch_config.assert_awaited_once()
    args, _ = mock_patch_config.call_args
    owner_id, patch = args
    assert owner_id == "user_u"
    assert patch["agents"][0]["name"] == "Pitch"
    assert patch["agents"][0]["id"] == result["agent_id"]
    assert patch["agents"][0]["workspace"] == f".openclaw/workspaces/{result['agent_id']}"
    assert patch["plugins"] == {"memory": {"enabled": True}}


@pytest.mark.asyncio
async def test_deploy_unknown_slug_raises(service, mock_s3):
    mock_s3.get_json.return_value = {"agents": []}
    with pytest.raises(KeyError):
        await service.deploy(user_id="user_u", slug="ghost")


@pytest.mark.asyncio
async def test_deploy_writes_template_sidecar(service, mock_s3, mock_workspace, mock_patch_config, tmp_path):
    def _get_json(key, default=None):
        if key == "catalog.json":
            return {"agents": [{"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"}]}
        if key == "pitch/v3/manifest.json":
            return {"slug": "pitch", "version": 3, "name": "Pitch"}
        if key == "pitch/v3/openclaw-slice.json":
            return {"agent": {"name": "Pitch"}, "plugins": {}, "tools": {}}
        return default

    mock_s3.get_json.side_effect = _get_json
    mock_s3.get_bytes.return_value = _tar_with({"./IDENTITY.md": b"hi"})

    sidecar_written = {}

    def _write_sidecar(user_id, agent_id, content):
        sidecar_written["user_id"] = user_id
        sidecar_written["agent_id"] = agent_id
        sidecar_written["content"] = content

    mock_workspace.write_template_sidecar = _write_sidecar

    result = await service.deploy(user_id="user_u", slug="pitch")
    assert sidecar_written["user_id"] == "user_u"
    assert sidecar_written["agent_id"] == result["agent_id"]
    assert sidecar_written["content"]["template_slug"] == "pitch"
    assert sidecar_written["content"]["template_version"] == 3
