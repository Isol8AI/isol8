# Provider Choice Per Owner — Design

Date: 2026-05-03
Status: Draft

## Goal

Move `provider_choice` (and its sibling `byo_provider`) off the `users` table — where it's incorrectly keyed on the human caller — onto `billing_accounts`, where it's keyed on the owner (personal user or org). Update every reader to consult `billing_accounts`. Add the missing server-side guard that prevents `chatgpt_oauth` from being set on org-owners. Filter the frontend picker so org users see only Bedrock and BYO API key.

## Why

On 2026-05-03, admin@isol8.co's prod org sat 80 minutes on "Provisioning your container…" The first ten provision attempts hit a 402 (`bedrock_claude` + $0 credits — separate root cause, see the provision-gate-ui spec). The eleventh, made by a *different* org member (`user_3CxcOiaf5GaHb69Gv1B7IYj8MBG`, since deleted from Clerk), 503'd with "No ChatGPT OAuth tokens for owner org_3DBS…". That ghost member's `users.provider_choice = chatgpt_oauth` was used as the org's provider choice because `_resolve_provider_choice` keys on the calling Clerk user, not the owner. Two members in one org could resolve to two different providers; OAuth tokens are owner-keyed (and orgs can't have any), so the chatgpt_oauth path always fails for orgs.

Per a 2026-04-30 product decision (`memory/project_chatgpt_oauth_personal_only.md`) **orgs have two valid options — Bedrock or BYO API key (OpenAI/Anthropic).** ChatGPT OAuth is personal-only. The frontend picker shows all three cards regardless of context, the backend has the guard for one write path (`/billing/trial-checkout`) but not the other (`/users/sync`), and storage lets a per-user choice silently override an org's intent. This design closes those gaps by making the choice an owner-level fact.

## Non-goals

- **Switch-provider UI** — own design (deferred). Today an owner is locked into their initial choice; that stays true.
- **Clerk `user.deleted` webhook handler** that tears down orphan personal containers. The `user_3Cxc` container running idle on EFS since 2026-05-01 is its own ticket.
- **OAuth token storage migration** — tokens stay keyed on `owner_id`. Orgs won't have any once the picker filter and backend guard land.
- **BYOK-in-org semantics** — today an org with `provider_choice = byo_key` uses one BYOK key (whichever member's key landed in `openclaw.json` first). That's already broken for multi-member orgs and deserves its own design. Out of scope here.
- **Multi-org-per-user** — still one org per user (`memory/project_single_org_per_user.md`). Revisit if that changes.

## Storage

Two new fields on `billing_accounts` items (DDB is schemaless, no migration ceremony):

| field             | type   | values                                              | required                                  |
| ----------------- | ------ | --------------------------------------------------- | ----------------------------------------- |
| `provider_choice` | string | `bedrock_claude` \| `byo_key` \| `chatgpt_oauth`    | yes (after onboarding)                    |
| `byo_provider`    | string | `openai` \| `anthropic` (extensible)                | only when `provider_choice == byo_key`    |

`billing_accounts` already stores `owner_type` (`personal` or `org`) — set by `billing_repo.create_if_not_exists`. The org invariant uses it without any other plumbing.

**Org invariant** — enforced at the repository layer (and at the router boundary as defense-in-depth):
- if `owner_type == "org"`, `provider_choice ∈ {bedrock_claude, byo_key}`. `chatgpt_oauth` is a `ValueError` from the repo, a `403` from the router.

**Removed from `users` table** in a follow-up cleanup PR (see Rollout): `provider_choice` and `byo_provider`. Removed only after dashboards confirm zero reads from the legacy fields.

## Repository surface

**`core/repositories/billing_repo.py`** — add:

```python
async def set_provider_choice(
    owner_id: str,
    *,
    provider_choice: str,
    byo_provider: str | None,
    owner_type: str,  # "personal" | "org" — caller passes from the row
) -> None:
    if provider_choice not in ("bedrock_claude", "byo_key", "chatgpt_oauth"):
        raise ValueError(f"unknown provider_choice: {provider_choice!r}")
    if owner_type == "org" and provider_choice == "chatgpt_oauth":
        raise ValueError("chatgpt_oauth is not allowed for org owners")
    if provider_choice == "byo_key" and byo_provider is None:
        raise ValueError("byo_provider required for byo_key")
    # ... atomic SET on the row, REMOVE byo_provider when not byo_key
```

Plus `clear_provider_choice(owner_id)` for parity.

A small typed helper `ProviderChoice(provider_choice: str, byo_provider: str | None)` lives next to the existing `schemas/billing.py` Pydantic models — callers pass one object instead of two correlated strings.

**`core/repositories/user_repo.py`** — delete `set_provider_choice` and `clear_provider_choice` (after the cleanup PR; first PR keeps them so the migration script can no-op-read from there). The other methods on user_repo are unchanged.

## Call-site changes (verified against main)

### Reads to migrate (5 sites)

`apps/backend/routers/container.py`:
- `_resolve_provider_choice(clerk_user_id)` → `_resolve_provider_choice(owner_id)`. Body switches from `user_repo.get(...)` to `billing_repo.get_by_owner_id(...)`.
- Callers update at the function boundary only — they already have `owner_id` in scope:
  - `_assert_provision_allowed` line 94 (currently passes `clerk_user_id`)
  - `_background_provision` line 137
  - `container_provision` (around line 353)
- `_assert_provision_allowed` is itself called at lines 226, 347, 392 — its signature simplifies (drop `clerk_user_id`, owner_id is enough now).

`apps/backend/core/gateway/connection_pool.py`:
- Line 751 (chat-time provider check) and line 1129 (credit-deduct gate). Both currently call `user_repo.get(billing_user_id).provider_choice`. **Important nuance:** `billing_user_id` resolves to the *member* who sent the chat (`member_user_id` or `parsed["member_id"] or self.user_id`). After migration the **provider_choice lookup keys on `owner_id` (the org/personal owner)**, not the member. Credits stay keyed on the member (the credit ledger is intentionally per-member; that's correct).

`apps/backend/routers/users.py`:
- `GET /users/me` line 103 returns `user.provider_choice` for the frontend `LLMPanel`. Switch to read from `billing_repo.get_by_owner_id(resolve_owner_id(auth))`. Returning `None` when no billing row exists is fine (the panel already handles it).

### Writes to migrate (3 sites)

`apps/backend/routers/billing.py`:
- `/trial-checkout` (line ~318) already validates and threads `provider_choice` into Stripe metadata. **Add a synchronous `billing_repo.set_provider_choice(...)` call right after the `_get_billing_account` / `create_customer_for_owner` block (around line 360), before `create_flat_fee_checkout`.** This closes the race window where the user lands on `/chat` and triggers `/container/provision` before the `customer.subscription.created` webhook lands. Without this synchronous write, dropping the `/users/sync` write (below) leaves a multi-second hole during which provision reads no `provider_choice` from `billing_accounts`.
- The downstream **webhook handler** (`customer.subscription.created`, line ~620) currently does `user_repo.set_provider_choice(metadata_clerk_user_id, ...)`. Switch to `billing_repo.set_provider_choice(account["owner_id"], owner_type=account["owner_type"], ...)`. With the synchronous write above, this becomes an idempotent backup writer — covers metadata-only paths (e.g., a user resuming a partially-created Stripe session, or any future webhook-only entry point).
- The `clerk_user_id` threading through subscription metadata is no longer load-bearing (only `owner_id` matters), but keep the field for backwards-compat — old in-flight Stripe subscriptions still carry it.
- The `is_org_context` guard at line 335 stays exactly as is.

`apps/backend/routers/users.py`:
- `POST /users/sync` currently writes `provider_choice` to `user_repo` if present in the body. **Migration of this write is non-trivial** because of the existing comment on the endpoint:
  > `// no billing-account creation here. /users/sync fires from multiple places (ChatLayout mount, onboarding, settings)`
- Two options. **Recommended:** stop accepting `provider_choice` on `/users/sync` entirely. The frontend already calls `/users/sync` then `/trial-checkout` in sequence in `ProvisioningStepper`; let `/trial-checkout` be the sole writer (it already creates the billing row and fires the webhook that persists the choice). Frontend changes accordingly.
- If we keep `/users/sync` accepting `provider_choice`, it would need to lazily create the billing row, which fights the existing design intent. Picking the recommended path is cleaner and matches the per-owner model.

`apps/backend/core/services/billing_service.py`:
- `create_flat_fee_checkout(provider_choice=…)` (lines 147, 193, 210) — signature unchanged. Source of `provider_choice` is the request body (already wired). No code change here.

### Pass-through plumbing (unchanged signatures)

`apps/backend/core/containers/config.py:write_openclaw_config(provider_choice=…)` (lines 311+, 442+, 672+) and `apps/backend/core/containers/ecs_manager.py:provision_user_container(provider_choice=…)` (lines 1041+, 1319, 1507+) take `provider_choice` as a parameter. Origin of the value changes (read from `billing_repo` upstream); the function bodies stay the same.

### Tests

Update mocks; add new tests for the org invariant.

- `tests/unit/repositories/test_user_repo.py` — drop the `set_provider_choice` / `clear_provider_choice` cases.
- New: `tests/unit/repositories/test_billing_repo_provider_choice.py` — covers the org invariant rejection + happy path + byo_provider validation.
- `tests/unit/routers/test_container_provision_gating.py` (lines 111, 149, 189, 230) — flip mocks from `user_repo.get(...)` returning `{provider_choice: ...}` to `billing_repo.get_by_owner_id(...)`.
- `tests/unit/routers/test_container_paperclip_autoprovision.py` (lines 145, 204) — same flip.
- `tests/unit/routers/test_container_recover.py` — its docstring mentions "Recovery now reads provider_choice from user_repo before…" — update to billing_repo.
- `tests/unit/routers/test_users.py:test_sync_persists_provider_choice` and friends — change to assert `provider_choice` is **not** persisted by `/users/sync` (the recommended path drops the write).
- `tests/unit/routers/test_billing.py` (line 296+) — the webhook persistence test currently mocks `user_repo.set_provider_choice`; flip to `billing_repo.set_provider_choice`. Pass through `owner_type`.
- `tests/unit/routers/test_billing_trial_checkout_guard.py` — already covers the org guard for trial-checkout. Add a parallel test for the new repo-level invariant.

## Frontend changes

`apps/frontend/src/components/chat/ProvisioningStepper.tsx`:

- **Skip the picker entirely for org members joining an org that's already onboarded.** The picker MUST only render when `billing_accounts.provider_choice` is null AND the caller is the org admin (or in personal context). Today, a new org member (e.g. an invited cofounder) lands on `/chat`, the picker reads `users.provider_choice` (null for the new user) and renders the onboarding flow as if they were the org admin. Real bug: an invited cofounder accepting an org invite was prompted to pick a provider despite the org already running on Bedrock. After this work, the picker reads from billing-accounts (per-owner), sees the choice is set, and falls through to normal provisioning UX.
- `ProviderPicker` (line 1028) already accepts `isOrg` (passed from line 551). Add the filter: `if (isOrg) cards = cards.filter(c => c.id !== "chatgpt_oauth")`. Update the section heading copy for the org case so subhead doesn't promise three options.
- The picker's `handlePick` currently calls `await api.post("/users/sync", { provider_choice: providerChoice })` (line 502). **Remove this call.** The choice is held in component state and posted to `/billing/trial-checkout` when the user clicks "Subscribe."
- Confirm `LLMPanel` (used by `/settings`) reads provider_choice via `GET /users/me` — the endpoint's response shape stays the same (still returns `{provider_choice, byo_provider}`); just the source on the backend changes.

The "skip picker for already-onboarded orgs" behavior also needs a backend signal: `GET /billing/account` (or `GET /users/me`) must return `provider_choice` from the billing-row source. The existing `GET /billing/account` already returns the billing row's relevant fields, so adding `provider_choice` there is one line.

No new frontend components. Three existing files touched (picker filter + dropped `/users/sync` write + the "skip picker if billing.provider_choice is set" check).

## Server-side enforcement (defense in depth)

The picker filter is presentation-layer; an old client, dev tools, or a future API consumer can still POST `chatgpt_oauth` for an org. Two enforcement layers:

1. **Router-level guard** at every write entry point:
   - `routers/billing.py:335` already has the `is_org_context + chatgpt_oauth → 403` check on `/trial-checkout`. Keep it.
   - `routers/users.py` if `/users/sync` keeps accepting provider_choice (not the recommended path) needs the same guard. If the recommended path is taken (drop the write), no guard needed because there's nothing to guard.
2. **Repository-level invariant** — inside `billing_repo.set_provider_choice`. Belt-and-suspenders so any future write site can't bypass.

## Migration script

A one-shot script — `apps/backend/scripts/migrate_provider_choice.py` — does the backfill in a single pass:

```
For each users row with provider_choice set:
  1. Look up the user's billing_account row(s):
     - Personal owner_id == clerk_user_id (1 row).
     - Org owner_id from Clerk org membership (one org per user).
       At most 1 personal + 1 org row per user.
  2. For each billing row:
     - If row already has provider_choice, skip (idempotent).
     - If owner_type == "org" and user's choice is chatgpt_oauth,
       skip and log (org invariant — choice will be re-prompted on
       next provision).
     - Otherwise, write provider_choice (and byo_provider) to the
       billing row via billing_repo.set_provider_choice.
  3. Leave the user row's provider_choice alone — the cleanup PR
     deletes it.
Print: rows scanned / migrated / skipped / org-invariant violations.
```

**Run mode:** invoked manually as a one-off via `aws ecs run-task` with the migration command override after the new code deploys. Idempotent — re-running is safe.

**Why a script not a Lambda:** the backend already has all the boto3 / repo / Clerk-client plumbing. ~100 lines in `apps/backend/scripts/` reuses everything — no IAM/VPC duplication.

**Manual verification post-run:**
- `aws dynamodb scan billing_accounts --filter-expression "attribute_exists(provider_choice)"` count → matches pre-migration users count minus org-invariant skips.
- Spot-check a few rows in each owner_type.

## Rollout

**PR 1 — main migration:**
1. `billing_repo.set_provider_choice` + invariant + tests.
2. Migrate readers (`routers/container.py`, `core/gateway/connection_pool.py`, `routers/users.py:get_me`) to billing-row source.
3. Migrate webhook write (`routers/billing.py`) to billing-row destination.
4. Drop `provider_choice` accept on `/users/sync` (recommended path) and update tests.
5. Frontend picker filter (`isOrg` → drop chatgpt_oauth) and removal of the `/users/sync` write in `handlePick`.
6. Migration script.

**Deploy order:**
1. Ship PR 1.
2. Run the migration script on prod via `aws ecs run-task`.
3. Verify dashboards (no 5xx from new repo writes; no fallback hits; new provisions read from billing row).

**PR 2 — cleanup (after a few days of clean dashboards):**
1. Remove `user_repo.set_provider_choice` / `clear_provider_choice`.
2. Remove `provider_choice` / `byo_provider` from the users-row Pydantic schemas (if present) and from the test fixtures.
3. DDB column removal: a separate one-off script `aws dynamodb update-item ... REMOVE provider_choice, byo_provider` per row, since DDB has no DROP COLUMN.

**No flag, no DB schema migration (DDB), additive on `billing_accounts`, removal on `users` deferred to PR 2.**

## Out of scope (cross-references)

- Switch-provider UI — own design.
- Clerk `user.deleted` → orphan-container cleanup — own ticket. (`user_3Cxc` container is the live evidence.)
- BYOK-in-org semantics (which member's key does the org container use?) — own design.
- Provision-gate UX (the silent-spinning bug from the same incident) — see `2026-05-03-provision-gate-ui-design.md`.
