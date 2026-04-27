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
from core.services.catalog_slice import (
    _agents_list,
    extract_agent_slice,
    filter_cron_jobs_for_agent,
)

# Catalog slugs become a single S3 key path segment (e.g. "pitch/v1/..."),
# so reject anything that could inject additional segments, reserved
# characters, or escape the prefix. Must start with [a-z0-9] to avoid
# leading dashes.
_VALID_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _remap_cron_jobs_for_deploy(
    template_jobs: list[dict],
    *,
    new_agent_id: str,
    owner_id: str,
) -> list[dict]:
    """Regenerate per-deploy fields on each cron-job template.

    The slice carries cron jobs with ``id``, ``sessionKey``, ``state``,
    ``createdAtMs``, and ``updatedAtMs`` already stripped (by
    ``catalog_slice.filter_cron_jobs_for_agent``). For each remaining
    template entry, we set:
      - a fresh ``id`` (random UUID)
      - the deployer's new ``agentId``
      - a freshly-derived ``sessionKey`` matching OpenClaw's
        ``agent:{agentId}:{userId}`` shape (the persisted format observed
        in ``cron/jobs.json``)
      - ``createdAtMs`` and ``updatedAtMs`` set to now
      - ``state`` is intentionally absent — OpenClaw recomputes
        ``nextRunAtMs`` from ``schedule`` on first read.

    ``delivery`` (channel + accountId) is carried as-is. If the deployer
    hasn't bound the named channel yet, the cron run will fail at delivery
    time and OpenClaw's ``failureAlert`` flow surfaces the error. We
    deliberately don't strip ``delivery`` because the schedule + payload +
    routing intent IS the value of carrying the cron job.
    """
    if not template_jobs:
        return []
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    owner_id_lower = owner_id.lower()
    out: list[dict] = []
    for job in template_jobs:
        if not isinstance(job, dict):
            continue
        new_job = copy.deepcopy(job)
        new_job["id"] = str(uuid.uuid4())
        new_job["agentId"] = new_agent_id
        new_job["sessionKey"] = f"agent:{new_agent_id}:{owner_id_lower}"
        new_job["createdAtMs"] = now_ms
        new_job["updatedAtMs"] = now_ms
        # Drop any stale ``state`` carried through (defensive — slice should
        # already have stripped it, but jobs.json from older publishes may
        # have leaked it through).
        new_job.pop("state", None)
        out.append(new_job)
    return out


class CatalogService:
    def __init__(
        self,
        *,
        s3,
        workspace,
        apply_deploy_mutation: Callable[[str, dict, dict], Awaitable[None]],
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

    # ---- list_all (admin) ----

    def list_all(self) -> dict[str, list[dict[str, Any]]]:
        """Admin view: return {"live": [...with manifest preview], "retired": [...]}.
        Live entries include the full manifest (same shape as list()).
        Retired entries include only the metadata stored at retire time.
        """
        catalog = self._s3.get_json("catalog.json", default={"agents": [], "retired": []})
        live: list[dict[str, Any]] = []
        for item in catalog.get("agents") or []:
            manifest = self._s3.get_json(item["manifest_url"], default=None)
            if not manifest:
                continue
            live.append(
                {
                    "slug": manifest["slug"],
                    "name": manifest.get("name", manifest["slug"]),
                    "emoji": manifest.get("emoji", ""),
                    "vibe": manifest.get("vibe", ""),
                    "description": manifest.get("description", ""),
                    "current_version": manifest["version"],
                    "published_at": manifest.get("published_at", ""),
                    "published_by": manifest.get("published_by", ""),
                    "suggested_model": manifest.get("suggested_model", ""),
                    "suggested_channels": manifest.get("suggested_channels", []),
                    "required_skills": manifest.get("required_skills", []),
                    "required_plugins": manifest.get("required_plugins", []),
                }
            )

        retired = list(catalog.get("retired") or [])
        return {"live": live, "retired": retired}

    # ---- list_versions (admin) ----

    def list_versions(self, slug: str) -> list[dict[str, Any]]:
        """List all published versions of a slug, ascending.
        Each entry: {version, manifest_url, published_at, published_by, manifest}.
        """
        versions = self._s3.list_versions(slug)
        out: list[dict[str, Any]] = []
        for v in versions:
            manifest_url = f"{slug}/v{v}/manifest.json"
            manifest = self._s3.get_json(manifest_url, default=None)
            if not manifest:
                continue
            out.append(
                {
                    "version": v,
                    "manifest_url": manifest_url,
                    "published_at": manifest.get("published_at", ""),
                    "published_by": manifest.get("published_by", ""),
                    "manifest": manifest,
                }
            )
        return out

    # ---- deploy ----

    async def deploy(self, *, owner_id: str, slug: str) -> dict[str, Any]:
        # owner_id is the EFS/DDB partition key — org_id for org-context
        # callers, user_id for personal-mode. Resolved by the router from the
        # caller's JWT via core.auth.resolve_owner_id(auth). Doing the resolve
        # at the router layer (not here) ensures the active auth context is
        # respected — a user with an org membership but currently in personal
        # mode lands in their personal partition, not the org's.
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
            user_id=owner_id,
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
            # concurrent deploys cannot drop each other's agent entries.
            plugins_patch = copy.deepcopy(slice_.get("plugins") or {})

            await self._apply_deploy(
                owner_id,
                agent_entry,
                plugins_patch,
            )

            self._workspace.write_template_sidecar(
                user_id=owner_id,
                agent_id=new_agent_id,
                content={
                    "template_slug": slug,
                    "template_version": manifest["version"],
                    "deployed_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Carry the publisher's cron jobs (filtered + stripped at publish
            # time) over to the deployer's cron/jobs.json with regenerated
            # ids and the new agent_id wired in. Done AFTER the agent entry
            # is in place so the runtime never sees a cron job pointing at a
            # nonexistent agent.
            template_cron_jobs = slice_.get("cron_jobs") or []
            if template_cron_jobs:
                from core.services.config_patcher import append_cron_jobs

                await append_cron_jobs(
                    owner_id,
                    _remap_cron_jobs_for_deploy(
                        template_cron_jobs,
                        new_agent_id=new_agent_id,
                        owner_id=owner_id,
                    ),
                )
        except Exception:
            # Roll back the extracted workspace so a failed deploy doesn't
            # leave orphan files on EFS. cleanup_agent_dirs removes both
            # agents/{id}/ and workspaces/{id}/, and is best-effort +
            # idempotent — safe to call even if the config patch never
            # ran or already succeeded.
            self._workspace.cleanup_agent_dirs(owner_id, new_agent_id)
            raise

        return {
            "slug": slug,
            "version": manifest["version"],
            "agent_id": new_agent_id,
            "name": manifest.get("name", slug),
            "skills_added": list(agent_entry.get("skills") or []),
            # OpenClaw plugin entries live at ``plugins.entries.{name}``;
            # the top-level keys (``slots``/``entries``) are structural
            # containers, not plugin names.
            "plugins_enabled": list(((slice_.get("plugins") or {}).get("entries") or {}).keys()),
            "cron_jobs_added": len(slice_.get("cron_jobs") or []),
        }

    # ---- deployed ----

    def list_deployed_for_user(self, owner_id: str) -> list[dict[str, Any]]:
        """Scan the owner's workspaces for .template sidecars; return provenance.

        Scans ``workspaces/`` (where sidecars live and where deploy writes
        immediately) rather than ``agents/`` (OpenClaw runtime state that
        lags behind openclaw.json updates). Caller must pass the same
        owner_id used during ``deploy()`` — the router resolves it via
        ``core.auth.resolve_owner_id(auth)`` so deploy + list stay keyed
        consistently for both personal and org-context callers.
        """
        deployed = []
        for agent_id in self._workspace.list_workspace_agent_dirs(owner_id):
            sidecar = self._workspace.read_template_sidecar(owner_id, agent_id)
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
        owner_id: str,
        agent_id: str,
        slug_override: str | None = None,
        description_override: str | None = None,
    ) -> dict[str, Any]:
        # admin_user_id and owner_id are intentionally separate:
        #   - admin_user_id: the Clerk user who clicked publish; recorded as
        #     the manifest's ``published_by`` and on the audit row
        #     (preserves attribution).
        #   - owner_id: the EFS/DDB partition the agent's openclaw.json +
        #     workspace live on. For org-context admins this is org_id; for
        #     personal-mode admins it equals admin_user_id. Router resolves
        #     it via core.auth.resolve_owner_id(auth) — using the JWT's
        #     active context, not Clerk membership lookups, so personal-mode
        #     admins never accidentally write into an org partition.
        config = self._workspace.read_openclaw_config(owner_id)
        if not config:
            raise FileNotFoundError(f"admin {admin_user_id} (owner {owner_id}) has no openclaw.json")

        slice_ = extract_agent_slice(config, agent_id)
        # Read from the nested agents.list the same way extract_agent_slice does.
        agent_entry_raw = next(a for a in _agents_list(config) if isinstance(a, dict) and a.get("id") == agent_id)
        # Carry the publisher's cron jobs that target this agent. Lives in
        # a separate file from openclaw.json (see config.cron.store, default
        # ``~/.openclaw/cron/jobs.json``); runtime + user-specific fields
        # (id, sessionKey, state, createdAtMs, updatedAtMs) are stripped at
        # slice time and regenerated at deploy.
        slice_["cron_jobs"] = filter_cron_jobs_for_agent(
            self._workspace.read_cron_jobs(owner_id),
            agent_id,
        )

        name = agent_entry_raw.get("name") or agent_id
        slug = (slug_override or name).strip().lower().replace(" ", "-")
        if not _VALID_SLUG_RE.fullmatch(slug):
            raise ValueError(
                f"invalid slug {slug!r}: must match [a-z0-9][a-z0-9-]* "
                "(single path segment, no slashes or reserved chars)"
            )

        prior_versions = self._s3.list_versions(slug)
        next_version = (max(prior_versions) + 1) if prior_versions else 1

        # Read manifest fields from the OpenClaw schema's actual paths
        # (see openclaw/src/config/zod-schema.agent-runtime.ts +
        # zod-schema.core.ts):
        #   emoji   → agent.identity.emoji   (NOT agent.emoji)
        #   plugins → plugins.entries.{name} (top-level keys are structural)
        #   tools   → tools.{profile,allow,alsoAllow,deny,...}
        #             (no ``allowed`` field exists; ``required_tools`` left
        #             empty until we model a proper effective-tools resolver)
        # ``vibe`` and ``description`` are not OpenClaw fields — kept in the
        # manifest schema for future use, populated only from the publish-time
        # ``description_override`` argument when supplied by the admin.
        identity = agent_entry_raw.get("identity") or {}
        plugin_entries = (slice_.get("plugins") or {}).get("entries") or {}
        manifest = build_manifest(
            slug=slug,
            version=next_version,
            name=name,
            emoji=identity.get("emoji") or "",
            vibe="",
            description=description_override or "",
            suggested_model=agent_entry_raw.get("model", ""),
            suggested_channels=list((agent_entry_raw.get("channels") or {}).keys()),
            required_skills=list(agent_entry_raw.get("skills") or []),
            required_plugins=list(plugin_entries.keys()),
            required_tools=[],
            published_by=admin_user_id,
        )

        workspace_dir = self._workspace.agent_workspace_path(owner_id, agent_id)
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
