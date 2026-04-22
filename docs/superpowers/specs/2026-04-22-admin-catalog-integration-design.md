# Admin Catalog Integration

**Date:** 2026-04-22
**Status:** Draft (brainstorm-validated, pending implementation plan)

## Summary

Move the curated-agent catalog's operator flows out of the `publish-agent.sh` CLI and into the admin dashboard shipped by #351. Add a `/admin/catalog` management page that lists every published slug (with a collapsible "Retired" section), one-click `[Unpublish]` and `[View versions]` affordances per row, and a `[Publish to catalog]` button on the existing admin agent detail page. Every catalog write runs through the dashboard's audit pipeline (`@audit_admin_action` + `isol8-{env}-admin-actions` DDB table) so shell-script and dashboard pushes produce identical audit rows. The user-facing `/catalog` endpoint and Gallery sidebar are unchanged.

## Goals

- Admin publishes a curated agent in two clicks from the dashboard — no JWT paste, no shell, no CLI.
- Admin can see every slug in the catalog, its version history, and retire a broken one without touching S3.
- Every catalog write appears in the existing admin-actions audit table.
- The existing shell script keeps working (for automation / scripted bulk publishes) and lands audit rows identical to the dashboard path.
- User-facing Gallery UX is unchanged — retired slugs simply stop appearing.

## Non-goals (v1)

- Publishing agents that belong to a user other than the calling admin. Phase 2 needs a consent flow.
- A "deployed count" column on the admin catalog table. Cheap to add once an operator need appears.
- Edit manifest fields (description, suggested channels/model) on already-published slugs.
- "Recall" / force-update already-deployed users. Fork model is deliberately preserved.
- A "Restore" button on retired slugs. Republishing from the agent detail page achieves the same effect.

## Prerequisites that already exist

- `require_platform_admin` (backend) — `apps/backend/core/auth.py:242`, the same allowlist the catalog already uses.
- `@audit_admin_action` decorator — `apps/backend/core/services/admin_audit.py` — fail-closed synchronous audit write before the response returns.
- `admin-actions` DDB table — `isol8-{env}-admin-actions`, PK `admin_user_id`, SK `timestamp_action_id`.
- Admin dashboard app — `apps/frontend/src/app/admin/*`, host-gated via middleware on `admin.isol8.co`.
- Admin agent detail page — `/admin/users/[id]/agents/[agent_id]` with `AgentActionsFooter` for inline writes.
- `ConfirmActionDialog` — typed-confirmation pattern for every write.
- `CatalogService` — `apps/backend/core/services/catalog_service.py` with `list`, `deploy`, `publish`.
- `CatalogS3Client` — already exposes `list_versions(slug)`, `get_json`, `put_json`.

## Architecture

```
                  ┌────────────────────────────────────────────────┐
                  │         admin.isol8.co   (Next.js admin app)   │
                  │                                                │
   admin clicks   │  /admin/catalog                                │
   "Publish"  ───▶│  table of slugs (live + retired collapsible)  │
                  │  + View versions side panel                   │
                  │  + Unpublish action                           │
                  │                                                │
                  │  /admin/users/[me]/agents/[agent_id]          │
                  │  └── [Publish to catalog] button in          │
                  │      AgentActionsFooter                       │
                  │                                                │
                  │  Server Actions in app/admin/_actions/catalog.ts
                  └────────┬───────────────────────────────┬──────┘
                           │                               │
                           ▼                               ▼
                  ┌────────────────────────────────────────────────┐
                  │    Backend: routers/admin_catalog.py           │
                  │                                                │
                  │    Existing (now audited):                     │
                  │      POST /admin/catalog/publish               │
                  │                                                │
                  │    New:                                        │
                  │      GET  /admin/catalog                       │
                  │      POST /admin/catalog/{slug}/unpublish      │
                  │      GET  /admin/catalog/{slug}/versions       │
                  │                                                │
                  │    Every endpoint:                             │
                  │      Depends(require_platform_admin) +         │
                  │      @audit_admin_action(...)                  │
                  └────┬────────────────┬──────────────────┬──────┘
                       │                │                  │
                       ▼                ▼                  ▼
                 CatalogService   admin-actions     isol8-{env}-
                 (+ unpublish,    DDB table         agent-catalog
                  + list_all,     (audited writes)  S3 bucket
                  + list_versions)
```

### Trust boundaries

- `require_platform_admin` remains the only auth gate. No behavior change for the existing shell-script path — the CLI's JWT is already validated by this dependency.
- The v1 publish endpoint's server reads the *calling admin's* EFS (`auth.user_id`'s workspace). The admin UI's Publish button only renders when `params.id === auth.user_id` on the agent detail page, preventing accidental clicks that would imply "publish someone else's agent".
- Retired slugs are admin-only visibility. The user-facing `GET /catalog` reads only the `agents` list from `catalog.json`; the new `retired` list never reaches that response.

## Data model

### `catalog.json` (extended)

```json
{
  "updated_at": "2026-04-22T09:00:00Z",
  "agents": [
    {"slug": "pitch", "current_version": 3, "manifest_url": "pitch/v3/manifest.json"}
  ],
  "retired": [
    {
      "slug": "echo",
      "last_version": 2,
      "last_manifest_url": "echo/v2/manifest.json",
      "retired_at": "2026-04-22T08:30:00Z",
      "retired_by": "user_admin_xyz"
    }
  ]
}
```

- Reading: user-facing `/catalog` reads only `agents`. Admin `/admin/catalog` reads both.
- Writing: unpublish moves a row from `agents` → `retired`. Republish (calling `CatalogService.publish` again with the same slug) removes the row from `retired` and appends to `agents` with the next-version number in S3.
- Backward compatibility: `retired` is optional. Existing `catalog.json` files without the key continue to work (treated as `retired: []`).

### Audit row (`isol8-{env}-admin-actions`)

Reuses the existing shape. New `action` values:

- `catalog.publish` — payload: `{source_agent_id, slug, version, s3_prefix}`
- `catalog.unpublish` — payload: `{slug, last_version, last_manifest_url}`

`target_user_id` on both actions is the sentinel string `"__catalog__"`. The target of a catalog action is the shared catalog, not a user, but the existing audit schema requires a non-empty `target_user_id` attribute for the GSI. A distinct sentinel makes it trivial to filter catalog actions out of per-user audit queries (`target-timestamp-index` queries for `user_abc` will not collide with catalog writes).

### S3 layout

Unchanged. Version directories (`s3://.../pitch/v1/`, `v2/`, …) persist across unpublish — soft delete never removes S3 objects. Version numbers keep counting up through retire/republish cycles.

## Backend changes

### New endpoints

| Method | Path | Action name | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/admin/catalog` | (read, not audited) | Returns `{live: [...], retired: [...]}` for the catalog page |
| `POST` | `/api/v1/admin/catalog/{slug}/unpublish` | `catalog.unpublish` | Soft-delete: moves `slug` from `agents` to `retired` |
| `GET` | `/api/v1/admin/catalog/{slug}/versions` | (read, not audited) | Returns `[{version, published_at, published_by, manifest}]` |

### Modified endpoint

- `POST /api/v1/admin/catalog/publish` — wrap the existing handler with `@audit_admin_action("catalog.publish")`. No behavior change; both dashboard and shell-script paths now produce audit rows.

### Handler location

Keep the existing `routers/admin_catalog.py` file. Add the three new handlers alongside `publish`. All four endpoints share the same `router = APIRouter(prefix="/admin/catalog", ...)` — no new router file needed.

### `CatalogService` additions

```python
def list_all(self) -> dict[str, list[dict]]:
    """Return {"live": [entry...], "retired": [entry...]} for the admin page."""

async def unpublish(self, admin_user_id: str, slug: str) -> dict:
    """Soft-delete the slug. Atomic rewrite of catalog.json.
    Raises KeyError if slug isn't live.
    Returns {"slug", "last_version", "last_manifest_url"}.
    """

def list_versions(self, slug: str) -> list[dict]:
    """Return [{version, manifest_url, manifest, published_at, published_by}]
    sorted ascending by version.
    Uses CatalogS3Client.list_versions + fetches each manifest.json.
    """
```

`list_all` and `list_versions` are read-only and safe to invoke without a lock. `unpublish` uses the same single-writer assumption as `publish` (rewriting `catalog.json` with an ETag-conditional PUT; Phase 2 can revisit if multi-admin concurrency appears).

### Shell script (`scripts/publish-agent.sh`)

Unchanged. The endpoint it hits now carries the audit decorator; shell publishes automatically appear in the admin-actions table.

## Frontend changes

### New files

- `src/app/admin/catalog/page.tsx` — Server Component. Fetches `GET /admin/catalog` via existing `_lib/api.ts` helper. Renders a table of live slugs; below, a collapsible "Retired" section with the same columns.
- `src/app/admin/catalog/CatalogRowActions.tsx` — Client Component rendering the `[Unpublish]` + `[View versions]` buttons per row. Wraps `[Unpublish]` in `ConfirmActionDialog` with typed confirmation `"unpublish <slug>"`. Selecting `[View versions]` toggles the `VersionsPanel` on the right.
- `src/app/admin/catalog/VersionsPanel.tsx` — Client Component. Right-side panel (match existing admin pattern). Shows each version (v1, v2, …) with timestamp + "published by"; expandable accordion reveals the manifest JSON syntax-highlighted.
- `src/app/admin/_actions/catalog.ts` — Server Actions: `publishAgent(agent_id, slug?, description?)` and `unpublishSlug(slug)`. Both call the corresponding admin endpoint via the existing admin API client; both return typed results for the UI.

### Modified files

- `src/app/admin/users/[id]/agents/[agent_id]/page.tsx` — compute `is_own_agent = (params.id === authenticated_admin.user_id)`. Pass to `AgentActionsFooter`.
- `src/app/admin/users/[id]/agents/[agent_id]/AgentActionsFooter.tsx` — add `[Publish to catalog]` button alongside existing Delete / Clear sessions. Button is only rendered when `is_own_agent === true`. Uses `ConfirmActionDialog` with typed confirmation `"publish <agent_name>"`. On submit, calls the `publishAgent` Server Action.
- `src/app/admin/layout.tsx` — add "Catalog" to the top-level admin nav between Users and Health.

### UX details

- Table columns: emoji, slug, name, current_version, last_published_at, published_by, actions.
- "Retired" section is collapsed by default (shows "Retired (3)" as a click-to-expand header). When expanded, rows show the same columns plus `retired_at` and `retired_by`. No actions on retired rows in v1.
- `[View versions]` opens a right-side panel overlaying the table, scoped to the single slug. Closing the panel returns focus to the row.
- `[Publish to catalog]` on the agent detail page is disabled with a tooltip "Only your own agents can be published" when viewing another user's agent.

### Accessibility

`ConfirmActionDialog` already handles keyboard focus trap + typed-confirmation lockout (3 wrong tries → forced reload) from the admin dashboard's existing S5 fix. New buttons reuse the same component.

## Security considerations

- Admin-only gate (`require_platform_admin`) on every endpoint. Host-based middleware already blocks `/admin/*` on non-`admin.isol8.co` hosts.
- `ConfirmActionDialog` typed confirmation on publish + unpublish prevents accidental muscle-memory triple-clicks.
- Retired slug metadata (`retired_by` admin user ID) is visible in the admin UI. Not a privacy leak because the set of admins is small and known.
- Publishing is scoped to the calling admin's own agents — no cross-user EFS reads.
- Soft-delete preserves S3 artifacts, so an unpublished agent can be audited (including historical manifests + tarballs) indefinitely.

## Testing

### Backend

- `catalog_service.unpublish` — integration test against LocalStack S3: publish, unpublish, assert catalog.json `agents` list drops the slug, `retired` list adds it, S3 artifacts untouched.
- `catalog_service.list_versions` — fixture: upload v1/v2/v3 manifests, assert sorted descending.
- `catalog_service.list_all` — fixture: populate agents + retired, assert both surfaces.
- Router tests in `tests/unit/test_routers_catalog.py`:
  - `GET /admin/catalog` auth (non-admin → 403).
  - `POST /admin/catalog/{slug}/unpublish` auth (non-admin → 403).
  - Publish with the new audit decorator writes an audit row.
  - Unpublish writes an audit row with action=`catalog.unpublish`.
  - 404 on unpublishing a slug that isn't live.

### Frontend

- Unit tests for the Server Actions (`_actions/catalog.ts`) — mock the admin API client, assert correct endpoint call + error surface.
- Unit tests for `CatalogRowActions` — click unpublish → confirm dialog → Server Action called with correct slug.
- Unit tests for the agent detail page's Publish button visibility (only when `is_own_agent`).

### E2E (deferred)

Gallery deploy E2E step was dropped during the merge with main (journey.spec.ts rewrite). Both user-facing deploy and admin publish are candidates for re-addition into `personal.spec.ts` once the E2E gate is back in good health — tracked as separate follow-up, not blocking this increment.

## Rollout

1. Ship backend changes (new endpoints, audit decorator on publish, `CatalogService` extensions, `catalog.json` schema with `retired` list). Existing `catalog.json` files are forward-compatible (no `retired` key is treated as empty).
2. Ship frontend changes (catalog page, row actions, versions panel, Publish button, Server Actions, nav entry).
3. Deploy to dev. Verify:
   - Sign in as admin at `admin-dev.isol8.co/admin/catalog` — page loads empty (unless something already published).
   - Publish an agent from the detail page — audit row appears in DDB.
   - Unpublish — audit row, slug gone from `/catalog`, visible in the retired section.
   - Shell-script publish still works and produces an identical audit row.
4. Promote to prod.
5. Deprecate (but don't remove) the shell script in team docs — dashboard becomes the documented path.

## Open questions / follow-ups

- Multi-admin concurrency on `catalog.json` rewrites. Single-writer assumption holds in v1 (few admins, infrequent publishes). If it becomes a problem, use an S3 ETag-conditional PUT with retry, or migrate the catalog index to DynamoDB.
- Deployed-count metric — genuinely useful but requires scanning every user's `.template` sidecars. Better supported by a counter maintained at deploy/delete time.
- Edit manifest fields post-publish (description, suggested channels/model). Out of scope but close enough to the unpublish/republish flow that a future increment could fold it into the versions panel.
