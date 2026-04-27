import io
import tarfile
from unittest.mock import AsyncMock, MagicMock, patch

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
    # Default: no cron jobs to carry. Tests that exercise the cron-carry
    # path override this explicitly.
    m.read_cron_jobs.return_value = []
    return m


@pytest.fixture
def mock_apply_deploy():
    return AsyncMock()


@pytest.fixture
def service(mock_s3, mock_workspace, mock_apply_deploy):
    return CatalogService(
        s3=mock_s3,
        workspace=mock_workspace,
        apply_deploy_mutation=mock_apply_deploy,
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
async def test_deploy_extracts_tar_merges_config_writes_sidecar(service, mock_s3, mock_workspace, mock_apply_deploy):
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

    result = await service.deploy(owner_id="user_u", slug="pitch")

    assert result["slug"] == "pitch"
    assert result["agent_id"]
    assert result["skills_added"] == ["web-search"]

    mock_workspace.extract_tarball_to_workspace.assert_called_once()
    _, kwargs = mock_workspace.extract_tarball_to_workspace.call_args
    assert kwargs["user_id"] == "user_u"

    mock_apply_deploy.assert_awaited_once()
    args, _ = mock_apply_deploy.call_args
    owner_id, agent_entry, plugins_patch = args
    assert owner_id == "user_u"
    assert agent_entry["name"] == "Pitch"
    assert agent_entry["id"] == result["agent_id"]
    assert agent_entry["workspace"] == f".openclaw/workspaces/{result['agent_id']}"
    assert plugins_patch == {"memory": {"enabled": True}}


@pytest.mark.asyncio
async def test_deploy_unknown_slug_raises(service, mock_s3):
    mock_s3.get_json.return_value = {"agents": []}
    with pytest.raises(KeyError):
        await service.deploy(owner_id="user_u", slug="ghost")


@pytest.mark.asyncio
async def test_deploy_writes_template_sidecar(service, mock_s3, mock_workspace, mock_apply_deploy, tmp_path):
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

    result = await service.deploy(owner_id="user_u", slug="pitch")
    assert sidecar_written["user_id"] == "user_u"
    assert sidecar_written["agent_id"] == result["agent_id"]
    assert sidecar_written["content"]["template_slug"] == "pitch"
    assert sidecar_written["content"]["template_version"] == 3


@pytest.mark.asyncio
async def test_deploy_rolls_back_workspace_on_patch_failure(service, mock_s3, mock_workspace, mock_apply_deploy):
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
    mock_apply_deploy.side_effect = RuntimeError("patch boom")

    with pytest.raises(RuntimeError, match="patch boom"):
        await service.deploy(owner_id="user_u", slug="pitch")

    # Tar was extracted, then the config patch failed — the extracted
    # workspace must be cleaned up so we don't leak an orphan dir.
    mock_workspace.extract_tarball_to_workspace.assert_called_once()
    mock_workspace.cleanup_agent_dirs.assert_called_once()
    cleanup_args, _ = mock_workspace.cleanup_agent_dirs.call_args
    assert cleanup_args[0] == "user_u"
    # The rolled-back agent_id matches the one we extracted.
    _, extract_kwargs = mock_workspace.extract_tarball_to_workspace.call_args
    assert cleanup_args[1] == extract_kwargs["agent_id"]
    # Sidecar must not have been written (we failed before that step).
    mock_workspace.write_template_sidecar.assert_not_called()


@pytest.mark.asyncio
async def test_publish_reads_admin_efs_and_uploads_package(service, mock_s3, mock_workspace, tmp_path):
    # OpenClaw agent schema: emoji lives under ``identity``;
    # plugins are nested under ``plugins.entries.{name}``.
    mock_workspace.read_openclaw_config.return_value = {
        "agents": {
            "list": [
                {
                    "id": "agent_admin_pitch",
                    "workspace": ".openclaw/workspaces/agent_admin_pitch",
                    "name": "Pitch",
                    "identity": {"emoji": "🎯"},
                    "model": "qwen/qwen3-vl-235b",
                    "skills": ["web-search"],
                    "channels": {"telegram": {"bot_token": "SECRET"}},
                }
            ]
        },
        "plugins": {"entries": {"memory": {"enabled": True}}},
        "tools": {"profile": "full", "deny": ["canvas"]},
    }
    admin_workspace = tmp_path / "admin_ws"
    admin_workspace.mkdir()
    (admin_workspace / "IDENTITY.md").write_text("name: Pitch\nemoji: 🎯\n")
    mock_workspace.agent_workspace_path.return_value = admin_workspace

    mock_s3.list_versions.return_value = []
    mock_s3.get_json.return_value = {"agents": []}

    result = await service.publish(
        admin_user_id="user_admin",
        owner_id="user_admin",
        agent_id="agent_admin_pitch",
        description_override=None,
    )

    assert result["slug"] == "pitch"
    assert result["version"] == 1

    # Manifest reads emoji from agent.identity.emoji and required_plugins from
    # plugins.entries.* keys (NOT the top-level structural keys).
    manifest_call = next(c for c in mock_s3.put_json.call_args_list if c.args[0] == "pitch/v1/manifest.json")
    manifest = manifest_call.args[1]
    assert manifest["emoji"] == "🎯"
    assert manifest["required_plugins"] == ["memory"]
    assert manifest["required_tools"] == []

    put_json_keys = [c.args[0] for c in mock_s3.put_json.call_args_list]
    assert "pitch/v1/manifest.json" in put_json_keys
    assert "pitch/v1/openclaw-slice.json" in put_json_keys
    assert "catalog.json" in put_json_keys

    put_bytes_keys = [c.args[0] for c in mock_s3.put_bytes.call_args_list]
    assert "pitch/v1/workspace.tar.gz" in put_bytes_keys

    slice_call = next(c for c in mock_s3.put_json.call_args_list if c.args[0] == "pitch/v1/openclaw-slice.json")
    slice_json = slice_call.args[1]
    assert "model" not in slice_json["agent"]
    assert "channels" not in slice_json["agent"]
    assert "workspace" not in slice_json["agent"]
    assert "id" not in slice_json["agent"]


@pytest.mark.asyncio
async def test_publish_rejects_invalid_slug(service, mock_s3, mock_workspace, tmp_path):
    mock_workspace.read_openclaw_config.return_value = {
        "agents": {"list": [{"id": "a1", "name": "Pitch", "skills": []}]},
        "plugins": {},
        "tools": {},
    }
    admin_workspace = tmp_path / "ws"
    admin_workspace.mkdir()
    (admin_workspace / "IDENTITY.md").write_text("x")
    mock_workspace.agent_workspace_path.return_value = admin_workspace
    mock_s3.list_versions.return_value = []
    mock_s3.get_json.return_value = {"agents": []}

    # Path-traversal attempt
    with pytest.raises(ValueError, match="invalid slug"):
        await service.publish(
            admin_user_id="admin",
            owner_id="admin",
            agent_id="a1",
            slug_override="foo/bar",
        )

    # Whitespace-only override collapses to the empty string
    with pytest.raises(ValueError, match="invalid slug"):
        await service.publish(
            admin_user_id="admin",
            owner_id="admin",
            agent_id="a1",
            slug_override="   ",
        )

    # Leading dash is also rejected (slug must start with [a-z0-9])
    with pytest.raises(ValueError, match="invalid slug"):
        await service.publish(
            admin_user_id="admin",
            owner_id="admin",
            agent_id="a1",
            slug_override="-bad",
        )

    # Nothing was published for any of the rejected slugs.
    mock_s3.put_json.assert_not_called()
    mock_s3.put_bytes.assert_not_called()


@pytest.mark.asyncio
async def test_publish_bumps_version_when_prior_exists(service, mock_s3, mock_workspace, tmp_path):
    mock_workspace.read_openclaw_config.return_value = {
        "agents": {"list": [{"id": "a1", "name": "Pitch", "skills": []}]},
        "plugins": {},
        "tools": {},
    }
    admin_workspace = tmp_path / "admin_ws"
    admin_workspace.mkdir()
    (admin_workspace / "IDENTITY.md").write_text("name: Pitch\n")
    mock_workspace.agent_workspace_path.return_value = admin_workspace
    mock_s3.list_versions.return_value = [1, 2, 5]
    mock_s3.get_json.return_value = {"agents": []}

    result = await service.publish(admin_user_id="admin", owner_id="admin", agent_id="a1")
    assert result["version"] == 6


@pytest.mark.asyncio
async def test_unpublish_moves_slug_from_live_to_retired(service, mock_s3):
    """Soft delete: slug moves from agents -> retired. S3 artifacts untouched."""
    mock_s3.get_json.return_value = {
        "updated_at": "2026-04-22T00:00:00Z",
        "agents": [
            {"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"},
            {"slug": "echo", "current_version": 1, "manifest_url": "echo/v1/manifest.json"},
        ],
        "retired": [],
    }

    result = await service.unpublish(admin_user_id="user_admin", slug="pitch")

    assert result["slug"] == "pitch"
    assert result["last_version"] == 3

    put_json_calls = [c for c in mock_s3.put_json.call_args_list if c.args[0] == "catalog.json"]
    assert len(put_json_calls) == 1
    new_catalog = put_json_calls[0].args[1]
    assert [a["slug"] for a in new_catalog["agents"]] == ["echo"]
    assert len(new_catalog["retired"]) == 1
    assert new_catalog["retired"][0]["slug"] == "pitch"
    assert new_catalog["retired"][0]["last_version"] == 3
    assert new_catalog["retired"][0]["retired_by"] == "user_admin"
    assert "retired_at" in new_catalog["retired"][0]


@pytest.mark.asyncio
async def test_unpublish_missing_slug_raises(service, mock_s3):
    mock_s3.get_json.return_value = {"agents": [], "retired": []}
    with pytest.raises(KeyError):
        await service.unpublish(admin_user_id="user_admin", slug="ghost")


@pytest.mark.asyncio
async def test_unpublish_preserves_other_retired_entries(service, mock_s3):
    mock_s3.get_json.return_value = {
        "updated_at": "2026-04-22T00:00:00Z",
        "agents": [
            {"slug": "pitch", "current_version": 2, "manifest_url": "pitch/v2/manifest.json"},
        ],
        "retired": [
            {
                "slug": "oldie",
                "last_version": 1,
                "last_manifest_url": "oldie/v1/manifest.json",
                "retired_at": "2026-04-01T00:00:00Z",
                "retired_by": "user_admin",
            },
        ],
    }
    await service.unpublish(admin_user_id="user_admin", slug="pitch")

    new_catalog = next(c for c in mock_s3.put_json.call_args_list if c.args[0] == "catalog.json").args[1]
    retired_slugs = sorted(r["slug"] for r in new_catalog["retired"])
    assert retired_slugs == ["oldie", "pitch"]


@pytest.mark.asyncio
async def test_unpublish_handles_missing_retired_key(service, mock_s3):
    """Backward compat: catalog.json without a 'retired' key is treated as []."""
    mock_s3.get_json.return_value = {
        "updated_at": "2026-04-22T00:00:00Z",
        "agents": [
            {"slug": "pitch", "current_version": 1, "manifest_url": "pitch/v1/manifest.json"},
        ],
    }
    await service.unpublish(admin_user_id="user_admin", slug="pitch")
    new_catalog = next(c for c in mock_s3.put_json.call_args_list if c.args[0] == "catalog.json").args[1]
    assert new_catalog["retired"][0]["slug"] == "pitch"


@pytest.mark.asyncio
async def test_publish_removes_retired_entry_when_republishing(service, mock_s3, mock_workspace, tmp_path):
    """Republishing a retired slug removes it from retired and adds it to agents."""
    mock_workspace.read_openclaw_config.return_value = {
        "agents": {"list": [{"id": "a1", "name": "Pitch", "skills": []}]},
        "plugins": {},
        "tools": {},
    }
    admin_workspace = tmp_path / "ws"
    admin_workspace.mkdir()
    (admin_workspace / "IDENTITY.md").write_text("x")
    mock_workspace.agent_workspace_path.return_value = admin_workspace
    mock_s3.list_versions.return_value = [1, 2]
    mock_s3.get_json.return_value = {
        "agents": [],
        "retired": [
            {
                "slug": "pitch",
                "last_version": 2,
                "last_manifest_url": "pitch/v2/manifest.json",
                "retired_at": "2026-04-01T00:00:00Z",
                "retired_by": "user_admin",
            },
        ],
    }

    result = await service.publish(
        admin_user_id="user_admin",
        owner_id="user_admin",
        agent_id="a1",
        slug_override="pitch",
    )
    assert result["version"] == 3

    catalog_put = next(c for c in mock_s3.put_json.call_args_list if c.args[0] == "catalog.json")
    new_catalog = catalog_put.args[1]
    assert [a["slug"] for a in new_catalog["agents"]] == ["pitch"]
    assert new_catalog["retired"] == []


def test_list_all_returns_live_and_retired(service, mock_s3):
    """Admin view: live entries include full manifest preview; retired
    entries include the metadata we stored at retire time."""

    def _get_json(key, default=None):
        if key == "catalog.json":
            return {
                "agents": [
                    {"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"},
                ],
                "retired": [
                    {
                        "slug": "echo",
                        "last_version": 1,
                        "last_manifest_url": "echo/v1/manifest.json",
                        "retired_at": "2026-04-22T00:00:00Z",
                        "retired_by": "user_admin",
                    },
                ],
            }
        if key == "pitch/v3/manifest.json":
            return {
                "slug": "pitch",
                "version": 3,
                "name": "Pitch",
                "emoji": "🎯",
                "vibe": "Direct",
                "description": "Sales",
                "suggested_model": "qwen",
                "suggested_channels": [],
                "required_skills": [],
                "required_plugins": [],
                "required_tools": [],
                "published_at": "2026-04-20T00:00:00Z",
                "published_by": "user_admin",
            }
        return default

    mock_s3.get_json.side_effect = _get_json

    result = service.list_all()

    assert len(result["live"]) == 1
    assert result["live"][0]["slug"] == "pitch"
    assert result["live"][0]["name"] == "Pitch"
    assert result["live"][0]["current_version"] == 3
    assert "published_at" in result["live"][0]

    assert len(result["retired"]) == 1
    assert result["retired"][0]["slug"] == "echo"
    assert result["retired"][0]["retired_by"] == "user_admin"
    assert result["retired"][0]["last_version"] == 1


def test_list_all_empty_catalog(service, mock_s3):
    mock_s3.get_json.return_value = {"agents": [], "retired": []}
    result = service.list_all()
    assert result == {"live": [], "retired": []}


def test_list_all_handles_missing_retired_key(service, mock_s3):
    mock_s3.get_json.side_effect = lambda key, default=None: {"agents": []} if key == "catalog.json" else default
    result = service.list_all()
    assert result == {"live": [], "retired": []}


def test_list_versions_returns_sorted_with_manifests(service, mock_s3):
    """Versions sorted ascending; each entry includes manifest JSON + timestamps."""
    mock_s3.list_versions.return_value = [1, 2, 3]

    def _get_json(key, default=None):
        if key == "pitch/v1/manifest.json":
            return {
                "slug": "pitch",
                "version": 1,
                "name": "Pitch",
                "published_at": "2026-04-19T00:00:00Z",
                "published_by": "user_admin",
            }
        if key == "pitch/v2/manifest.json":
            return {
                "slug": "pitch",
                "version": 2,
                "name": "Pitch",
                "published_at": "2026-04-20T00:00:00Z",
                "published_by": "user_admin",
            }
        if key == "pitch/v3/manifest.json":
            return {
                "slug": "pitch",
                "version": 3,
                "name": "Pitch",
                "published_at": "2026-04-21T00:00:00Z",
                "published_by": "user_admin",
            }
        return default

    mock_s3.get_json.side_effect = _get_json

    result = service.list_versions("pitch")

    assert [v["version"] for v in result] == [1, 2, 3]
    assert result[2]["published_at"] == "2026-04-21T00:00:00Z"
    assert result[0]["manifest"]["name"] == "Pitch"
    assert result[0]["manifest_url"] == "pitch/v1/manifest.json"


def test_list_versions_empty_for_unknown_slug(service, mock_s3):
    mock_s3.list_versions.return_value = []
    result = service.list_versions("ghost")
    assert result == []


def test_list_versions_skips_missing_manifest(service, mock_s3):
    """If an S3 manifest is missing, the version is omitted rather than crashing."""
    mock_s3.list_versions.return_value = [1, 2]
    mock_s3.get_json.side_effect = lambda key, default=None: (
        {"slug": "pitch", "version": 2, "name": "Pitch", "published_at": "2026-04-22T00:00:00Z", "published_by": "u"}
        if key == "pitch/v2/manifest.json"
        else default
    )
    result = service.list_versions("pitch")
    assert [v["version"] for v in result] == [2]


# ---- owner_id resolution (org-context callers) ----
#
# Regression for the live prod trace where publish() crashed with
# FileNotFoundError: admin user_3CGsz7ain... has no openclaw.json because
# the catalog service read EFS at /mnt/efs/users/{admin_user_id}/ for an
# admin who is actually an org member — their config lives at
# /mnt/efs/users/{org_id}/.
#
# Resolution lives at the ROUTER layer via core.auth.resolve_owner_id(auth)
# (router tests assert this); the service just trusts the owner_id its caller
# passes in and uses it for every EFS access.


@pytest.mark.asyncio
async def test_publish_uses_passed_owner_id_for_efs_reads(mock_s3, mock_workspace, mock_apply_deploy, tmp_path):
    """Org-context: caller passes owner_id=org_id; EFS reads use it; published_by stays admin_user_id."""
    mock_workspace.read_openclaw_config.return_value = {
        "agents": {
            "list": [
                {
                    "id": "agent_admin_pitch",
                    "workspace": ".openclaw/workspaces/agent_admin_pitch",
                    "name": "Pitch",
                    "skills": ["web-search"],
                }
            ]
        },
        "plugins": {"memory": {"enabled": True}},
        "tools": {"allowed": ["web-search"]},
    }
    org_workspace = tmp_path / "org_ws"
    org_workspace.mkdir()
    (org_workspace / "IDENTITY.md").write_text("name: Pitch\n")
    mock_workspace.agent_workspace_path.return_value = org_workspace
    mock_s3.list_versions.return_value = []
    mock_s3.get_json.return_value = {"agents": []}

    service = CatalogService(
        s3=mock_s3,
        workspace=mock_workspace,
        apply_deploy_mutation=mock_apply_deploy,
    )
    result = await service.publish(
        admin_user_id="user_admin",
        owner_id="org_abc",
        agent_id="agent_admin_pitch",
    )

    # EFS reads used the passed owner_id (org_id), NOT the raw admin_user_id.
    mock_workspace.read_openclaw_config.assert_called_once_with("org_abc")
    mock_workspace.agent_workspace_path.assert_called_once_with("org_abc", "agent_admin_pitch")

    # Manifest's published_by attributes the admin who clicked publish, not
    # the resolved org owner_id (audit + provenance).
    manifest_call = next(c for c in mock_s3.put_json.call_args_list if c.args[0] == "pitch/v1/manifest.json")
    assert manifest_call.args[1]["published_by"] == "user_admin"

    assert result["slug"] == "pitch"
    assert result["version"] == 1


@pytest.mark.asyncio
async def test_publish_personal_mode_owner_equals_admin_user_id(mock_s3, mock_workspace, mock_apply_deploy, tmp_path):
    """Personal mode: caller passes owner_id == admin_user_id; everything keys off it."""
    mock_workspace.read_openclaw_config.return_value = {
        "agents": {"list": [{"id": "a1", "name": "Pitch", "skills": []}]},
        "plugins": {},
        "tools": {},
    }
    personal_workspace = tmp_path / "personal_ws"
    personal_workspace.mkdir()
    (personal_workspace / "IDENTITY.md").write_text("x")
    mock_workspace.agent_workspace_path.return_value = personal_workspace
    mock_s3.list_versions.return_value = []
    mock_s3.get_json.return_value = {"agents": []}

    service = CatalogService(
        s3=mock_s3,
        workspace=mock_workspace,
        apply_deploy_mutation=mock_apply_deploy,
    )
    result = await service.publish(
        admin_user_id="user_solo",
        owner_id="user_solo",
        agent_id="a1",
    )

    mock_workspace.read_openclaw_config.assert_called_once_with("user_solo")
    mock_workspace.agent_workspace_path.assert_called_once_with("user_solo", "a1")

    manifest_call = next(c for c in mock_s3.put_json.call_args_list if c.args[0] == "pitch/v1/manifest.json")
    assert manifest_call.args[1]["published_by"] == "user_solo"
    assert result["version"] == 1


@pytest.mark.asyncio
async def test_deploy_uses_passed_owner_id_for_all_efs_writes(mock_s3, mock_workspace, mock_apply_deploy):
    """Org-context: every EFS write — extract, config patch, sidecar — uses owner_id, not user_id."""

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
    mock_s3.get_bytes.return_value = _tar_with({"./IDENTITY.md": b"hi"})

    service = CatalogService(
        s3=mock_s3,
        workspace=mock_workspace,
        apply_deploy_mutation=mock_apply_deploy,
    )
    result = await service.deploy(owner_id="org_abc", slug="pitch")

    _, extract_kwargs = mock_workspace.extract_tarball_to_workspace.call_args
    assert extract_kwargs["user_id"] == "org_abc"

    apply_args, _ = mock_apply_deploy.call_args
    assert apply_args[0] == "org_abc"

    _, sidecar_kwargs = mock_workspace.write_template_sidecar.call_args
    assert sidecar_kwargs["user_id"] == "org_abc"
    assert sidecar_kwargs["agent_id"] == result["agent_id"]


@pytest.mark.asyncio
async def test_deploy_personal_mode_owner_equals_user_id(mock_s3, mock_workspace, mock_apply_deploy):
    """Personal mode: caller passes owner_id == user_id; identical behavior."""

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

    service = CatalogService(
        s3=mock_s3,
        workspace=mock_workspace,
        apply_deploy_mutation=mock_apply_deploy,
    )
    await service.deploy(owner_id="user_solo", slug="pitch")

    _, extract_kwargs = mock_workspace.extract_tarball_to_workspace.call_args
    assert extract_kwargs["user_id"] == "user_solo"
    apply_args, _ = mock_apply_deploy.call_args
    assert apply_args[0] == "user_solo"
    _, sidecar_kwargs = mock_workspace.write_template_sidecar.call_args
    assert sidecar_kwargs["user_id"] == "user_solo"


def test_list_deployed_for_user_keyed_by_owner_id(service, mock_workspace):
    """deploy + list must be keyed identically: when deploy writes under owner_id,
    list_deployed_for_user must also read under owner_id, not user_id.

    Codex P2 regression — earlier draft of this fix wrote sidecars under
    owner_id but the listing path still scanned by user_id, so org-context
    deploys silently disappeared from the deployed list."""
    mock_workspace.list_workspace_agent_dirs.return_value = ["agent_xx"]
    mock_workspace.read_template_sidecar.return_value = {
        "template_slug": "pitch",
        "template_version": 3,
    }

    deployed = service.list_deployed_for_user("org_abc")

    mock_workspace.list_workspace_agent_dirs.assert_called_once_with("org_abc")
    mock_workspace.read_template_sidecar.assert_called_once_with("org_abc", "agent_xx")
    assert deployed == [{"agent_id": "agent_xx", "template_slug": "pitch", "template_version": 3}]


# ---- cron-jobs carry through publish + deploy ----
#
# Cron jobs live in {owner_id}/cron/jobs.json (separate from openclaw.json),
# so the catalog service threads them through:
#   publish: workspace.read_cron_jobs() → filter_cron_jobs_for_agent →
#            slice["cron_jobs"]
#   deploy:  slice["cron_jobs"] → _remap_cron_jobs_for_deploy → append


@pytest.mark.asyncio
async def test_publish_carries_filtered_cron_jobs_in_slice(mock_s3, mock_workspace, mock_apply_deploy, tmp_path):
    mock_workspace.read_openclaw_config.return_value = {
        "agents": {"list": [{"id": "pitch", "name": "Pitch"}]},
        "plugins": {"entries": {"memory": {"enabled": True}}},
        "tools": {"profile": "full"},
    }
    # Publisher has cron jobs for two agents; only pitch's should ride along.
    mock_workspace.read_cron_jobs.return_value = [
        {
            "id": "j1",
            "agentId": "pitch",
            "name": "Daily morning brief",
            "schedule": {"kind": "cron", "expr": "0 9 * * *", "tz": "UTC"},
            "payload": {"kind": "agentTurn", "message": "Run brief"},
            "delivery": {"mode": "announce", "channel": "telegram"},
            "sessionKey": "agent:pitch:user_publisher",
            "createdAtMs": 1700000000000,
            "state": {"nextRunAtMs": 1700000060000},
        },
        {"id": "j2", "agentId": "other_agent", "name": "Should not carry"},
    ]
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "IDENTITY.md").write_text("x")
    mock_workspace.agent_workspace_path.return_value = workspace
    mock_s3.list_versions.return_value = []
    mock_s3.get_json.return_value = {"agents": [], "retired": []}

    service = CatalogService(
        s3=mock_s3,
        workspace=mock_workspace,
        apply_deploy_mutation=mock_apply_deploy,
    )
    await service.publish(
        admin_user_id="user_admin",
        owner_id="user_admin",
        agent_id="pitch",
    )

    slice_call = next(c for c in mock_s3.put_json.call_args_list if c.args[0] == "pitch/v1/openclaw-slice.json")
    slice_json = slice_call.args[1]
    assert "cron_jobs" in slice_json
    assert len(slice_json["cron_jobs"]) == 1
    [job] = slice_json["cron_jobs"]
    # Stripped fields.
    for k in ("id", "sessionKey", "state", "createdAtMs", "updatedAtMs"):
        assert k not in job
    # Behavioral fields preserved.
    assert job["agentId"] == "pitch"
    assert job["name"] == "Daily morning brief"
    assert job["schedule"]["expr"] == "0 9 * * *"
    assert job["delivery"] == {"mode": "announce", "channel": "telegram"}


@pytest.mark.asyncio
async def test_deploy_carries_cron_jobs_with_remapped_id_and_agent(mock_s3, mock_workspace, mock_apply_deploy):
    """Deploy reads slice.cron_jobs, regenerates id/sessionKey/timestamps,
    rewrites agentId to the new agent, and appends to the deployer's
    cron/jobs.json via append_cron_jobs."""

    def _get_json(key, default=None):
        if key == "catalog.json":
            return {"agents": [{"slug": "pitch", "current_version": 1, "manifest_url": "pitch/v1/manifest.json"}]}
        if key == "pitch/v1/manifest.json":
            return {"slug": "pitch", "version": 1, "name": "Pitch"}
        if key == "pitch/v1/openclaw-slice.json":
            return {
                "agent": {"name": "Pitch", "skills": []},
                "plugins": {},
                "tools": {},
                "cron_jobs": [
                    {
                        "agentId": "pitch",  # publisher's id
                        "name": "Daily brief",
                        "schedule": {"kind": "cron", "expr": "0 9 * * *", "tz": "UTC"},
                        "payload": {"kind": "agentTurn", "message": "go"},
                    },
                    {
                        "agentId": "pitch",
                        "name": "Weekly digest",
                        "schedule": {"kind": "cron", "expr": "0 7 * * 1", "tz": "UTC"},
                        "payload": {"kind": "agentTurn", "message": "weekly"},
                    },
                ],
            }
        return default

    mock_s3.get_json.side_effect = _get_json
    mock_s3.get_bytes.return_value = _tar_with({"./IDENTITY.md": b"hi"})

    appended: list[tuple[str, list[dict]]] = []

    async def _fake_append(owner_id, jobs):
        appended.append((owner_id, jobs))

    service = CatalogService(
        s3=mock_s3,
        workspace=mock_workspace,
        apply_deploy_mutation=mock_apply_deploy,
    )
    with patch("core.services.config_patcher.append_cron_jobs", new=_fake_append):
        result = await service.deploy(owner_id="org_xyz", slug="pitch")

    assert result["cron_jobs_added"] == 2
    assert len(appended) == 1
    captured_owner, captured_jobs = appended[0]
    assert captured_owner == "org_xyz"
    assert len(captured_jobs) == 2

    # Both jobs carry the new agent_id (not the publisher's "pitch") and
    # have fresh ids / sessionKeys derived from owner_id.
    new_agent_id = result["agent_id"]
    for j in captured_jobs:
        assert j["agentId"] == new_agent_id
        assert j["sessionKey"] == f"agent:{new_agent_id}:org_xyz"
        assert "id" in j and j["id"]  # uuid populated
        assert "createdAtMs" in j
        assert "updatedAtMs" in j
        assert "state" not in j

    # Schedule + payload preserved verbatim.
    by_name = {j["name"]: j for j in captured_jobs}
    assert by_name["Daily brief"]["schedule"]["expr"] == "0 9 * * *"
    assert by_name["Weekly digest"]["schedule"]["expr"] == "0 7 * * 1"


@pytest.mark.asyncio
async def test_deploy_with_no_cron_jobs_skips_append(mock_s3, mock_workspace, mock_apply_deploy):
    """A slice with no cron_jobs (or an empty list) doesn't call append_cron_jobs.
    Backward-compat: existing slices in S3 published before this change have
    no ``cron_jobs`` key — deploy must still work."""

    def _get_json(key, default=None):
        if key == "catalog.json":
            return {"agents": [{"slug": "pitch", "current_version": 1, "manifest_url": "pitch/v1/manifest.json"}]}
        if key == "pitch/v1/manifest.json":
            return {"slug": "pitch", "version": 1, "name": "Pitch"}
        if key == "pitch/v1/openclaw-slice.json":
            # No cron_jobs key at all (legacy slice).
            return {"agent": {"name": "Pitch"}, "plugins": {}, "tools": {}}
        return default

    mock_s3.get_json.side_effect = _get_json
    mock_s3.get_bytes.return_value = _tar_with({"./IDENTITY.md": b"hi"})

    appended: list = []

    async def _fake_append(owner_id, jobs):
        appended.append((owner_id, jobs))

    service = CatalogService(
        s3=mock_s3,
        workspace=mock_workspace,
        apply_deploy_mutation=mock_apply_deploy,
    )
    with patch("core.services.config_patcher.append_cron_jobs", new=_fake_append):
        result = await service.deploy(owner_id="user_solo", slug="pitch")

    assert result["cron_jobs_added"] == 0
    assert appended == []  # never called
