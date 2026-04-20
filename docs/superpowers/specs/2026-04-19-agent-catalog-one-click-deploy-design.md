# Agent Catalog — One-Click Deploy

**Date:** 2026-04-19
**Status:** Draft (brainstorm-validated, pending implementation plan)

## Summary

Let users deploy pre-built OpenClaw agents into their own container with one click. Isol8 builds and iterates on curated agents in its prod container, promotes them to an S3 catalog via a CLI script, and surfaces them in a permanent "Gallery" section in the user's sidebar. Clicking `[+]` forks the template into the user's EFS workspace and merges the required skills/plugins into their `openclaw.json`. The same mechanism generalizes to user-published agents in a later phase.

## Goals

- Users can deploy any of the curated agents in a single click.
- The user's container ends up with a working agent: identity, workflows, skills, uploads, and dependencies all wired up.
- Publishing a new or updated agent is a repeatable script, not a manual S3 upload.
- The architecture extends cleanly to user-authored publishing (B-phase) by relaxing an admin gate.
- No per-user/tier state leaks into the catalog package.

## Non-goals (v1)

- Automatic update propagation to already-deployed agents. Deploys are forks.
- User-authored publishing UI. Publishing is admin-only via script.
- Catalog search, categories, tags, ratings.
- Usage-stats / telemetry on catalog entries.
- Model / channel / tier-specific payload inside the catalog — user-specific runtime concerns stay out.

## Architecture

```
 YOUR PROD CONTAINER              CATALOG                USER CONTAINER
 ┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
 │ admin EFS       │      │  S3 bucket       │      │ user's EFS      │
 │  workspaces/    │      │  isol8-agent-    │      │  workspaces/    │
 │   pitch/        │      │  catalog/        │      │   {new_uuid}/   │
 │   echo/         │      │    pitch/v3/     │      │                 │
 │   ...           │      │    echo/v1/      │      │ openclaw.json   │
 │                 │      │    catalog.json  │      │  (merged)       │
 │ openclaw.json   │      │                  │      │                 │
 └──────┬──────────┘      └────────┬─────────┘      └─────────▲───────┘
        │                          │                          │
        │ [publish script]         │ [deploy via [+] button]  │
        └──────────► BACKEND ◄─────┴──────────────────────────┘
```

Three flows:

- **Publish** — admin runs `scripts/publish-agent.sh <agent_id>`; backend reads admin's EFS, packages, uploads to S3.
- **List** — `GET /api/v1/catalog` returns the gallery.
- **Deploy** — `POST /api/v1/catalog/deploy` copies the template into the user's EFS and merges config.

## Data model

### S3 layout

```
s3://isol8-agent-catalog/
├── catalog.json                   # index of all published agents
├── pitch/
│   ├── v1/
│   │   ├── manifest.json
│   │   ├── workspace.tar.gz
│   │   └── openclaw-slice.json
│   ├── v2/...
│   └── v3/                        # current
└── echo/
    └── v1/...
```

Older versions are retained for audit/rollback. `catalog.json` points at the current version of each slug.

### `catalog.json`

```json
{
  "updated_at": "2026-04-19T12:00:00Z",
  "agents": [
    {
      "slug": "pitch",
      "current_version": 3,
      "manifest_url": "pitch/v3/manifest.json"
    },
    {
      "slug": "echo",
      "current_version": 1,
      "manifest_url": "echo/v1/manifest.json"
    }
  ]
}
```

### `manifest.json`

```json
{
  "slug": "pitch",
  "version": 3,
  "name": "Pitch",
  "emoji": "🎯",
  "vibe": "Direct, data-driven, protective of the rep's credibility",
  "description": "Runs outbound sales sequences end-to-end: research, draft, send, handle replies.",
  "suggested_model": "qwen/qwen3-vl-235b",
  "suggested_channels": ["telegram", "email"],
  "required_skills": ["web-search", "email-send", "..."],
  "required_plugins": ["memory", "..."],
  "required_tools": ["..."],
  "published_at": "2026-04-19T12:00:00Z",
  "published_by": "admin:<clerk_user_id>"
}
```

`suggested_model` and `suggested_channels` are **informational only** — they are not applied at deploy time. They surface in the info panel as hints.

### `openclaw-slice.json`

The agent's slice of the publisher's `openclaw.json`, **stripped of all user/tier-specific fields**:

- ❌ **Stripped:** `model`, channel bindings, per-user file paths, cron enablement flags that depend on tier
- ✅ **Kept:** agent entry (without `model`), enabled skills, plugins config, tools allowlist, cron schedules, behavioral flags (`thinkingDefault`, `reasoningDefault`), identity references

On deploy, the merged agent entry has no `model` field — runtime resolves the user's tier default.

### `workspace.tar.gz`

Full clone of `workspaces/{agent_id}/` from the publisher's EFS, including:

- `IDENTITY.md`, `SOUL.md`, `MEMORY.md`, `USER.md`, `TOOLS.md`, `HEARTBEAT.md`, `AGENTS.md`
- `*.lobster` workflow files
- `*.js` skill implementations
- `uploads/` contents (fully included)

### `.template` sidecar (user side, post-deploy)

After deploy, the user's `workspaces/{new_agent_id}/.template` contains:

```json
{
  "template_slug": "pitch",
  "template_version": 3,
  "deployed_at": "2026-04-19T14:22:00Z"
}
```

The frontend uses this to:

- Hide the corresponding gallery entry while the user has this agent.
- Restore it to the gallery when the user deletes the agent.
- Provide provenance if we later add "update available" UX.

## Publish flow (admin)

```bash
scripts/publish-agent.sh <agent_id>
# or: pnpm catalog:publish <agent_id>
```

1. Script authenticates using the admin's local Clerk session (same mechanism used elsewhere).
2. POSTs `/api/v1/admin/catalog/publish` with `{agent_id}`.
3. Backend (admin-role gated):
   1. Looks up the admin's `user_id` via Clerk JWT; resolves `workspaces/{agent_id}/` on EFS.
   2. Reads the admin's `openclaw.json` and extracts the agent entry + resolves its skills/plugins/tools dependencies.
   3. Runs the **slice-and-strip step**: produces `openclaw-slice.json` with tier/user-specific fields removed.
   4. Builds `manifest.json`. Slug defaults to `lowercase(identity.name)` but can be overridden via `--slug`. Description can be overridden via `--description`.
   5. Determines next version: fetches `catalog.json` to find current `pitch/v2`, bumps to `v3`.
   6. Tars the workspace directory.
   7. Uploads `workspace.tar.gz`, `manifest.json`, `openclaw-slice.json` to `s3://isol8-agent-catalog/pitch/v3/`.
   8. Rewrites `catalog.json` atomically (read-modify-write with a conditional `If-Match` ETag).
   9. Returns `{slug, version, s3_url}`.
4. Script prints the result.

Republishing an agent is just "run the script again" — it creates a new version directory and flips `catalog.json`. No manual cleanup.

### Admin gate

Gated by a Clerk role check (`role === 'admin'`) in the publish endpoint. For v1 only the Isol8 team has this role. B-phase opens publishing to any authenticated user by softening the gate (and adding content moderation separately).

## Deploy flow (user)

User clicks **[+]** next to "Pitch" in the gallery:

1. Frontend calls `POST /api/v1/catalog/deploy` with `{slug}`.
2. Backend:
   1. Reads `catalog.json`, finds `pitch/v3/manifest.json`.
   2. Downloads `workspace.tar.gz` and `openclaw-slice.json` from S3.
   3. Generates a new `agent_id` UUID for this user.
   4. Extracts the tarball to the user's EFS at `workspaces/{new_agent_id}/`, `chown`ing to UID 1000 (OpenClaw runs as `node`).
   5. Writes `.template` sidecar.
   6. Deep-merges `openclaw-slice.json` into the user's `openclaw.json` using the existing Track-1 config-patch pipeline (file locks via `fcntl.lockf`, chokidar polling picks up the change). The merged agent entry has no `model` field — runtime uses the user's tier default.
   7. Records usage / audit log.
3. Response: `{agent_id, name, skills_added, plugins_enabled}`.
4. Frontend:
   - Shows toast: "Deployed Pitch. Enabled 11 skills."
   - Hides Pitch from the gallery (matched by `.template.template_slug`).
   - Shows the new agent in "Your Agents".
   - Auto-selects it and switches to chat — amplifies the "it worked!" moment.

Deploy is synchronous. For a typical package (~1 MB tar) this should complete in <3s.

### Error handling

- **Free tier scale-to-zero asleep:** if the user's container is stopped, deploy must wake it before writing EFS (existing wake-on-demand path handles this — deploy waits for container READY before writing).
- **Catalog entry missing:** return 404, frontend shows "This agent is no longer available."
- **EFS merge conflict:** extremely unlikely because we generate a fresh UUID per deploy. If it somehow collides, retry with a new UUID.
- **openclaw.json merge failure:** the workspace files are already on disk; we roll back by deleting `workspaces/{new_agent_id}/` before returning the error. Partial-state avoidance.

## UI: Gallery section

Permanent section in the left sidebar, beneath "Your Agents":

```
┌─────────────────────────┐
│ Your Agents             │
│   • Agent 1             │
│   • + New agent         │
│                         │
│ Gallery                 │
│   • Pitch    [+]  [i]   │
│   • Echo     [+]  [i]   │
│   • Scout    [+]  [i]   │
│   • Ember    [+]  [i]   │
│   • Lens     [+]  [i]   │
└─────────────────────────┘
```

### `[+]` — Deploy button

- One click → spinner on the row → success toast.
- Row disappears from gallery once deployed (and reappears if the user deletes their copy).
- Disabled while any deploy is in flight.

### `[i]` — Info button

Opens a right-side detail panel (same pattern as existing control panels):

- Emoji, name, description, vibe
- Required skills / plugins (as chips)
- Suggested model (informational; "Your tier will use …")
- Suggested channels (links to the Channels panel to connect)
- Screenshots of example interactions — deferred to v2

### Conflict behavior (deployed → gallery hidden)

Frontend computes `visible_gallery = catalog.agents.filter(a => !user.agents.some(u => u.template_slug === a.slug))`. This requires the user's agents list to expose `template_slug` — add it to the `agents.list` RPC response or fetch alongside.

## Backend changes

### New endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `POST` | `/api/v1/admin/catalog/publish` | Admin role | Package + upload to S3 |
| `GET` | `/api/v1/catalog` | Authenticated user | List current gallery |
| `POST` | `/api/v1/catalog/deploy` | Authenticated user | Deploy template into user's EFS |

### New service

`core/services/catalog_service.py`:

- `publish(admin_user_id, agent_id, slug_override, description_override) -> PublishResult`
- `list() -> list[CatalogEntry]` (reads `catalog.json` from S3; 60s in-memory cache OK)
- `deploy(user_id, slug) -> DeployResult`

### Reused infrastructure

- `core/containers/workspace.py` — EFS reads/writes.
- `core/containers/config.py` + Track-1 config-patch pipeline — `openclaw.json` deep merge, locking, chown.
- S3 client (already configured for `S3_CONFIG_BUCKET`).
- Container status polling — to ensure free-tier container is awake before EFS writes.

### New infrastructure

- S3 bucket `isol8-agent-catalog` (CDK in `apps/infra/`), private, accessed via backend IAM role.
- Env var `AGENT_CATALOG_BUCKET` (default `isol8-agent-catalog`) in backend config.

### New gateway RPC addition

`agents.list` response needs to include `template_slug` and `template_version` (pulled from the `.template` sidecar). If the `.template` file is absent (user-created agent), both fields are `null`.

## Frontend changes

### New components

- `src/components/chat/GallerySection.tsx` — sidebar section, renders catalog entries minus already-deployed.
- `src/components/chat/GalleryItemRow.tsx` — single row with `[+]` and `[i]`.
- `src/components/chat/AgentDetailPanel.tsx` — right-side info card opened by `[i]`.

### New hook

- `src/hooks/useCatalog.ts` — SWR-wrapped `GET /catalog` and `POST /catalog/deploy` mutation. Invalidates `useAgents` on successful deploy so the new agent shows up.

### Existing code touched

- `Sidebar.tsx` — add Gallery section under the existing agent list.
- `useAgents.ts` — surface `template_slug` / `template_version` from the RPC response (trivial type change).

## Security considerations

### Trust model (v1)

- Only admins publish. `.js` skills in the catalog are first-party code Isol8 authored. No sandboxing needed beyond what OpenClaw already provides.
- B-phase will need skill review / signing / sandboxing — out of scope here, documented as a prerequisite for opening publishing.

### PII in uploads

- Admin decides what to include in their agent's `uploads/` before running publish. The script can print a summary of files being uploaded (`--dry-run` flag recommended) so the admin can verify.
- B-phase: add a mandatory review checklist UI before publish succeeds.

### Tenant isolation

- Deploy reads S3 with the backend's IAM role, writes the user's EFS using the existing per-user access-point scoping. No cross-user paths are ever involved.
- `.template` sidecar is per-user; no user sees another user's data.

## Testing

### Backend

- `catalog_service.publish()` — integration test against LocalStack S3 + EFS: run publish, assert `catalog.json` updated, tarball uploaded, slice stripped correctly.
- `catalog_service.deploy()` — integration test: upload a fixture catalog entry to LocalStack S3, run deploy, assert user's EFS has the workspace + openclaw.json merged correctly + `.template` written.
- Strip step — unit test that model/channel fields are removed from the slice.
- Merge step — reuse existing Track-1 merge tests; add a case asserting a new agent entry appears.

### Frontend

- `GallerySection` — SWR mock catalog → renders rows → clicking `[+]` invalidates agents list.
- Hide-when-deployed logic — unit test the filter function against catalog + agents with / without `template_slug`.

### E2E

- Happy path: free-tier user provisions, catalog loads, clicks `[+]` on Pitch, agent appears in sidebar, can chat. Add to the existing Playwright journey.

## Open questions / things to decide during implementation

- **Which agents ship in v1?** Admin runs `publish-agent.sh` for each polished agent on prod EFS. Not a code decision; tracked as an ops checklist.
- **`catalog.json` rewrite atomicity** — using ETag conditional write should be sufficient given there's exactly one publisher (admin). Revisit when B-phase increases concurrency.
- **CDN caching on `catalog.json`** — the file is small and changes rarely. Skip CDN for v1; backend serves `/api/v1/catalog` directly with a 60s in-memory cache.

## Rollout

1. Ship CDK change creating the S3 bucket (no-op deploy).
2. Ship backend service + endpoints. Unit + integration tests green.
3. Ship frontend Gallery section behind a feature flag.
4. Admin publishes the first agent (Pitch) as a smoke test.
5. Admin publishes remaining polished agents.
6. Flip feature flag on for all users.
7. Monitor: deploy success rate, time-to-deploy, number of deploys per user.
