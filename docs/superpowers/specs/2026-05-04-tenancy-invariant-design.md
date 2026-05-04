# Tenancy Invariant — One Clerk User, One Tenancy

Date: 2026-05-04
Status: Draft

## Goal

Enforce a single product invariant: **a Clerk user has at most one active tenancy at a time — either a personal `billing_accounts` row (`owner_type=personal`) OR membership of an org (`owner_type=org`). Never both.**

Two enforcement gates land in code; one orphaned dual-state user (aden@isol8.co) plus one Clerk-deleted ghost container get wiped by hand. No new state, no Clerk metadata flag, no auto-migration, no roll-over UX.

## Why

On 2026-05-04, aden@isol8.co was invited to the `org_3DBS8G83oPrMm49yN2b70EjoFpN` org by admin@isol8.co. Instead of accepting the invite, he saw the personal ProviderPicker. Backend logs (2026-05-04T02:38:33Z, request_id 0cfd1c20-733c-40f1-9f1f-4e0df3815600) show `Reusing Stripe customer cus_UPnqlhwq2kvXYR for owner_id=user_3DEyqezB5b3wmW97mgsZFnIlSwJ (email=aden@isol8.co)` — the call resolved to his **personal** owner_id, not the org's. His JWT had no active org claim because Clerk never auto-activated the membership: he had previously completed personal onboarding, set `unsafeMetadata.onboarded=true`, and then `ChatLayout`'s `needsInvitationFlow` check (`!isOnboarded && !hasMemberships && hasPendingInvitations`) silently failed on the `!isOnboarded` term. He went straight to `/chat` in personal context, fell through the picker gate, and started another personal-tenancy onboarding alongside his (dormant) personal Stripe customer and a pending org invite.

Manual reproduction with a clean account confirmed the inverse: an email with no prior Isol8 history, invited to the same org, sees the invitation-acceptance screen on first sign-in and joins cleanly.

The provider-choice-per-owner work (PR #521 / #523, merged 2026-05-03) fixes the symptom for *new* invitees by making `provider_choice` owner-keyed. It does not prevent dual-state from forming in the first place. This spec closes that gap.

## Invariant

> A Clerk user has at most one active tenancy at any moment.
>
> - **Active personal tenancy**: a `billing_accounts` row keyed on the Clerk user_id with `subscription_status in ("active", "trialing")`.
> - **Active org tenancy**: membership of any Clerk organization (Clerk is authoritative).
>
> The two MUST NOT be simultaneously true for the same Clerk user.

The invariant is enforced at exactly two write boundaries, both *before* dual state can form. There is no runtime cross-check inside `resolve_owner_id` and no per-request reconciliation — we trust Clerk's JWT claim for active context and let the gates do their job upstream.

## Non-goals

- **Clerk `publicMetadata.tenancy_type` flag.** Considered and rejected. It would collapse gate checks to a single read but introduces three new sync points (trial-checkout, member-created webhook, subscription-deleted webhook) and a one-time backfill. The gates fire on rare events (org-admin invite clicks, personal trial-checkout starts), so the second lookup costs nothing. Revisit if a hot-path runtime check is ever added.
- **Auto-migration / roll-over UX.** No "convert my personal subscription into org membership" button. A user who wants to leave personal must cancel personally via the existing Stripe customer portal before the org invite can be sent.
- **Webhook-side enforcement on `organizationMembership.created`.** Both gates fire before the membership exists; by the time the webhook lands the invariant already holds. Adding a third check would be the kind of "owning state we shouldn't" pattern we're avoiding.
- **`user.deleted` webhook handler that tears down orphan personal containers.** The `user_3CxcOiaf5GaHb69Gv1B7IYj8MBG` ghost container is its own ticket (also flagged in the provider-choice-per-owner spec). Step 1 wipes it manually as a one-shot; the recurring webhook handler is out of scope here.
- **Multi-org-per-user.** Still one org per user (`memory/project_single_org_per_user.md`). Re-evaluate if that ever changes.
- **Backfill scan for other dual-state users.** We know of two dirty rows today (aden + the orphan). If any others exist, Gate A will surface them organically the next time an admin tries to invite them — they keep working as personal until then.

## Step 1 — One-time wipe (ops, not code)

Two known dirty states get wiped manually with the `isol8-admin` AWS profile. Both have already been verified via the prod cluster service list (`aws ecs list-services`) and Stripe customer logs.

| State | Identifier | Source of truth |
|---|---|---|
| **Orphan ghost** | `user_3CxcOiaf5GaHb69Gv1B7IYj8MBG` | Verify via Clerk dashboard search before wiping. Per the provider-choice-per-owner spec it was deleted from Clerk on or before 2026-05-03; if Clerk dashboard now shows the user does not exist, proceed. If it shows a live user with a non-aden email, stop and contact them first. |
| **Aden personal** | `user_3DEyqezB5b3wmW97mgsZFnIlSwJ` (email: aden@isol8.co) | Confirmed via 2026-05-04T02:38:33Z log line in `/ecs/isol8-prod`. Aden's Clerk user is kept; only the personal billing/container/Stripe artifacts are wiped, leaving his pending org invite intact so he can accept on next sign-in. |

For each owner_id, the wipe removes:

1. **ECS service** — `aws ecs delete-service --cluster isol8-prod-container-ClusterEB0386A7-Uc0EwgAC9DcQ --service openclaw-{owner_id}-{hash} --force --profile isol8-admin --region us-east-1`. (Aden's is already gone; orphan's is live.)
2. **EFS access point + workspace dir** — list APs filtered by tag, delete the matching AP, then `rm -rf /mnt/efs/users/{owner_id}` via ECS-exec on the backend task (procedure mirrors the dev clean-slate runbook in CLAUDE.md, `isol8-admin` profile, prod cluster).
3. **Stripe** — for aden, cancel any active sub on `cus_UPnqlhwq2kvXYR` and delete the customer record from the dashboard (the user has stated they will do this manually). For the orphan, check whether a customer exists and cancel + delete if found.
4. **DynamoDB** — delete by primary key from each of the eight per-user tables: `isol8-prod-users`, `isol8-prod-billing-accounts`, `isol8-prod-containers`, `isol8-prod-api-keys`, `isol8-prod-usage-counters`, `isol8-prod-pending-updates`, `isol8-prod-channel-links`, `isol8-prod-ws-connections`. Item shapes match the dev wipe loop in CLAUDE.md.
5. **Clerk user** — leave alone for both. Aden needs his Clerk identity to accept the pending invite; the orphan is already deleted from Clerk.

After Step 1: aden logs in → no personal billing row → `ChatLayout`'s `needsInvitationFlow` recomputes (`hasPendingInvitations=true`, `!hasMemberships=true`, `!isOnboarded` is still false but the fix in Step 2c addresses that) → he lands on `/onboarding/invitations` → accepts → org context activates → done.

This step has no code deliverable — it's a runbook executed once. No script is committed because there is exactly one user to clean up (plus one already-dead ghost), and the procedure is the same per-user loop already documented for dev resets.

## Step 2 — Code changes

### 2a. Gate A: invite-creation backend endpoint

**New router**: `apps/backend/routers/orgs.py`. Mounted under `/api/v1/orgs`. Single endpoint:

```python
@router.post("/{org_id}/invitations", status_code=201)
async def create_invitation(
    org_id: str,
    body: CreateInvitationRequest,  # { email: EmailStr, role: Literal["org:admin", "basic_member"] }
    auth: AuthContext = Depends(require_org_admin),
) -> CreateInvitationResponse:  # { invitation_id: str }
    # Caller must be admin of the target org
    if auth.org_id != org_id:
        raise HTTPException(403, "Cannot invite to a different org")

    # Look up the invitee in Clerk by email
    existing = await clerk_admin.find_user_by_email(body.email.lower())
    if existing is not None:
        # If they already have an active personal subscription, refuse.
        # billing_accounts is keyed on Clerk user_id for personal tenancies,
        # so a row + active/trialing status === active personal tenancy.
        account = await billing_repo.get_by_owner_id(existing["id"])
        if account and account.get("subscription_status") in ("active", "trialing"):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "personal_user_exists",
                    "message": (
                        f"{body.email} already has an active personal Isol8 "
                        "subscription. They must cancel it before they can "
                        "be invited to an organization."
                    ),
                },
            )

    # Forward to Clerk's createInvitation API
    invite = await clerk_admin.create_organization_invitation(
        org_id=org_id,
        email=body.email,
        role=body.role,
        inviter_user_id=auth.user_id,
    )
    put_metric("orgs.invitation.created", dimensions={"role": body.role})
    return CreateInvitationResponse(invitation_id=invite["id"])
```

**Clerk admin helpers** live in `core/services/clerk_admin.py` (file already exists). Two new methods:
- `find_user_by_email(email: str) -> dict | None` — wraps `GET https://api.clerk.com/v1/users?email_address=<email>&limit=1`, returns first result or None.
- `create_organization_invitation(org_id, email, role, inviter_user_id) -> dict` — wraps `POST /v1/organizations/{org_id}/invitations` with the standard Bearer secret-key auth.

**Schemas** added to a new `apps/backend/schemas/orgs.py`:

```python
class CreateInvitationRequest(BaseModel):
    email: EmailStr
    role: Literal["org:admin", "basic_member"] = "basic_member"

class CreateInvitationResponse(BaseModel):
    invitation_id: str
```

The endpoint is mounted in `main.py` alongside the other routers. No DDB writes happen here — Clerk owns the invitation state.

### 2b. Gate B: personal trial-checkout pending-invite check

`apps/backend/routers/billing.py:/trial-checkout` (around line 320, before any Stripe work):

```python
# Tenancy invariant: refuse personal subscription if the caller has any
# pending org invitations. Otherwise we'd race the user into a personal
# tenancy while a valid org invite is sitting in their inbox.
if not auth.is_org_context:
    pending = await clerk_admin.list_pending_invitations_for_user(auth.user_id)
    if pending:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "pending_org_invitation",
                "message": (
                    "You have a pending invitation to "
                    f"{pending[0]['public_organization_data']['name']}. "
                    "Accept it before subscribing personally."
                ),
                "redirect_to": "/onboarding/invitations",
            },
        )
```

`clerk_admin.list_pending_invitations_for_user(user_id)` wraps `GET https://api.clerk.com/v1/users/{user_id}/organization_invitations?status=pending`.

`is_org_context` short-circuit: if the caller is already inside an org context, `/trial-checkout` is creating an *org* subscription (the existing flow), not a personal one. The pending-invite check only matters when they'd be opening a *personal* tenancy.

The frontend handles the 409 by redirecting to `/onboarding/invitations` (already a route — see 2d).

### 2c. Frontend: custom invite dialog (replacing Clerk's built-in surface)

Today, `apps/frontend/src/app/onboarding/page.tsx:188` mounts Clerk's `<CreateOrganization skipInvitationScreen={false}>`. That component handles both org creation *and* the invite-people step, calling Clerk's API directly — our backend never sees the invitations, so Gate A would be bypassed.

Two changes:

1. **In `/onboarding`**: switch to `<CreateOrganization skipInvitationScreen={true} ...>`. After Clerk creates the org and `setActive` flips the JWT to org context, render our own `<InviteTeammatesStep>` component before redirecting to `/chat`.

2. **New component**: `apps/frontend/src/components/onboarding/InviteTeammatesStep.tsx`. Form with email + role (default "Member"), submits to `POST /api/v1/orgs/{org_id}/invitations`. Renders the 409 inline with the message string from the backend. Optional "Skip for now" button that just calls `router.push("/chat")`.

3. **Settings → Members**: any other surface that lets an org admin invite teammates today must also route through our endpoint. There's currently no `/settings/members` page in the codebase — confirmed via `grep -rn "OrganizationProfile" apps/frontend/src` returning zero matches outside of the onboarding flow. If/when one is added, it MUST use this endpoint, not Clerk's built-in `<OrganizationProfile />` modal. Add a `// CODEOWNERS` comment in `clerk_admin.py` warning future contributors.

`<OrganizationSwitcher />` is fine — it doesn't expose an invite surface; it only switches active org for users who are already members.

### 2d. Frontend: tighten `/onboarding` routing for pending-invite users

Today `apps/frontend/src/app/onboarding/page.tsx:37` derives the mode as:

```ts
const mode = explicitMode ?? (isLoaded && orgsLoaded && pendingInvitations.length > 0 ? "invitations" : "choose");
```

The `?? explicitMode` escape hatch means the user can hit "Skip invitations" (line 171) and fall back to the personal/org chooser even when they have a pending invite. That's the manual override that lets the bug class form (user clicks "Skip", goes to personal, subscribes personally, never accepts the invite).

**Change**: when `pendingInvitations.length > 0`, force `mode = "invitations"`. Remove the "Skip invitations" button. The user can still choose which invitation to accept (if multiple), but cannot route around them into personal. The component stays small — it's removing two lines of escape-hatch logic.

Aden specifically: after Step 1 wipes his personal billing, his next sign-in still has `unsafeMetadata.onboarded=true` from the previous personal flow. `ChatLayout`'s `needsInvitationFlow` uses `!isOnboarded` to decide whether to redirect to `/onboarding`. That check needs to relax: if `hasPendingInvitations && !hasMemberships && !organization`, redirect regardless of `isOnboarded`. The `onboarded` flag becomes "user has chosen *some* tenancy"; pending invitations override it because the invariant says they shouldn't have a different tenancy yet.

**Concrete edit** in `apps/frontend/src/components/chat/ChatLayout.tsx` around line 138:

```ts
// Old:
const needsInvitationFlow = clerkLoaded && isSignedIn === true && !isOnboarded && !hasMemberships && hasPendingInvitations && !organization;

// New: pending invitations beat the onboarded flag — invariant says
// a user can't be in personal tenancy AND have a pending org invite.
const needsInvitationFlow = clerkLoaded && isSignedIn === true && !hasMemberships && hasPendingInvitations && !organization;
```

The `!isOnboarded` removal is the load-bearing change. Everything else stays.

### 2e. Defense-in-depth: Clerk webhook on `organizationMembership.created`

This is the *only* webhook-side concession. Not enforcement — observability.

`apps/backend/routers/webhooks.py` already handles `organizationMembership.created` to provision the user's per-member workspace. Add a single check at the top of that handler:

```python
member_user_id = payload["data"]["public_user_data"]["user_id"]
account = await billing_repo.get_by_owner_id(member_user_id)
if account and account.get("subscription_status") in ("active", "trialing"):
    # Invariant violation: gates A+B should have prevented this.
    # Don't refuse activation (Clerk has already accepted the membership) —
    # log loudly so we can investigate and clean up by hand.
    logger.error(
        "tenancy_invariant.violated user=%s org=%s personal_status=%s",
        member_user_id, payload["data"]["organization"]["id"],
        account["subscription_status"],
    )
    put_metric("tenancy_invariant.violation", dimensions={"path": "membership_created"})
```

The metric should be zero in steady state. A non-zero count means a gate leaked — alarm on it via the observability stack. This is *not* a write; it's a no-op observer. It does not "own" any state, doesn't decide tenancy, doesn't migrate anything.

## What this explicitly does NOT do

- ❌ Does not add `publicMetadata.tenancy_type` or any other Clerk metadata field.
- ❌ Does not add an `is_personal` column or any tenancy flag to DDB.
- ❌ Does not run a migration script. Aden's wipe is a hand-executed runbook, not a committed `migrate_*.py`.
- ❌ Does not auto-cancel a user's personal subscription when they accept an org invite. If admin tries to invite a user with personal billing, the invite is *refused* — the would-be invitee must cancel personally first.
- ❌ Does not add runtime cross-checks inside `resolve_owner_id`, `get_billing_account`, or any per-request hot path. Gates A+B fire before dual state can form; once the JWT is settled, we trust it.
- ❌ Does not handle the orphan user lifecycle generally (Clerk `user.deleted` → resource teardown). Out of scope; tracked separately.
- ❌ Does not change provider-choice resolution, billing-account schemas, or any of the work merged in PR #521 / #523.

## Tests

**Backend, new file `apps/backend/tests/unit/routers/test_orgs_invitations.py`**:

- `test_invite_to_email_with_no_clerk_user_succeeds` — Clerk lookup returns None, gate passes, Clerk createInvitation called.
- `test_invite_to_email_with_clerk_user_no_billing_succeeds` — Clerk user exists, `billing_repo.get_by_owner_id` returns None, gate passes.
- `test_invite_to_email_with_inactive_billing_succeeds` — Clerk user exists, billing row exists with `subscription_status="canceled"`, gate passes (canceled ≠ active).
- `test_invite_to_email_with_active_personal_returns_409` — full unhappy path; assert response code, body shape (`detail.code == "personal_user_exists"`), and that Clerk createInvitation was NOT called.
- `test_invite_to_email_with_trialing_personal_returns_409` — same as above with `subscription_status="trialing"`.
- `test_non_admin_caller_returns_403` — `require_org_admin` dependency rejects basic members.
- `test_caller_in_different_org_returns_403` — body `org_id` mismatches `auth.org_id`.

**Backend, in `apps/backend/tests/unit/routers/test_billing_trial_checkout_guard.py`** (extend existing file):

- `test_trial_checkout_with_pending_org_invitation_returns_409` — mock Clerk pending-invitations list to return a non-empty result, assert 409 + `detail.code == "pending_org_invitation"`.
- `test_trial_checkout_in_org_context_skips_pending_invite_check` — `auth.is_org_context=True`, Clerk admin should not be called.

**Backend, in `apps/backend/tests/unit/routers/test_webhooks.py`**:

- `test_membership_created_with_active_personal_logs_violation` — assert error log emitted + metric incremented; provisioning still proceeds.

**Frontend, new test `apps/frontend/src/app/onboarding/__tests__/page.test.tsx`**:

- `pending_invitations_force_invitation_mode` — mock `userInvitations.data` non-empty, assert "Skip invitations" button is absent and personal/org chooser does not render.

**Frontend, in `apps/frontend/src/components/chat/__tests__/ProvisioningStepper.test.tsx`** or sibling: a smoke test that `ChatLayout`'s `needsInvitationFlow` no longer requires `!isOnboarded`. May live in a new `ChatLayout.test.tsx` if no test currently covers that derivation.

**Frontend, new test for `<InviteTeammatesStep>`**:

- Renders form, submits to backend mock, displays inline error on 409 `personal_user_exists`.

## Rollout

Single PR. Deploy must happen BEFORE the wipe, not after — explained below.

1. **Merge PR + deploy** (backend + frontend together; one PR, two pipelines). At this point Gate A starts refusing invites to existing personal subscribers, Gate B starts refusing personal trial-checkout for users with pending invites, and the relaxed `needsInvitationFlow` in `ChatLayout.tsx` starts honouring pending invites regardless of `unsafeMetadata.onboarded`.

2. **Wipe aden + orphan** (manual ops, after deploy). Order matters: aden's `unsafeMetadata.onboarded=true` is still set from his earlier personal flow, and only the relaxed routing in 2d makes `needsInvitationFlow` fire for an "already-onboarded" user with a pending invite. If we wiped before deploy, aden's next sign-in would land on `/chat`, find no billing row, and re-trigger the ProviderPicker for a fresh personal flow — same bug class. After deploy + wipe, his next sign-in routes to `/onboarding/invitations` automatically.

3. **Verify post-wipe**: aden signs in → lands on `/onboarding/invitations` → accepts → org context activates → reaches `/chat` with `provider_choice` already set on the org's billing row → no picker.

4. **Smoke-test the gates**: send a test invite to a brand-new email → succeeds. Send an invite to an email with a known active personal sub (a test account) → 409 surfaces in the new dialog. Try `/billing/trial-checkout` from a Clerk user with a pending invite → 409 + redirect to `/onboarding/invitations`.

No feature flag. No DB schema migration. The blast radius is org-admin invite UX (changes from Clerk's modal to ours) and the personal-checkout race window.

## Out of scope (cross-references)

- **Clerk `user.deleted` → orphan-resource teardown**. The `user_3CxcOiaf5GaHb69Gv1B7IYj8MBG` ghost container is the live evidence. Own ticket.
- **Tenancy switch UX** ("I want to leave personal and become an org admin" / "leave the org and go personal"). Today, lock-in is permanent without manual ops. Own design.
- **Multi-org-per-user**. Still one org per user.
- **`<OrganizationProfile />` mounted anywhere**. None today; if added later, must route invite ops through the new endpoint.
