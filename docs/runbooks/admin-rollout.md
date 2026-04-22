# Admin dashboard rollout

Operational runbook for `admin.isol8.co` (and `admin-dev.isol8.co`).

**Tracking issue:** [Isol8AI/isol8#351](https://github.com/Isol8AI/isol8/issues/351)
**Spec:** [`docs/superpowers/specs/2026-04-21-admin-dashboard-design.md`](../superpowers/specs/2026-04-21-admin-dashboard-design.md)
**Plan:** [`docs/superpowers/plans/2026-04-21-admin-dashboard.md`](../superpowers/plans/2026-04-21-admin-dashboard.md)

## What's in v1

- Dedicated subdomain `admin.isol8.co` aliased to the existing `isol8-frontend-*` Vercel project.
- Route group at `apps/frontend/src/app/admin/*`, gated by host-based middleware (only the admin host serves these routes).
- Backend `/api/v1/admin/*` endpoints, gated by `Depends(require_platform_admin)` (allowlist driven by `PLATFORM_ADMIN_USER_IDS`).
- Audit table `isol8-{env}-admin-actions` records every write action.
- **No edge SSO gate.** Defense-in-depth = host-check + Clerk + allowlist + audit. (See "When to add an edge gate" below.)

## Prerequisites — one-time per environment

1. **DNS + Vercel domain alias:** `admin-dev.isol8.co` → `isol8-frontend-dev` Vercel project; `admin.isol8.co` → `isol8-frontend-prod`. Verify with `dig admin-dev.isol8.co CNAME`.
2. **Backend secrets** (Secrets Manager entry `isol8/{env}/backend-env`):
   - `PLATFORM_ADMIN_USER_IDS` — comma-separated Clerk user IDs of the Isol8 team
   - `ADMIN_UI_ENABLED=true`
   - `ADMIN_UI_ENABLED_USER_IDS` — comma-separated subset for staged rollout (start small)
   - `ADMIN_AUDIT_VIEWS=true`
   - `POSTHOG_HOST` (default `https://app.posthog.com`), `POSTHOG_PROJECT_ID`, `POSTHOG_PROJECT_API_KEY` (mint a project API key in PostHog dashboard with scopes `person:read`, `events:read`, `session_recording:read`)
3. **Backend redeploy** so the new env vars propagate (env vars are read at module load).

## Adding a new admin

1. Get the new admin's Clerk user_id (visible in Clerk dashboard → Users; or query via `clerk_sync_service.get_user_by_email`).
2. Update Secrets Manager:

   ```bash
   aws secretsmanager get-secret-value --secret-id isol8/dev/backend-env \
     --query SecretString --output text --profile isol8-admin \
     | jq --arg id "$NEW_USER_ID" '
         .PLATFORM_ADMIN_USER_IDS = (.PLATFORM_ADMIN_USER_IDS + "," + $id | sub("^,"; "")) |
         .ADMIN_UI_ENABLED_USER_IDS = (.ADMIN_UI_ENABLED_USER_IDS + "," + $id | sub("^,"; ""))
       ' \
     | aws secretsmanager update-secret --secret-id isol8/dev/backend-env --secret-string file:///dev/stdin --profile isol8-admin
   ```

3. Redeploy backend. Within ~2 min the new admin can sign into `https://admin-{env}.isol8.co/admin` via Clerk and reach `/admin/users`.

## Removing an admin (immediate)

1. Remove their user_id from `PLATFORM_ADMIN_USER_IDS` in Secrets Manager (and `ADMIN_UI_ENABLED_USER_IDS`).
2. Redeploy backend. The next API call from any open admin session 403s.
3. Optional: revoke their Clerk sessions via another admin's UI: `Actions → /admin/users/{user_id}/account/force-signout`.

## Breaking glass — disable admin entirely

```bash
aws secretsmanager get-secret-value --secret-id isol8/{env}/backend-env \
  --query SecretString --output text --profile isol8-admin \
  | jq '.PLATFORM_ADMIN_USER_IDS = ""' \
  | aws secretsmanager update-secret --secret-id isol8/{env}/backend-env --secret-string file:///dev/stdin --profile isol8-admin
```

Redeploy backend. Every `/admin/*` API endpoint 403s within ~2 min. The Next.js middleware still serves the host so users hitting `admin.isol8.co/admin` see the not-authorized page (no information leak).

DNS alias and Vercel project remain. Once the incident is resolved, restore the env var and redeploy.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `/admin` returns 404 in browser | Wrong host (you're on `isol8.co/admin` instead of `admin.isol8.co/admin`); `ADMIN_UI_ENABLED=false`; or your Clerk user_id missing from `ADMIN_UI_ENABLED_USER_IDS` | Check URL; check Secrets Manager values |
| `/admin/me` returns 403 | Your Clerk user_id missing from `PLATFORM_ADMIN_USER_IDS` | Add it; redeploy |
| Admin page renders but Stripe panel shows error banner | Stripe API timeout or auth issue; `admin_service` returns partial responses on upstream failure | Check Stripe dashboard health; verify `STRIPE_SECRET_KEY` in Secrets Manager |
| PostHog tab shows "No PostHog activity recorded — user may not have visited the frontend" | User legitimately has no PostHog identify yet; OR `POSTHOG_PROJECT_API_KEY` is unset | Confirm by visiting the frontend as that user; otherwise mint the PostHog project key |
| CloudWatch Logs tab shows "no logs" | LocalStack (no real CWL); user hasn't generated logs in the time window; or IAM missing on the backend task role | Check task role has `logs:FilterLogEvents` on `arn:aws:logs:{region}:{account}:log-group:/ecs/isol8-{env}:*` (added in #355) |
| Write action returns `audit_status: "panic"` | DDB write to `admin-actions` failed after the action executed | Check CloudWatch for `ADMIN_AUDIT_PANIC` log entries; investigate DDB connectivity / IAM. The action *did* run; the audit row is missing. |

## When to add an edge gate (Phase 2 trigger)

V1 deliberately ships without an edge SSO gate to avoid adding a vendor. Defense relies on host-check + Clerk + `require_platform_admin` + audit.

Watch the `admin_api.errors` CloudWatch metric (added in Phase B) for repeated 403s on `/admin/me` from unknown IPs. If probe traffic appears, prioritize Phase 2 backlog item 14 — pick one of:

- **Cloudflare Access** — SSO gate in front of the subdomain. Requires Cloudflare as a vendor + DNS handover.
- **Vercel Deployment Protection** — Vercel-native password / SSO gate. Pro+ plan only.
- **HTTP basic auth via Next.js middleware** — ~15 LOC: if `host=admin.isol8.co` and no `Authorization: Basic` header, return 401 challenge. Username/password in `ADMIN_BASIC_AUTH_*` env vars. Zero new vendor.

## Local development

`apps/backend/.env.local` should include:

```
PLATFORM_ADMIN_USER_IDS=user_<your dev Clerk id>
ADMIN_UI_ENABLED=true
ADMIN_UI_ENABLED_USER_IDS=user_<your dev Clerk id>
ADMIN_AUDIT_VIEWS=true
# Stub PostHog — leave POSTHOG_PROJECT_API_KEY unset to short-circuit the API call
```

Frontend env (`apps/frontend/.env.local`):

```
NEXT_PUBLIC_ADMIN_HOSTS=admin.isol8.co,admin-dev.isol8.co,admin.localhost:3000
```

Then `pnpm dev` and visit `http://admin.localhost:3000/admin` (Chrome/Safari resolve `*.localhost` → 127.0.0.1 automatically — no `/etc/hosts` edit).

## Related

- [Phase B onwards](../superpowers/plans/2026-04-21-admin-dashboard.md) — backend router + frontend pages.
- `core/auth.py:242` — `require_platform_admin`.
- `apps/infra/lib/stacks/database-stack.ts` — `admin-actions` table.
