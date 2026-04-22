"""Catalog service — list, deploy, publish.

Depends on injected collaborators so unit tests can mock them:
  - s3: CatalogS3Client
  - workspace: Workspace (from core.containers.workspace)
  - apply_deploy_mutation: async callable (from core.services.config_patcher)
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from core.services.catalog_package import build_manifest, tar_directory
from core.services.catalog_slice import extract_agent_slice

# Catalog slugs become a single S3 key path segment (e.g. "pitch/v1/..."),
# so reject anything that could inject additional segments, reserved
# characters, or escape the prefix. Must start with [a-z0-9] to avoid
# leading dashes.
_VALID_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class CatalogService:
    def __init__(
        self,
        *,
        s3,
        workspace,
        apply_deploy_mutation: Callable[[str, dict, dict, list[str]], Awaitable[None]],
    ):
        self._s3 = s3
        self._workspace = workspace
        self._apply_deploy = apply_deploy_mutation

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

        try:
            # Build agent entry with new id + workspace path.
            # Deep-copy the slice's agent dict so we don't mutate the caller's state
            # (matters if s3 returns a cached/shared dict).
            agent_entry = copy.deepcopy(slice_.get("agent") or {})
            agent_entry["id"] = new_agent_id
            agent_entry["workspace"] = f".openclaw/workspaces/{new_agent_id}"

            # Apply the mutation atomically inside the config file lock so two
            # concurrent deploys cannot drop each other's agent entries or wipe
            # each other's tool allowlist.
            plugins_patch = copy.deepcopy(slice_.get("plugins") or {})
            tools_allowed = list((slice_.get("tools") or {}).get("allowed") or [])

            await self._apply_deploy(
                user_id,
                agent_entry,
                plugins_patch,
                tools_allowed,
            )

            self._workspace.write_template_sidecar(
                user_id=user_id,
                agent_id=new_agent_id,
                content={
                    "template_slug": slug,
                    "template_version": manifest["version"],
                    "deployed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception:
            # Roll back the extracted workspace so a failed deploy doesn't
            # leave orphan files on EFS. cleanup_agent_dirs removes both
            # agents/{id}/ and workspaces/{id}/, and is best-effort +
            # idempotent — safe to call even if the config patch never
            # ran or already succeeded.
            self._workspace.cleanup_agent_dirs(user_id, new_agent_id)
            raise

        return {
            "slug": slug,
            "version": manifest["version"],
            "agent_id": new_agent_id,
            "name": manifest.get("name", slug),
            "skills_added": list(agent_entry.get("skills") or []),
            "plugins_enabled": list((slice_.get("plugins") or {}).keys()),
        }

    # ---- deployed ----

    def list_deployed_for_user(self, user_id: str) -> list[dict[str, Any]]:
        """Scan the user's workspaces for .template sidecars; return provenance.

        Scans ``workspaces/`` (where sidecars live and where deploy writes
        immediately) rather than ``agents/`` (OpenClaw runtime state that
        lags behind openclaw.json updates).
        """
        deployed = []
        for agent_id in self._workspace.list_workspace_agent_dirs(user_id):
            sidecar = self._workspace.read_template_sidecar(user_id, agent_id)
            if sidecar:
                deployed.append(
                    {
                        "agent_id": agent_id,
                        "template_slug": sidecar.get("template_slug"),
                        "template_version": sidecar.get("template_version"),
                    }
                )
        return deployed

    # ---- publish ----

    async def publish(
        self,
        *,
        admin_user_id: str,
        agent_id: str,
        slug_override: str | None = None,
        description_override: str | None = None,
    ) -> dict[str, Any]:
        config = self._workspace.read_openclaw_config(admin_user_id)
        if not config:
            raise FileNotFoundError(f"admin {admin_user_id} has no openclaw.json")

        slice_ = extract_agent_slice(config, agent_id)
        agent_entry_raw = next(a for a in config["agents"] if a.get("id") == agent_id)

        name = agent_entry_raw.get("name") or agent_id
        slug = (slug_override or name).strip().lower().replace(" ", "-")
        if not _VALID_SLUG_RE.fullmatch(slug):
            raise ValueError(
                f"invalid slug {slug!r}: must match [a-z0-9][a-z0-9-]* "
                "(single path segment, no slashes or reserved chars)"
            )

        prior_versions = self._s3.list_versions(slug)
        next_version = (max(prior_versions) + 1) if prior_versions else 1

        manifest = build_manifest(
            slug=slug,
            version=next_version,
            name=name,
            emoji=agent_entry_raw.get("emoji", ""),
            vibe=agent_entry_raw.get("vibe", ""),
            description=description_override or agent_entry_raw.get("description", ""),
            suggested_model=agent_entry_raw.get("model", ""),
            suggested_channels=list((agent_entry_raw.get("channels") or {}).keys()),
            required_skills=list(agent_entry_raw.get("skills") or []),
            required_plugins=list((slice_.get("plugins") or {}).keys()),
            required_tools=list((slice_.get("tools") or {}).get("allowed") or []),
            published_by=admin_user_id,
        )

        workspace_dir = self._workspace.agent_workspace_path(admin_user_id, agent_id)
        tar_bytes = tar_directory(workspace_dir)

        prefix = f"{slug}/v{next_version}"
        self._s3.put_bytes(f"{prefix}/workspace.tar.gz", tar_bytes, content_type="application/gzip")
        self._s3.put_json(f"{prefix}/manifest.json", manifest)
        self._s3.put_json(f"{prefix}/openclaw-slice.json", slice_)

        catalog = self._s3.get_json("catalog.json", default={"agents": [], "retired": []})
        entries = [e for e in (catalog.get("agents") or []) if e.get("slug") != slug]
        entries.append(
            {
                "slug": slug,
                "current_version": next_version,
                "manifest_url": f"{prefix}/manifest.json",
            }
        )
        # Republishing a slug removes it from retired (if present)
        retired = [r for r in (catalog.get("retired") or []) if r.get("slug") != slug]
        self._s3.put_json(
            "catalog.json",
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "agents": entries,
                "retired": retired,
            },
        )

        return {"slug": slug, "version": next_version, "s3_prefix": prefix}

    # ---- unpublish ----

    async def unpublish(self, *, admin_user_id: str, slug: str) -> dict[str, Any]:
        """Soft-delete: move slug from agents list to retired list in catalog.json.
        S3 artifacts (versioned manifests + tarballs) remain untouched for audit.
        Raises KeyError if slug isn't currently live.
        """
        catalog = self._s3.get_json("catalog.json", default={"agents": [], "retired": []})
        agents = list(catalog.get("agents") or [])
        retired = list(catalog.get("retired") or [])

        match = next((a for a in agents if a.get("slug") == slug), None)
        if not match:
            raise KeyError(f"slug {slug!r} is not currently live")

        new_agents = [a for a in agents if a.get("slug") != slug]
        retired_entry = {
            "slug": slug,
            "last_version": match["current_version"],
            "last_manifest_url": match["manifest_url"],
            "retired_at": datetime.now(timezone.utc).isoformat(),
            "retired_by": admin_user_id,
        }
        new_retired = retired + [retired_entry]

        self._s3.put_json(
            "catalog.json",
            {
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "agents": new_agents,
                "retired": new_retired,
            },
        )

        return {
            "slug": slug,
            "last_version": match["current_version"],
            "last_manifest_url": match["manifest_url"],
        }


_catalog_service: CatalogService | None = None


def get_catalog_service() -> CatalogService:
    global _catalog_service
    if _catalog_service is not None:
        return _catalog_service

    from core.config import settings
    from core.containers import get_workspace
    from core.services.catalog_s3_client import CatalogS3Client
    from core.services.config_patcher import apply_deploy_mutation

    if not settings.AGENT_CATALOG_BUCKET:
        raise RuntimeError("AGENT_CATALOG_BUCKET is not configured")

    _catalog_service = CatalogService(
        s3=CatalogS3Client(bucket_name=settings.AGENT_CATALOG_BUCKET),
        workspace=get_workspace(),
        apply_deploy_mutation=apply_deploy_mutation,
    )
    return _catalog_service
