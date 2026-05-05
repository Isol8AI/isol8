# Marketplace artifact upload + v1 flow fixes — design

**Status:** Approved (brainstorming complete, awaiting plan).
**Companion to:** `docs/superpowers/specs/2026-04-29-marketplace-design.md` (the v1 marketplace design).
**Affects PRs:** #445 (CDK), #448 (backend), #450 (CLI), #451 (admin UI), #452 (storefront). PR #449 (MCP service) is **deferred to v1.1** as a result of this design.

---

## 1. Background

The marketplace v1 stack (PRs #434 → #452) is implemented but has a set of dangling pieces that prevent it from functioning end-to-end at deploy time. They surfaced during a thorough code-review sweep on 2026-05-01:

- **The publish flow saves no actual artifact.** `marketplace_listings.create_listing` calls `create_draft(artifact_bytes=b"", manifest=…metadata-only…)`. There is no separate upload endpoint, and `pack_skillmd()` is defined but never called from any router. As coded, sellers create listings whose `s3://…/workspace.tar.gz` is empty — every install ships an empty tarball.
- **Stripe marketplace webhooks cannot validate signatures.** `STRIPE_CONNECT_WEBHOOK_SECRET` is read by the backend but never wired in CDK. Every webhook returns 400 "invalid signature"; no licenses are ever issued.
- **CLI device-code auth dead-ends.** `/cli/auth/start` returns `marketplace.isol8.co/cli/authorize?code=…` but no such page exists.
- **Stripe Connect onboarding redirects to 404.** CDK sends sellers to `marketplace.{env}.isol8.co/payouts/refresh` and `/payouts/return`; neither route exists.
- **`/buyer` page calls a non-existent `/my-purchases` endpoint** (already flagged in PR #452 body).
- **Marketplace storefront has no sign-in / sign-up pages.** The `/sell` page links to `/sign-in?redirect_url=…` which 404s.
- **Marketplace storefront never calls `/users/sync`.** Marketplace-only Clerk users have no `users` DDB row, breaking downstream lookups.
- **Path B (publish from existing OpenClaw agent) has no implementation.** The "publish from agent" path requires reading from EFS and a tier gate, neither of which exists.
- **Admin moderation UI shows metadata only.** Admins click Approve/Reject without ever seeing the SKILL.md content, file tree, openclaw summary, or any safety scan — i.e., they're rubber-stamping.
- **`description_md` is rendered as plain text** on listing cards and detail pages — markdown formatting never reaches the buyer.
- **MCP Fargate service introduces ~$45/mo idle cost** for an unproven feature; deferring it to v1.1 simplifies operations and reduces footprint.

The user requested a fix that lands all of the above. This document captures the decisions made during brainstorming and serves as the basis for the implementation plan.

## 2. Goals

- The marketplace v1 publish → moderate → buy → install flow works end-to-end on dev after these PRs merge.
- Both seller paths (outsider with SKILL.md, Isol8 paid user publishing an existing agent) are supported.
- Admins moderate with full content visibility and an automated safety-scan signal.
- No deploy-time configuration gaps remain (env vars, redirect pages, missing endpoints).
- The MCP server is **explicitly deferred** to v1.1; no Fargate service runs in v1.

## 3. Non-goals

- Replacing the Fargate-based MCP server with Lambda or another runtime. Deferring leaves the design unchanged for v1.1.
- Removing the v1 carve-outs (openclaw+mcp delivery, $20 price ceiling). Those stay.
- Multi-version listings beyond v1. `replace_artifact` keeps `version=1`; v2 publish is unchanged.
- Refactoring the existing Stripe SaaS subscription webhook (`/webhooks/stripe`). The new marketplace webhook (`/webhooks/stripe-marketplace`) gets its own secret.
- International (non-US) seller payouts. Stripe Connect remains US-only in v1.

## 4. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Both seller paths land in v1 (Path A: outsider SKILL.md, Path B: Isol8 user publishing agent) | User chose option (b) over partial scope. |
| D2 | Upload format: zip + server-side wrapper-strip normalization | Most accessible for non-technical sellers (right-click → Compress); server-side normalization makes buyer install layout deterministic regardless of seller packaging style. |
| D3 | Commit fixes to existing PR branches (no new fix branch) | Fix is in-scope for the PRs themselves; reviewers see context; stack stays at 7 PRs. |
| D4 | Critical + High + selected Medium items land together in this fix; Low tier deferred | "Critical-everything" prevents shipping a known-broken stack to dev. |
| D5 | Admin review tooling lands as part of this fix | Without it, moderation is rubber-stamping. ~3-4 hours added scope is worth it. |
| D6 | MCP Fargate service deferred to v1.1; PR #449 parked | Cost discipline ($45/mo idle for unproven feature); CDK scaffolding (DDB sessions table, etc.) stays in #445 for cheap reactivation later. |
| D7 | Path B reads agent definitions directly from EFS, not via the user's container gateway | EFS is authoritative; works whether the container is running or scaled-to-zero; avoids waking free-tier containers. |
| D8 | Path B is a snapshot at upload time, not a live link | Buyers get a stable artifact; seller can edit their agent freely after publishing without affecting buyers. |
| D9 | Validation runs at upload time, not submit time | Fail fast — sellers fix issues immediately, before they hit the moderation queue. |
| D10 | Path B requires Isol8 Starter / Pro / Enterprise tier | Free users have no provisioned container, so no agents on EFS to read. UI gates the option with a `seller-eligibility` precheck and an upgrade link. |

## 5. Architecture

### 5.1 Two upload paths, one shared S3 write

```
                           POST /listings
                            (metadata only,
                             empty workspace.tar.gz)
   ┌──────────────────┐
   │  /sell page      │   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   │                  │
   │  Step 1 metadata │   PATH A (skillmd)              PATH B (openclaw)
   │  Step 2 picks A  │   ─────────────────             ──────────────────
   │  or B based on   │   POST .../{id}/artifact        POST .../{id}/artifact-from-agent
   │  format          │   multipart: zip                JSON: { agent_id }
   └──────────────────┘
                                │                                │
                                ▼                                ▼
                       ┌────────────────┐              ┌────────────────────┐
                       │ unzip          │              │ read EFS           │
                       │ + strip 1-dir  │              │ /mnt/efs/users/    │
                       │   wrapper      │              │   {sid}/agents/    │
                       │ pack_skillmd() │              │   {agent_id}/      │
                       │  validates and │              │ catalog_service    │
                       │  builds tar    │              │  packs (snapshot)  │
                       └────────┬───────┘              └──────────┬─────────┘
                                │                                 │
                                └────────────┬────────────────────┘
                                             ▼
                            replace_artifact(listing_id, seller_id,
                                             artifact_bytes, manifest):
                              - Conditional update: seller match + status=draft
                              - S3 PutObject: workspace.tar.gz, manifest.json
                              - DDB Update: manifest_sha256, updated_at
```

### 5.2 End-to-end publish + moderate + buy

```
SELLER                         MARKETPLACE                ADMIN              BUYER
  │                                  │                       │                  │
  │ sign up via /sign-up             │                       │                  │
  │ (Clerk hosted)                   │                       │                  │
  │ first auth → UserSync component  │                       │                  │
  │ writes users DDB row             │                       │                  │
  │                                  │                       │                  │
  │ /sell:                           │                       │                  │
  │  GET /seller-eligibility ───────▶│                       │                  │
  │  ◀── {can_sell_skillmd: T,       │                       │                  │
  │       can_sell_openclaw: F|T}    │                       │                  │
  │  fill metadata                   │                       │                  │
  │  POST /listings ────────────────▶│                       │                  │
  │  ◀── listing_id ─────────────────│                       │                  │
  │  pick artifact source            │                       │                  │
  │  POST /artifact OR ─────────────▶│ unzip+normalize       │                  │
  │  POST /artifact-from-agent ─────▶│ pack / read EFS       │                  │
  │  ◀── manifest_sha256 ────────────│ replace_artifact      │                  │
  │  POST /listings/{id}/submit ────▶│ status: review        │                  │
  │                                  │                       │                  │
  │                                  │ appears in queue ────▶│                  │
  │                                  │                       │ click row →      │
  │                                  │                       │ detail page:     │
  │                                  │                       │ GET /preview     │
  │                                  │ ◀───────────────────  │                  │
  │                                  │   {file_tree,         │                  │
  │                                  │    skill_md_text,     │                  │
  │                                  │    openclaw_summary,  │                  │
  │                                  │    safety_flags}      │                  │
  │                                  │                       │ Approve / Reject │
  │                                  │ ◀───────────────────  │                  │
  │                                  │ status: published     │                  │
  │                                  │                       │                  │
  │ paid only:                       │                       │                  │
  │  POST /payouts/onboard          │                       │                  │
  │  Stripe Connect KYC              │                       │                  │
  │  → /payouts/return page          │                       │                  │
  │  → /dashboard                    │                       │                  │
  │                                  │ listing live ────────────────────────▶  │
  │                                  │                       │   browse → click │
  │                                  │                       │   Buy → Stripe   │
  │                                  │                       │   webhook →      │
  │                                  │                       │   license issued │
  │                                  │ /buyer page           │                  │
  │                                  │  ◀── /my-purchases ─────────────────────│
  │                                  │                       │   npx install    │
  │                                  │   /cli/auth/start ────│                  │
  │                                  │   (browser_url with   │                  │
  │                                  │   device_code)        │                  │
  │                                  │   /cli/authorize page │                  │
  │                                  │   /install/validate   │                  │
  │                                  │   ────────────────────▶│  ~/.claude/     │
  │                                  │                       │  skills/<slug>/  │
```

## 6. Components

### 6.1 Backend (PR #448)

#### New: `core/services/agent_export.py`

```python
def export_agent_from_efs(seller_id: str, agent_id: str) -> CatalogPackage
```

Reads `/mnt/efs/users/{seller_id}/agents/{agent_id}/` directly from EFS (no container interaction). Validates `agent_id` is a UUID, resolves the path, asserts the resolved path starts with `/mnt/efs/users/{seller_id}/agents/` (path-traversal defense). Skips junk dirs (`__pycache__`, `.cache`, `.git`). Tars the agent, builds a manifest with `format="openclaw"`. Returns a `CatalogPackage` matching `pack_skillmd`'s shape so `replace_artifact` doesn't branch.

#### New: `core/services/marketplace_safety.py`

```python
@dataclass
class SafetyFlag:
    pattern: str          # "curl-bash", "eval", "secret", etc.
    severity: Literal["high", "medium", "low"]
    file: str
    line: int | None
    snippet: str          # ~80 char excerpt

def scan(file_dict: dict[str, bytes], format: Literal["skillmd", "openclaw"]) -> list[SafetyFlag]
```

Built-in patterns (regex, no AST in v1):

| Pattern | Severity | Applies to |
|---|---|---|
| `curl\s+\S+\s*\|\s*(bash|sh|zsh)` (or wget) | high | both |
| `eval\(`, `Function\(`, `exec\(`, `subprocess\.` | high | both |
| `(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*["'][a-zA-Z0-9_-]{16,}` | high | both |
| `(?i)(aws|aws_)?(access|secret)[_-]?key` | high | both |
| `process\.env\.(\w+)` outside allowlist | medium | openclaw |
| Fetch/axios to non-allowlisted host | medium | both |
| `fs\.write` outside `workspace/` paths | medium | openclaw |
| Suspiciously large files (>1 MB binary) | low | both |

Returns a list of `SafetyFlag`. Detection is best-effort — admins still make the call, but high-severity flags pre-fill the rejection-notes textarea with `"flagged: <pattern> in <file>:<line>"`.

#### Modified: `core/services/skillmd_adapter.py`

```python
def unpack_zip_and_normalize(zip_bytes: bytes) -> dict[str, bytes]
```

Caps:
- Total compressed size ≤ 5 MB (request body)
- Total uncompressed size ≤ 10 MB
- File count ≤ 256
- No symlinks (`ZipInfo.external_attr` upper bits)
- No absolute paths, no `..`

Wrapper-strip rule: after extraction, if the result has exactly one top-level directory **and** that directory contains `SKILL.md` directly, strip the wrapper (i.e., return `{"SKILL.md": ..., "scripts/x.sh": ...}` instead of `{"my-skill/SKILL.md": ..., "my-skill/scripts/x.sh": ...}`). Multiple top-level entries → kept as-is.

#### Modified: `core/services/marketplace_service.py`

```python
async def replace_artifact(
    *, listing_id: str, seller_id: str, artifact_bytes: bytes, manifest: dict
) -> dict
```

Conditional: `seller_id == auth.user_id AND status == 'draft' AND version == 1`. Re-uploads to the same S3 prefix (`listings/{id}/v1/`), recomputes manifest SHA-256, updates the listing row's `manifest_sha256` + `updated_at`. The empty-string SHA constant `EMPTY_MANIFEST_SHA` is exported for use by `submit_for_review`'s precondition check.

#### Modified: `core/services/marketplace_service.submit_for_review`

Adds precondition: `manifest_sha256 != EMPTY_MANIFEST_SHA`. If empty, returns 409 with `"upload artifact before submitting"`. Prevents sellers from submitting an empty draft to the queue.

#### New endpoints in `routers/marketplace_listings.py`

| Method | Path | Auth | Body / Query | Returns |
|---|---|---|---|---|
| POST | `/listings/{id}/artifact` | Clerk | multipart `file=zip` | `ArtifactUploadResponse` |
| POST | `/listings/{id}/artifact-from-agent` | Clerk | JSON `{agent_id}` | `ArtifactUploadResponse` |
| GET | `/my-agents` | Clerk | — | `MyAgentsResponse` (list of `{agent_id, name, updated_at}` from EFS) |
| GET | `/seller-eligibility` | Clerk | — | `SellerEligibilityResponse` `{tier, can_sell_skillmd, can_sell_openclaw, reason?}` |

All write endpoints conditional on listing seller match + `status="draft"`. `/my-agents` reads EFS via `core.containers.workspace`; returns empty list if seller has no `agents/` dir. `/seller-eligibility` calls `billing_repo.get_by_owner_id`; `can_sell_openclaw = tier in {"starter", "pro", "enterprise"}`.

#### New endpoint in `routers/marketplace_purchases.py`

| Method | Path | Auth | Returns |
|---|---|---|---|
| GET | `/my-purchases` | Clerk | `MyPurchasesResponse` `{items: [{purchase_id, listing_id, listing_slug, license_key, price_paid_cents, status, created_at}]}` |

Queries `marketplace-purchases` by `buyer_id == auth.user_id`. Joins listing slug via single-item DDB read per row (small N — sellers don't buy thousands of items). Cap result count at 100.

#### New endpoint in `routers/marketplace_admin.py`

| Method | Path | Auth | Returns |
|---|---|---|---|
| GET | `/admin/marketplace/listings/{id}/preview` | platform admin | `ListingPreviewResponse` |

```python
class ListingPreviewResponse(BaseModel):
    listing_id: str
    format: Literal["skillmd", "openclaw"]
    manifest: dict
    file_tree: list[FileTreeEntry]    # path, size_bytes
    skill_md_text: str | None         # populated when format="skillmd"
    openclaw_summary: dict | None     # populated when format="openclaw"
    safety_flags: list[SafetyFlag]
```

Implementation: streams `workspace.tar.gz` from S3, extracts in-memory, runs `marketplace_safety.scan(...)`, returns the response. Cap: `tarball_size <= 10 MB`. Audit-decorated via the existing `@audit_admin_action` decorator.

### 6.2 Infra (PR #445)

#### Modified: `apps/infra/lib/stacks/auth-stack.ts`

Add a new Secrets Manager entry: `isol8-{env}-stripe-connect-webhook-secret`. Value populated manually post-deploy (mirrors the existing `STRIPE_WEBHOOK_SECRET` pattern). Pass the secret name (string, not `ISecret`) to ServiceStack via stack props to avoid cross-stack KMS auto-grant cycles.

#### Modified: `apps/infra/lib/stacks/service-stack.ts`

Add to the backend service's `secrets:` block:

```ts
STRIPE_CONNECT_WEBHOOK_SECRET: ecs.Secret.fromSecretsManager(
  secretsmanager.Secret.fromSecretNameV2(
    this, "ConnectWebhookSecret", props.connectWebhookSecretName
  )
),
```

#### Modified: `docs/superpowers/runbooks/marketplace-plan-1-provisioning.md`

Add post-deploy step: register the new Connect webhook endpoint in Stripe dashboard (`https://api-{env}.isol8.co/api/v1/marketplace/webhooks/stripe-marketplace`), copy the signing secret from the Stripe UI, paste into the new Secrets Manager entry. Mirrors the existing Stripe SaaS webhook step.

### 6.3 Storefront (PR #452)

#### New pages

```
apps/marketplace/src/app/sign-in/[[...rest]]/page.tsx       — Clerk hosted <SignIn/>
apps/marketplace/src/app/sign-up/[[...rest]]/page.tsx       — Clerk hosted <SignUp/>
apps/marketplace/src/app/cli/authorize/page.tsx             — paste device_code, hit
                                                              POST /cli/auth/authorize,
                                                              show success copy
apps/marketplace/src/app/payouts/refresh/page.tsx           — calls /payouts/onboard
                                                              again, redirects to fresh
                                                              Stripe URL
apps/marketplace/src/app/payouts/return/page.tsx            — polls /payouts/dashboard
                                                              until status=ready, then
                                                              redirects to /dashboard
```

#### New components

```
src/components/UserSync.tsx          — invisible client component:
                                       useEffect(() => { if (signedIn) call /users/sync })
                                       runs once per session via sessionStorage flag
src/components/Listing/MarkdownDescription.tsx
                                     — react-markdown + rehype-sanitize, allowlist:
                                       headings, lists, code, links (target=_blank),
                                       inline emphasis. No raw HTML.
src/components/Sell/ZipUploader.tsx  — drag-drop zone, client-side .zip MIME guard,
                                       shows upload progress, surfaces server error,
                                       posts multipart to /listings/{id}/artifact
src/components/Sell/AgentPicker.tsx  — fetches /my-agents, renders list, posts
                                       /listings/{id}/artifact-from-agent on selection
```

#### Modified files

```
src/app/layout.tsx                    — mount <UserSync /> (no UI)
src/app/sell/page.tsx                 — calls /seller-eligibility on mount;
                                        2-step flow: metadata → artifact (zip OR agent);
                                        format dropdown gates "Agent" option;
                                        uses ZipUploader and AgentPicker
src/app/listing/[slug]/page.tsx       — replaces plain text with <MarkdownDescription>;
                                        adds installation help block for paid listings
                                        (npx command + post-purchase flow)
src/components/Listing/ListingCard.tsx— renders description with stripped markdown
                                        (first paragraph, plain text — no full render
                                        on the card to avoid layout shift)
src/app/buyer/page.tsx                — no change (endpoint exists now via C4)
src/app/mcp/setup/page.tsx            — replaces existing copy with "Live MCP server
                                        coming in v1.1. Use the npx installer for now."
                                        Keeps the page so /mcp/setup links don't 404.
package.json                          — adds: react-markdown, rehype-sanitize.
                                        (pnpm; not npm — see project memory.)
```

### 6.4 Admin UI (PR #451)

#### New page

```
apps/frontend/src/app/admin/marketplace/listings/[id]/page.tsx
```

RSC page. Adds `getListingPreview` to `apps/frontend/src/app/admin/_actions/marketplace.ts` (Next.js Server Action) which calls the backend `GET /admin/marketplace/listings/{id}/preview` endpoint and returns the project's standard `ActionResult` envelope. The page renders:

1. **Safety flags banner** at the top — red if any `severity="high"`, amber if `medium` only, hidden if none.
2. **Metadata card** — slug, name, seller_id, price_cents, tags, created_at.
3. **File tree** — each file size + click-to-expand for text files.
4. **Content viewer:**
   - `format="skillmd"` → markdown render of SKILL.md + syntax-highlighted view of helper scripts
   - `format="openclaw"` → summary card (tools count, providers, cron count, channels count, sub-agent count) + collapsible raw `openclaw.json`
5. **Approve / Reject** buttons (existing `ModerationActions` component).

Reject's free-form notes textarea is **pre-filled** with `"flagged: " + safety_flags.high.map(...)` when there are high-severity findings, so admins don't have to retype them.

#### Modified file

```
apps/frontend/src/app/admin/marketplace/listings/page.tsx
```

Each row links to `/admin/marketplace/listings/{listing_id}` (the new detail page). Approve/Reject buttons stay on the queue page for the rubber-stamp-when-clean case.

### 6.5 CLI (PR #450)

No code changes. Operational notes added to `packages/marketplace-cli/README.md`:

- **Operational prereq:** `NPM_TOKEN` must be in GitHub Actions secrets before the first `marketplace-cli-v*` git tag.
- Reference the new `/cli/authorize` page now reachable on the storefront.

#### Branch retarget (operational, no code)

PR #450's base changes from `feat/marketplace-plan-3-mcp-server` to `feat/marketplace-plan-2-backend`:

```bash
gh pr edit 450 --base feat/marketplace-plan-2-backend
```

This is the "park PR #449" step. PR #449 stays open as a draft (or labeled `v1.1-deferred`) for future reactivation.

## 7. Data flow — error paths

| Error | Response | Where |
|---|---|---|
| Zip > 10 MB unpacked | 413 | `unpack_zip_and_normalize` |
| Zip contains absolute path / `..` / symlink | 400 with explicit reason | `unpack_zip_and_normalize` |
| `SKILL.md` missing in zip | 400 | `pack_skillmd` (existing) |
| Listing not in `draft` state | 409 | `replace_artifact` |
| Caller is not the seller | 403 | `replace_artifact` |
| Path B: caller is free tier | 403 with upgrade link in body | `seller-eligibility` precheck + `export_agent_from_efs` defensive check |
| Path B: `agent_id` traverses outside seller's dir | 400; emit `marketplace.path_traversal_attempt` metric | `export_agent_from_efs` |
| Path B: agent dir doesn't exist on EFS | 404 | `export_agent_from_efs` |
| `/my-agents` when seller has no `agents/` dir | 200 `{items: []}` | not an error — UI shows empty state |
| Submit-for-review with empty manifest_sha256 | 409 `"upload artifact before submitting"` | `submit_for_review` |
| Stripe webhook with bad signature | 400 | `marketplace_purchases.stripe_webhook` (existing — works once secret is wired) |
| `/users/sync` race on first auth | idempotent — already handled | existing `users.py` |

## 8. Testing

### 8.1 Backend unit tests

| File | New tests |
|---|---|
| `tests/unit/services/test_agent_export.py` (new) | happy-path read, path-traversal rejection, missing-dir 404, snapshot determinism (two calls → identical SHA), junk-skip filter, seller_id sanitization |
| `tests/unit/services/test_skillmd_adapter.py` (additions) | zip with no wrapper kept flat, zip with wrapper stripped, multiple top-level dirs kept, `..` rejected, absolute path rejected, symlink rejected, oversized zip rejected |
| `tests/unit/services/test_marketplace_safety.py` (new) | each pattern fires, non-matching content produces no flags, severity ordering |
| `tests/unit/routers/test_marketplace_listings.py` (additions) | `POST /artifact` happy path, on already-published listing 409, from non-seller 403, `POST /artifact-from-agent` happy path, on free tier 403, `GET /my-agents` lists from EFS, `GET /seller-eligibility` per tier, free user no billing → `can_sell_openclaw=false` |
| `tests/unit/routers/test_marketplace_purchases.py` (additions) | `GET /my-purchases` returns items, empty list with no purchases, no cross-tenant leak |
| `tests/unit/routers/test_marketplace_admin.py` (additions) | `GET /preview` returns content for skillmd, returns content for openclaw, surfaces safety flags, audit row written |

### 8.2 Backend integration test

Extend `tests/integration/test_marketplace_flow.py` with `test_full_publish_flow`:

1. Create draft via `POST /listings`.
2. Upload zip via `POST /listings/{id}/artifact`.
3. Verify S3 object exists with non-empty body and correct manifest_sha256.
4. Submit for review.
5. Admin GETs `/preview` and inspects file tree + safety flags.
6. Admin approves.
7. Verify search-indexer Lambda picked it up (DDB → search shard).
8. Buyer purchases (Stripe webhook simulated).
9. CLI install validates, downloads, extracts; SKILL.md ends up at the canonical path (no wrapper dir).

LocalStack-gated.

### 8.3 Frontend tests

| File | Coverage |
|---|---|
| `__tests__/UserSync.test.tsx` | calls `/users/sync` once on mount when signed in; no call when signed out; sessionStorage flag set after success |
| `__tests__/ZipUploader.test.tsx` | accepts .zip MIME, rejects non-zip, shows progress UI, surfaces server error message |
| `__tests__/AgentPicker.test.tsx` | shows empty state, lists agents, calls `/artifact-from-agent` on selection |
| `__tests__/MarkdownDescription.test.tsx` | renders headings/lists/code; sanitizes `<script>`; honors target=_blank on links |

### 8.4 E2E (Playwright)

One new journey test gated behind `E2E_MARKETPLACE=1`:

1. Sign up new Clerk user via `/sign-up`.
2. Verify `/users/sync` was called (DDB row exists).
3. `/sell` → fill metadata → upload a tiny zip.
4. Submit for review.
5. Sign in as admin → load detail page → verify file tree + safety flags render → approve.
6. Sign back as buyer (different Clerk session) → buy → Stripe webhook simulated → `/buyer` shows the purchase.
7. CLI run against dev backend → SKILL.md lands at the canonical path.

## 9. Rollout

```
PHASE 1 — Land code on existing branches (1-2 weeks)
   Backend commits → PR #448 (rebase, push)
   Infra commits → PR #445 (rebase, push)
   Storefront commits → PR #452 (rebase, push)
   Admin UI commit → PR #451 (rebase, push)
   CLI README + base retarget → PR #450
   PR #449 → leave open as draft, labeled `v1.1-deferred`

PHASE 2 — Operational prereqs (1 day, no code)
   - Add NPM_TOKEN to GitHub Actions secrets
   - Create Vercel project pointed at apps/marketplace
       env: NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY, CLERK_SECRET_KEY,
            NEXT_PUBLIC_API_URL=https://api-dev.isol8.co
   - Point marketplace.dev.isol8.co DNS at Vercel
   - Register the Connect webhook endpoint in Stripe dashboard,
     paste signing secret into Secrets Manager

PHASE 3 — Stack merges in order to dev
   #434 → main          (design doc)
   #445 → main          (CDK foundation, includes Connect webhook secret)
   #448 → main          (backend, includes upload + my-purchases + admin preview)
   #450 → main          (CLI, retargeted to plan-2)
   #451 + #452 → main   (admin UI + storefront, parallel)

   Backend deploys to dev via GitHub Actions. Verify:
   - `aws secretsmanager get-secret-value
       --secret-id isol8-dev-stripe-connect-webhook-secret`
     returns the value pasted in Phase 2.
   - `curl https://api-dev.isol8.co/api/v1/marketplace/listings`
     returns `{"items": [], "count": 0}`.

PHASE 4 — Smoke test on dev (1 hour)
   - Sign up new Clerk user via marketplace.dev.isol8.co/sign-up
   - Publish one free SKILL.md skill end-to-end
   - Approve via admin-dev.isol8.co/admin/marketplace/listings/{id}
   - Run `npx @isol8/marketplace install <slug>` → verify file path
   - Sign up second user → buy a paid listing → verify license issued,
     /buyer page shows the purchase
   - Tag marketplace-cli-v0.1.0 → CI publishes to npm

PHASE 5 — Path B test (optional dogfood)
   Ask one Pro/Enterprise Isol8 user to publish their agent via Path B
   before public launch.

PHASE 6 — Production
   Repeat Phase 2 for prod (NPM_TOKEN already global; new Vercel env;
   prod Stripe Connect webhook → Secrets Manager).
   Promote main → prod via existing CI/CD.
```

## 10. Risks

| Risk | Mitigation |
|---|---|
| Zip-bomb attack via malicious upload | 10 MB unpacked cap + file count cap (256) + no symlinks. Tested. |
| Path traversal via `agent_id` | UUID validation + resolved path must `startswith` `/mnt/efs/users/{seller_id}/agents/`. Metric on attempts. |
| Seller submits empty draft | `replace_artifact` precondition for `submit_for_review`; explicit 409 message. |
| Connect webhook secret rotated | Existing rotation runbook applies. |
| `/seller-eligibility` cached after upgrade | Form calls it on each `/sell` mount, no client cache. |
| `/my-agents` stale (agent deleted post-publish) | Path B is snapshot at upload, so post-publish deletion doesn't break the buyer. EFS read failure on `/my-agents` returns empty list (no 500). |
| Safety scan misses a malicious pattern | Regex-only in v1, intentionally best-effort. Admin still inspects content; flags pre-fill rejection notes when triggered. AST-based deep scan deferred to v1.1. |
| MCP feature deferred — competitive thesis weakens | Acceptable given $45/mo idle cost vs unproven demand. Live MCP demo can be re-added in v1.1 when there's evidence buyers want it. |

## 11. Open questions

None. All decisions captured in §4.

## 12. Operational checklist (carried into the plan)

- [ ] `NPM_TOKEN` added to GitHub Actions secrets (before tagging `marketplace-cli-v0.1.0`)
- [ ] Vercel project for `apps/marketplace` created
- [ ] `marketplace.dev.isol8.co` DNS pointed at Vercel
- [ ] `marketplace.isol8.co` DNS pointed at Vercel (prod)
- [ ] Connect webhook endpoint registered in Stripe dashboard (dev + prod)
- [ ] Connect webhook signing secret pasted into Secrets Manager (dev + prod)
- [ ] PR #449 labeled `v1.1-deferred` and unlinked from the merge train
- [ ] PR #450 base retargeted to `feat/marketplace-plan-2-backend`
