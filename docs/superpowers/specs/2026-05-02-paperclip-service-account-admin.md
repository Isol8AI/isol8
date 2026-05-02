# Paperclip service-account admin (`admin@isol8.co`)

## Problem

`paperclip_provisioning.provision_org` currently signs up each new user in Paperclip and immediately uses that user's session to call `POST /api/companies`. Paperclip enforces `req.actor.source === "local_implicit" || req.actor.isInstanceAdmin` on that endpoint (`paperclip/server/src/routes/companies.ts:269`); newly-signed-up users are neither, so the call fails with 403 and provisioning leaves a `status="failed"` row in DDB.

Switching Paperclip to `local_trusted` deployment mode would make every request implicit-admin, which loses per-user authz isolation. Not acceptable.

## Solution

A single Paperclip-internal service account (`admin@isol8.co`) that holds the `instance_admin` role. Backend reads its credentials from Secrets Manager, signs into Paperclip as that admin, and uses the admin session for the privileged steps of provisioning. Per-user requests through the proxy continue to use each user's own session.

## Architecture

```
Isol8 backend (FastAPI)
  │
  ├── per-user request → sign in as user → forward to Paperclip
  │   (unchanged, used for serving Paperclip UI through the proxy)
  │
  └── provisioning request →
        1. (no auth) Better Auth sign_up_user(new_user_email)
        2. ADMIN session: POST /api/companies (was failing, admin can do this)
        3. ADMIN session: add new user as company owner via membership API
        4. ADMIN session: create Main Agent
        5. persist DDB row
```

## Components

### One-time bootstrap (operator step, ~5 min per env)

A Python script in `apps/backend/scripts/bootstrap_paperclip_admin.py`, runnable as a one-shot ECS task (mirroring the existing `migrateTaskDefinition` pattern in `paperclip-stack.ts`).

The script:

1. Reads `PAPERCLIP_INTERNAL_URL` from env
2. Hits Better Auth signup at that URL with email=`admin@isol8.co`, password=32-byte random
3. Prints the **board-claim URL** Paperclip exposes on first deploy (operator opens it in a browser, signs in as admin@isol8.co, claims the board → Paperclip writes `instance_admin` role)
4. Writes `{email, password}` to Secrets Manager at `isol8/{env}/paperclip_admin_credentials`

Operator runbook documented in `apps/infra/paperclip/RUNBOOK.md`.

Why operator step: Paperclip's `instance_admin` promotion requires the board-claim URL flow (security feature — prevents network-reachable attackers from auto-promoting). Direct DB writes would be more invasive than a 30-second URL click.

### Admin session manager

New module `apps/backend/core/services/paperclip_admin_session.py`:

- Reads admin credentials from Secrets Manager at process startup (cached for process lifetime)
- Maintains a long-lived Better Auth session token for admin@isol8.co
- Re-signs-in on first request after process start, on 401 from any admin call, or after `BETTER_AUTH_SESSION_TTL` (~1 day default)
- Async-safe: serializes concurrent re-sign-in attempts with an asyncio lock

Public surface: `await get_admin_session_token() -> str`.

### Updated provision_org

In `apps/backend/core/services/paperclip_provisioning.py`:

```
async def provision_org(self, *, org_id, owner_user_id, owner_email):
    existing = await self._repo.get(owner_user_id)
    if existing and existing.status == "active": return existing
    
    password = secrets.token_urlsafe(32)
    
    # 1. Public Better Auth signup — doesn't need admin
    signup = await self._admin.sign_up_user(email=owner_email, password=password, name=owner_email)
    new_user_id = signup["user"]["id"]
    user_session_token = signup["token"]  # for the seeded Main Agent (acts as user)
    
    # 2. Get admin session
    admin_token = await get_admin_session_token()
    
    # 3. Admin creates the company
    company = await self._admin.create_company(
        name=owner_email,
        description="Isol8 Teams workspace",
        session_token=admin_token,
        idempotency_key=owner_user_id,
    )
    
    # 4. Admin adds new user as company owner
    await self._admin.add_company_member(
        company_id=company["id"],
        user_id=new_user_id,
        role="owner",
        session_token=admin_token,
    )
    
    # 5. Mint service token + create Main Agent (as user — they own it)
    svc_token = service_token.mint(owner_user_id)
    await self._admin.create_agent(
        company_id=company["id"],
        ...adapter config...,
        session_token=user_session_token,  # user owns the agent
        idempotency_key=f"{owner_user_id}:main-agent",
    )
    
    # 6. Persist row
    await self._repo.put(...)
```

### Admin client extension

In `apps/backend/core/services/paperclip_admin_client.py`, add `add_company_member(company_id, user_id, role, session_token)` that POSTs to whatever Paperclip's membership endpoint is. (Need to inspect Paperclip source to confirm path; likely `POST /api/companies/{companyId}/memberships`.)

### Secrets Manager + IAM

- New secret in `auth-stack.ts`: `isol8/{env}/paperclip_admin_credentials`
- `service-stack.ts` grants the backend task role read access on it
- KMS decrypt grant (same CMK as other auth secrets)

### Bootstrap one-shot task definition

Add a `bootstrapAdminTaskDefinition` in `paperclip-stack.ts` parallel to `migrateTaskDefinition`. Operator runs it via `aws ecs run-task` after first deploy of each env.

## What stays the same

- Paperclip stays in `authenticated` deployment mode
- Per-user proxy requests still use each user's own session
- DDB schema unchanged
- Cookie/handoff/proxy auth flow unchanged
- The single-org-per-user invariant unchanged (each user gets their own one-user company)

## Out of scope

- Multi-member orgs (provision_member already exists for this; out of scope for this fix)
- Rotating admin credentials (manual via re-running bootstrap script)
- Removing admin from companies after creating them (admin stays as co-owner; harmless)

## Risks

- **Bootstrap step skipped on a new env** → backend logs "no admin credentials" at startup; provisioning fails with clear error. Detectable by missing secret.
- **Admin session expires mid-provision** → admin session manager refreshes on 401, retries once. Provision succeeds.
- **Admin password rotates without secret update** → all provisioning fails. Operator re-runs bootstrap script.
- **Paperclip's membership API doesn't exist** at the assumed path → discover during implementation, adapt to whatever Paperclip exposes (check `paperclip/server/src/routes/access.ts` or similar).
