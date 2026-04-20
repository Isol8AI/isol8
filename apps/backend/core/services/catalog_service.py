"""Catalog service — list, deploy, publish.

Depends on injected collaborators so unit tests can mock them:
  - s3: CatalogS3Client
  - workspace: Workspace (from core.containers.workspace)
  - patch_openclaw_config: async callable (from core.services.config_patcher)
"""

from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


class CatalogService:
    def __init__(
        self,
        *,
        s3,
        workspace,
        patch_openclaw_config: Callable[[str, dict], Awaitable[None]],
    ):
        self._s3 = s3
        self._workspace = workspace
        self._patch = patch_openclaw_config

    # ---- list ----

    def list(self) -> list[dict[str, Any]]:
        catalog = self._s3.get_json("catalog.json", default={"agents": []})
        entries: list[dict[str, Any]] = []
        for item in catalog.get("agents") or []:
            manifest = self._s3.get_json(item["manifest_url"], default=None)
            if not manifest:
                continue
            entries.append(
                {
                    "slug": manifest["slug"],
                    "version": manifest["version"],
                    "name": manifest.get("name", manifest["slug"]),
                    "emoji": manifest.get("emoji", ""),
                    "vibe": manifest.get("vibe", ""),
                    "description": manifest.get("description", ""),
                    "suggested_model": manifest.get("suggested_model", ""),
                    "suggested_channels": manifest.get("suggested_channels", []),
                    "required_skills": manifest.get("required_skills", []),
                    "required_plugins": manifest.get("required_plugins", []),
                }
            )
        return entries

    # ---- deploy ----

    async def deploy(self, *, user_id: str, slug: str) -> dict[str, Any]:
        catalog = self._s3.get_json("catalog.json", default={"agents": []})
        match = next((a for a in catalog.get("agents") or [] if a.get("slug") == slug), None)
        if not match:
            raise KeyError(f"catalog entry not found: {slug!r}")

        manifest = self._s3.get_json(match["manifest_url"])
        slice_key = match["manifest_url"].replace("manifest.json", "openclaw-slice.json")
        slice_ = self._s3.get_json(slice_key)

        workspace_key = match["manifest_url"].replace("manifest.json", "workspace.tar.gz")
        tar_bytes = self._s3.get_bytes(workspace_key)

        new_agent_id = f"agent_{uuid.uuid4().hex[:12]}"

        self._workspace.extract_tarball_to_workspace(
            user_id=user_id,
            agent_id=new_agent_id,
            tar_bytes=tar_bytes,
        )

        # Build agent entry with new id + workspace path.
        # Deep-copy the slice's agent dict so we don't mutate the caller's state
        # (matters if s3 returns a cached/shared dict).
        agent_entry = copy.deepcopy(slice_.get("agent") or {})
        agent_entry["id"] = new_agent_id
        agent_entry["workspace"] = f".openclaw/workspaces/{new_agent_id}"

        # Compute merged agents list ourselves because _deep_merge replaces lists.
        current = self._workspace.read_openclaw_config(user_id) or {}
        existing_agents = list(current.get("agents") or [])

        patch: dict[str, Any] = {
            "agents": existing_agents + [agent_entry],
            "plugins": copy.deepcopy(slice_.get("plugins") or {}),
            "tools": copy.deepcopy(slice_.get("tools") or {}),
        }

        await self._patch(user_id, patch)

        self._workspace.write_template_sidecar(
            user_id=user_id,
            agent_id=new_agent_id,
            content={
                "template_slug": slug,
                "template_version": manifest["version"],
                "deployed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        return {
            "slug": slug,
            "version": manifest["version"],
            "agent_id": new_agent_id,
            "name": manifest.get("name", slug),
            "skills_added": list(agent_entry.get("skills") or []),
            "plugins_enabled": list((slice_.get("plugins") or {}).keys()),
        }
