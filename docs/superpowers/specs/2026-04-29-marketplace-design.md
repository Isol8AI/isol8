# Design: marketplace.isol8.co

**Date:** 2026-04-29
**Status:** APPROVED (user accepted 2026-04-29 after revision 3; agents-led reframing + plan-eng-review fixes applied 2026-04-29)
**Mode:** Startup (produced via /office-hours diagnostic)
**Branch:** main
**Author:** prabuddhagupta

## Summary

**The marketplace for AI agents.** A public marketplace at `marketplace.isol8.co` where complete AI agents — full workers with identity, workflows, memory, and bundled skills — can be browsed, published, and bought or downloaded for free. Built as a layer on top of the existing Isol8 catalog system.

Individual SKILL.md files are also a supported format for sellers who want to publish atomic skills rather than full agents. Skills sit one level below agents in the brand hierarchy: discoverable, listable, but not the headline. The home page and discovery default to agents.

Sellers: Isol8 paying users publish the agents they've already built on the platform; non-Isol8 sellers publish either as agents or as standalone SKILL.md files. Buyers consume purchases via two paths chosen per-listing by the seller: a CLI installer (`npx @isol8/marketplace install <slug>`) for client-side install into Claude Code, Cursor, OpenClaw, and Copilot CLI, or via a hosted MCP server that exposes purchased agents/skills as MCP tools to MCP-supporting clients (Claude Desktop, Cursor with MCP, Codex CLI).

The strategic thesis is **manufactured sellers**: existing Isol8 paying users currently use their agents privately; giving them a path to publish (free or paid) creates a seller pool the platform did not have before. The competitive thesis is **install simplicity AND agents-first positioning**: every existing skills marketplace (Agensi, Skly, SkillsMP) sells skills as commodities and is structurally stuck at $5 price points. Selling complete agents at $20-100 is a different market with no dominant player.

## Positioning

The brand is "the marketplace for AI agents." Agents are products; skills are commodities. Commodities sit at $5 because there is no scarcity. Agents — bundles of identity, workflows, memory, and skills targeted at a specific job — can sell at $20-100 because each one is genuinely different. Agensi, Skly, SkillsMP, LobeHub, agentskill.sh all sell skills. None has a dominant agents marketplace. That is the wedge.

Operational implications:

- **Home page** leads with featured agents. Skills are a tab, not the front door.
- **Discovery default tab** is "Agents." A "Skills" tab is one click away for buyers who want individual SKILL.md files.
- **Pricing guidance** in the publishing UX nudges agent sellers toward $20-100 ranges and skill sellers toward $5-20.
- **Marketing copy and case studies** lead with agents. Skill listings appear in the catalog but not in launch materials.
- **Architecture is unchanged.** The schema's `format` field still holds `"openclaw"` (agent) or `"skillmd"` (skill). Only the framing, copy, and discovery defaults change.

## Problem Statement

Isol8 users build per-user OpenClaw agents on the platform. They cannot today share what they built with anyone outside their own container; they cannot earn money from it; they cannot discover what other users have built. Outside of Isol8, the broader skill-author community (people writing SKILL.md files for Claude Code, Cursor, OpenClaw, Copilot CLI, etc.) has the same gaps: most skills live as private tarballs on personal GitHub repos with no monetization path and no curated discovery.

Existing marketplaces in this category (Agensi as the closest analogue, plus Skly, SkillsMP, LobeHub) have solved cataloging but have notable gaps: install friction (manual unzip into client-specific directories), no IP protection (plaintext SKILL.md downloadable for $5), no try-before-buy, and no vertical curation. None has clearly proven that creators are making meaningful money on their platform.

Isol8 already has the catalog plumbing in production: `catalog_service.py` (504 LOC), S3-backed agent packaging with `manifest.json` + `workspace.tar.gz` + `openclaw-slice.json`, an admin publishing flow, a one-click deploy flow, and an admin UI for catalog management. The gap between today's admin-only catalog and a public marketplace is real but smaller than starting from scratch.

## Demand Evidence

What we have:

- **Adjacent demand from Isol8 users (Q1 push 2):** users have asked for sharing/templates ("can I share my agent with my team", "is there a way to import someone else's setup"). Real signal, but not a paid-marketplace signal.
- **Manufactured-seller thesis (Q3):** Isol8 paying users (Free, Starter $40, Pro $75, Enterprise $165) are the candidate seller pool. They don't try to monetize today because no path exists. Build the path, measure activation.

What we **do not** have:

- No named seller who has said "I would pay to publish" or "I would pay $X for someone else's agent."
- No evidence that any existing Agensi/Skly creator earns meaningful money on those platforms (validation gap of the entire category).
- No status-quo evidence that the imagined sellers are currently trying to monetize via GitHub or Twitter or other means.

This is a *thesis-driven* product, not a demand-pull product. Honest framing.

## Status Quo

### For agent builders

There is no marketplace for complete AI agents. An Isol8 user who builds an interesting agent today has these options:

- Keep it private (default, what almost everyone does).
- Manually export the workspace tarball and share with friends (no platform support).
- Strip it down to a SKILL.md file and post on GitHub (loses identity, workflows, multi-step memory — the things that make it an agent).

The "complete worker that does this specific job" category has no marketplace. Relevance AI Marketplace and ServiceNow Store sell agents but only inside their walled platforms and only for enterprise. There is no Etsy/Gumroad-style independent agent marketplace.

### For skill authors

A developer outside Isol8 who builds a Claude Code or Cursor skill has these options:

- Post on GitHub, hope for stars.
- List on Agensi/Skly with manual ZIP-based install, charge $5-12.
- Tweet about it.
- Submit to one of the 425k-skill aggregators (LobeHub, SkillsMP) where it disappears.

The skills market is crowded. The agents market is empty. The cost of all current workarounds: no monetization, weak discovery, install friction for buyers, no quality signal.

## Target User & Narrowest Wedge

### Primary user (v1 sellers): Isol8 agent builders

A Pro-tier Isol8 user who has built a complete agent in their container that does something specific and valuable (sales sequence generator, code review worker, customer-support triage agent). They use it daily for themselves. Once a "publish to marketplace" toggle exists, a small percentage will publish, some will charge $20-100 for a complete agent, and the platform learns what's monetizable. **This is the headline persona.**

### Secondary user (v1 sellers): non-Isol8 agent and SKILL.md authors

Two flavors:

- A non-Isol8 developer who has built an agent-shaped artifact for Claude Code, Cursor, or Copilot CLI (multi-step prompt + tool definitions + workflow), wrapped as a SKILL.md package. Charges $10-30.
- A developer with a single high-quality SKILL.md file (Postgres migration helper, security-audit skill) who wants to monetize an atomic skill at $5-15. Listed in the Skills tab; not on the home page.

Both flavors use the SKILL.md format and reach buyers via CLI install or MCP. The agent-shaped flavor is brand-positioned the same as Isol8 agents; the atomic-skill flavor is honestly framed as a skill, not an agent.

### Buyers

Anyone using a skill-aware AI client (Claude Code, Cursor, OpenClaw, Copilot CLI) plus Isol8 users who want to deploy purchased agents directly into their container. v1 supports four CLI installer targets natively; everything else falls back to a printed manual-install instruction. Buys a free or paid agent (or skill), runs `npx @isol8/marketplace install <slug>` or connects the marketplace MCP server, and the agent/skill appears in their toolchain.

### Narrowest wedge (recorded, not chosen)

A free-only catalog of curated agents/skills, browseable at `marketplace.isol8.co`, with one-command install via the CLI. No payments, no MCP server, no creator dashboard. ~3 weeks. Validates two things: (a) does anyone visit, and (b) does the CLI installer feel as good as we think.

The wedge is **not** what we're shipping in v1. The user has explicitly committed to free + paid + non-Isol8 + dual distribution from day 1, accepting the 18-24 week effort. The wedge is recorded here for transparency and as a fallback option if any v1 milestone slips materially.

## Constraints

- Must run on existing Isol8 infrastructure (AWS account, monorepo, existing Stripe/Clerk/DynamoDB).
- Must reuse the existing catalog system rather than rebuild.
- Domain is `marketplace.isol8.co` (Vercel, like the existing frontend and goosetown).
- Must ship with both Isol8-format publishing (OpenClaw) and SKILL.md publishing path.
- v1 is plaintext distribution (no encrypted bundles). Hosted execution lives in the MCP server but does not yet provide IP protection (skills are still readable by the server-side runtime; v2 will introduce the actual protection layer).

## Premises (locked with user)

- **P1: Free + paid coexist from v1.** Sellers choose per-listing whether to publish free or set a price. Listings can move between free and paid. Stripe Connect Express handles creator payouts from day 1.
- **P2: Non-Isol8 sellers AND buyers from v1.** A developer with no OpenClaw container can sign up, publish a SKILL.md skill, set a price, get paid. A buyer with no OpenClaw container can browse, buy, and install via CLI or MCP.
- **P3: Plaintext distribution v1.** Both Isol8 agents and SKILL.md skills download as plaintext tarballs. Buyers can technically republish what they bought. Price ceiling for v1 effectively $5-20 per skill. Encrypted bundles are explicitly Phase 2.
- **P4: Both CLI installer AND hosted MCP server v1.** Sellers choose per-listing via a `delivery_method` field (`cli`, `mcp`, or `both`). CLI installer for plaintext skills (most listings). Hosted MCP server for sellers who want sandboxed delivery as the foundation of the eventual Phase 2 IP-protection story.

## Approaches Considered

### Approach A: Monorepo extension, OpenClaw-format primary, SKILL.md adapter (chosen)

Extend the existing Isol8 monorepo. New `apps/marketplace` Next.js app at `marketplace.isol8.co`. Backend grows new routers and services that build on `catalog_service.py`. Native publish format remains the OpenClaw `workspace.tar.gz + manifest.json + openclaw-slice.json` triple. SKILL.md sellers go through an adapter (`skillmd_adapter.py`) that wraps a SKILL.md plus support files into the same triple structure.

Effort: **~18-24 weeks human / ~80-120 hours CC+gstack** (revised after adversarial review; the original 10-12 / 35 estimate was off by 2-3x because it under-counted the MCP server and the cross-platform CLI).
Reuses ~70% of existing catalog/auth/billing code.
Risk: marketplace tightly coupled to Isol8; future spin-out painful. SKILL.md publishing path feels less polished than OpenClaw because the OpenClaw flow is privileged.

### Approach B: Standalone federated product

Separate codebase, separate database, separate FastAPI app. Calls Isol8 only via public APIs. Format-neutral from day 1.

Effort: ~26-32 weeks / ~140 hours CC.
Reuses ~30%.
Pro: marketplace can be its own brand later. Con: duplicated infrastructure, slowest v1 of the three.

### Approach C: Format-neutral inside the monorepo

Stay in the monorepo but refactor the catalog so SKILL.md is canonical and OpenClaw is one of multiple render targets.

Effort: ~22-28 weeks / ~110 hours CC.
Reuses ~50% of catalog plumbing.
Pro: better long-term positioning vs Agensi. Con: forces a refactor of an in-flight catalog system; higher regression risk.

## Recommended Approach: A

Approach A captures the catalog-reuse advantage (~6-8 weeks of head start vs B and C), satisfies the P2 "non-Isol8 from day 1" capability via the SKILL.md adapter without paying the refactor tax of C, and respects the user's stated v1 timeline preference. The decision to keep OpenClaw as the privileged native format is reversible: if the marketplace takes off and the majority of sellers turn out to be non-Isol8, a Phase 2 refactor toward Approach C's format-neutrality remains an option.

## Architecture (high-level)

```
                ┌──────────────────────────────────────────────┐
                │           marketplace.isol8.co                │
                │           (Vercel, Next.js 16)                │
                │                                                │
                │  /                  home (Featured agents)     │
                │  /agents            agents browse (default tab)│
                │  /skills            skills browse (secondary)  │
                │  /listing/:slug     detail page + buy/install  │
                │  /sell              creator publishing UI       │
                │  /dashboard         creator earnings + listings │
                │  /buyer             buyer purchase history      │
                │  /mcp/setup         MCP integration help page   │
                └─────────────┬────────────────────────────────┘
                              │ REST + WS (existing api.isol8.co)
                              ▼
                ┌──────────────────────────────────────────────┐
                │       FastAPI backend (existing ECS)          │
                │                                                │
                │  routers/marketplace_listings.py  (NEW)       │
                │  routers/marketplace_purchases.py (NEW)       │
                │  routers/marketplace_payouts.py   (NEW)       │
                │  routers/marketplace_install.py   (NEW)       │
                │  routers/marketplace_admin.py     (NEW)       │
                │                                                │
                │  services/                                     │
                │   marketplace_service.py   (NEW, wraps         │
                │     catalog_service.py)                        │
                │   payout_service.py        (NEW)              │
                │   skillmd_adapter.py       (NEW)              │
                │   license_service.py       (NEW)              │
                │   marketplace_search.py    (NEW)              │
                │   takedown_service.py      (NEW)              │
                └─────┬─────────────────┬───────────────┬──────┘
                      │                 │                │
                      ▼                 ▼                ▼
              ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
              │  DynamoDB     │  │  Stripe      │  │   S3          │
              │  (8 new       │  │  Connect     │  │  isol8-{env}- │
              │   tables —    │  │  Express     │  │  marketplace- │
              │   see Data    │  │              │  │  artifacts    │
              │   Model)      │  └──────────────┘  └──────────────┘
              └──────────────┘
                                                            │
                              ┌─────────────────────────────┘
                              ▼
                ┌──────────────────────────────────────────────┐
                │       MCP server (NEW, Fargate)                │
                │                                                │
                │  apps/marketplace-mcp (NEW Fargate service)   │
                │   ── per-listing routes: /:listing-id/sse     │
                │   ── auth: Bearer license-key in HTTP header   │
                │   ── execution: warm-pool of two runtimes      │
                │      (openclaw skill runner, skillmd runner)   │
                └──────────────────────────────────────────────┘
                              │
                              ▼
                ┌──────────────────────────────────────────────┐
                │       Distribution: end-buyer surfaces         │
                │                                                │
                │  @isol8/marketplace-cli  (npm, public)        │
                │   ── npx @isol8/marketplace install <slug>     │
                │   ── auto-detects client (claude-code, cursor, │
                │      openclaw, copilot, generic-fallback)      │
                │                                                │
                │  marketplace.isol8.co/mcp/:listing-id (SSE)    │
                │   ── per-listing MCP endpoint, license-gated   │
                │                                                │
                │  POST /api/v1/marketplace/listings/:slug/deploy│
                │   ── Isol8 users only, deploys directly into   │
                │      their existing OpenClaw EFS workspace      │
                └──────────────────────────────────────────────┘
```

## Component boundaries

- **`marketplace_service.py`** wraps `catalog_service.py`. Catalog handles packaging (already works); marketplace_service adds listing metadata (price, seller, status, delivery_method), purchase records, the publishing UX state machine, and the listing version-update flow.
- **`skillmd_adapter.py`** converts a SKILL.md file plus optional support files into the same `manifest.json + workspace.tar.gz + openclaw-slice.json` triple the existing catalog uses. The slice for SKILL.md skills is empty. Path-rewriting rules ensure the SKILL.md works after install (see SKILL.md adapter rules below).
- **`payout_service.py`** owns Stripe Connect Express onboarding, payout balance accrual, and tax-form delivery (which Stripe Connect Express handles natively for US sellers, including 1099-K generation and form delivery).
- **`license_service.py`** generates and validates license keys (full lifecycle below).
- **`marketplace_search.py`** owns search/filter logic. v1 uses DynamoDB GSIs on tags, format, price-bucket, and seller; full-text search runs against a denormalized list cached in CloudFront for 60s. v2 swaps to OpenSearch when listings exceed ~5000 or query QPS exceeds DynamoDB-friendly limits.
- **`takedown_service.py`** owns DMCA / content-policy takedowns: revokes licenses, soft-deletes the listing, records audit, refunds within a configurable window.
- **`apps/marketplace-mcp`** is a separate Fargate service (not in the FastAPI process) for blast-radius isolation and independent scaling. Full MCP server spec below.
- **`apps/marketplace-search-indexer`** is a separate AWS Lambda function fronted by a DynamoDB Streams trigger on the `marketplace-listings` table. On every insert/update, it refreshes the corresponding row(s) in `marketplace-search-index`. Lambda runtime is Python 3.13 to share code with the backend.

## Data Model

### New DynamoDB tables (`isol8-{env}-marketplace-*`)

```
isol8-{env}-marketplace-listings
  PK: listing_id (uuid)
  SK: version (int, latest version row also has alias SK="LATEST")
  GSI1: slug-version-index (PK: slug, SK: version)
  GSI2: seller_id-created_at-index
  GSI3: status-published_at-index   (browse "newest published")
  GSI4: tag-published_at-index      (faceted browse, sparse, one row per tag)
  Attributes: slug (lowercase), name, description_md, seller_id (Clerk user id),
              format ("openclaw" | "skillmd"),
              price_cents (0 = free, range 0..2000 for v1),
              delivery_method ("cli" | "mcp" | "both"),
              status ("draft" | "review" | "published" | "retired" | "taken_down"),
              s3_prefix, manifest_json, manifest_sha256, screenshots[],
              tags[] (max 5), category, suggested_clients[],
              artifact_format_version ("v1" — Phase 2 introduces "v2-encrypted"),
              entitlement_policy ("perpetual"; v1 ships only this value;
                "major-only" deferred to Phase 2),
              created_at, updated_at, published_at

isol8-{env}-marketplace-purchases
  PK: buyer_id (Clerk user id; guest checkout uses Clerk Anonymous Users
                with REQUIRED email at checkout — needed for license-key
                recovery, refunds, and takedown notifications. Anonymous
                buyers without a verified email cannot complete a paid
                purchase. Free downloads do NOT require email.)
  SK: purchase_id
  GSI1: listing_id-created_at-index   (per-listing buyer list, used for
                                       takedown-driven license revocation)
  GSI2: license_key-index             (sparse, license-key lookup)
  Attributes: listing_id, listing_version_at_purchase,
              entitlement_version_floor (int — what versions buyer can install),
              price_paid_cents, stripe_payment_intent_id,
              license_key (32-char base32 random; see License Key Lifecycle),
              license_key_revoked (bool, default false),
              license_key_revoked_reason, license_key_revoked_at,
              status ("paid" | "refunded" | "revoked"),
              install_count, last_install_at,
              created_at

isol8-{env}-marketplace-payout-accounts
  PK: seller_id
  Attributes: stripe_connect_account_id (null until onboarding completes),
              onboarding_status ("none" | "started" | "completed"),
              payout_schedule, balance_held_cents (escrow until onboarding),
              lifetime_earned_cents, tax_form_status,
              created_at, last_balance_update_at

isol8-{env}-marketplace-listing-versions   (immutable history; canonical
                                              source for download artifacts —
                                              the listings table mirrors only
                                              the latest version's s3_prefix)
  PK: listing_id
  SK: version (int)
  Attributes: s3_prefix, manifest_json, manifest_sha256, published_at,
              published_by, changelog_md, breaking_change (bool, defaults
              false — v1 ignores this flag, present for forward compat)

isol8-{env}-marketplace-takedowns
  PK: listing_id
  SK: takedown_id
  Attributes: reason ("dmca" | "policy" | "fraud" | "seller-request"),
              filed_by, filed_at, decision, decided_by, decided_at,
              affected_purchases (count), refunded_purchases (count),
              audit_trail_ref (admin-actions table id)

isol8-{env}-marketplace-mcp-sessions   (TTL = 24h for cleanup)
  PK: session_id
  Attributes: license_key, listing_id, listing_version, runtime_pool_id,
              started_at, last_activity_at, ttl

isol8-{env}-marketplace-search-index   (denormalized for cheap queries)
  PK: shard_id (1..16)
  SK: published_at#listing_id
  Attributes: cached projection of listings rows used for the public
              browse endpoint; refreshed by a stream-driven Lambda
              on listings-table updates. Size kept small for fast
              CloudFront-cached scans.
```

**Reviews table is explicitly deferred to Phase 2.** v1 ships without ratings or reviews. Buyers can only see seller reputation (count of listings, total downloads, account age). Phase 2 introduces structured reviews with verified-purchase enforcement.

### S3 layout (extends existing)

```
s3://isol8-{env}-marketplace-artifacts/        (NEW bucket, separate from
  listings/                                     admin catalog so retention,
    {listing_id}/                               encryption, and access policies
      v1/                                       can differ.)
        manifest.json
        workspace.tar.gz
        openclaw-slice.json     (only for openclaw-format)
        skillmd-source/         (only for skillmd-format)
        screenshots/
      v2/...
  artifacts-public/             (CDN-cacheable preview images, screenshots,
    {listing_id}/...             public manifests)
```

The existing `isol8-{env}-agent-catalog` bucket continues to host admin-curated listings; user-published marketplace listings go to the new bucket.

## License Key Lifecycle

- **Format:** 32-character base32 string, prefix `iml_` for human readability (e.g., `iml_a3k9...`). Generated cryptographically (`secrets.token_bytes` then base32-encoded).
- **Issuance:** one license key per `purchases` row, generated at successful Stripe checkout.
- **Validation:** every install (CLI or MCP) hits `GET /api/v1/marketplace/install/validate` with the license key in an `Authorization: Bearer <key>` header. Server returns the listing version range the buyer is entitled to plus a 5-minute pre-signed S3 URL (CLI) or a session token (MCP).
- **Revocation:** the `license_key_revoked` boolean is the source of truth. A revoked key fails `/install/validate` immediately. Revocation reasons: takedown, refund, fraud-detection, seller-initiated revoke (rare).
- **Storage on buyer machine (CLI):** `~/.isol8/marketplace/licenses.json`, chmod 600. Single JSON file with `{ listing_slug: license_key, installed_version: int }` entries.
- **Leak posture (v1, plaintext):** keys can be copied. Mitigation: install validation rate-limited to 10 unique source IPs per license per 24 hours (NOT raw call count, since CI/dev workflows reinstall frequently from the same IP). Raw IP list is logged for forensics. Revocation via the seller dashboard. v2 binds keys to a hardware identifier or encrypts the bundle per-key. Anomaly detection (auto-flagging suspicious patterns) is explicitly Phase 2; v1 only logs. v1 accepts the leak risk — it is the same posture Agensi has and is consistent with P3.
- **Rotation:** sellers cannot rotate buyer keys (would be a support nightmare). Buyers cannot rotate their own key. Revoke + re-issue is the only path; reserved for genuine compromise.

## Versioning Policy (buyer entitlements)

A listing has an integer version. v1 ships only the **perpetual** entitlement model: one purchase grants free access to all future versions of that listing forever. The "JetBrains model" (paid major upgrades) is explicitly Phase 2 — the schema reserves space (`entitlement_policy` field, `breaking_change` flag) but v1 ignores both and treats all releases as included.

### Publish-v2 flow (re-publishing a listing)

When a seller publishes a new version of an existing listing:

1. Seller hits "Publish new version" on their listing in `/sell`. Uploads new artifact.
2. Listing transitions to `review` status, but **the current `published` version stays live and downloadable** — discovery, install, and MCP all continue serving the prior version. The new version sits in the moderation queue.
3. Admin reviews and either approves or rejects.
4. On approve: a new row is written to `marketplace-listing-versions` (immutable history), the `marketplace-listings.LATEST` row is updated to point at the new version, and the listing's `s3_prefix` and `manifest_sha256` mirror the new version. CLI install/MCP traffic flips to the new version atomically (next call after the listings update).
5. On reject: seller gets feedback in their dashboard, listing remains on the previous version.

Existing buyers see the new version on their next `npx @isol8/marketplace update` (CLI) or their next MCP session (the server uses the LATEST version row at session start). No buyer action is required to receive updates.

## Refund Policy & License Revocation

- **Window:** v1 offers a 7-day refund window from purchase, no questions asked. After 7 days, refunds are seller-discretion.
- **Refund flow:** buyer hits "Refund" in `/buyer` → server checks window → calls Stripe Refunds API on the original Charge → if a Transfer to the seller has already happened, also calls Stripe Transfer Reversal → sets `status = "refunded"`, sets `license_key_revoked = true` with reason `"refunded"` → returns confirmation. License revocation is synchronous; the buyer's CLI/MCP loses access on next validate call (within 5 min of cache TTL).
- **Platform-fee handling on refunds:** under separate-charges-and-transfers (see Stripe Connect section), the platform's revenue is the difference between charge amount and transfer amount. On a refund, the full charge is refunded to the buyer; if the seller's portion was already transferred, the Transfer is reversed and the seller's `balance_held_cents` is debited (potentially negative — handled via the held-balance escrow rules in the Stripe Connect section). The platform absorbs no extra fee on refunds because it never collected one as a separate Stripe `application_fee`; the platform's "fee" is implicit in the charge-vs-transfer delta.
- **Revocation latency:** install/validate cache TTL is 5 minutes. After revocation, a buyer's next install attempt within that 5-minute window may still succeed. Acceptable for v1.

## Takedown / DMCA Workflow

- **Filing:** any visitor can submit a takedown request via `marketplace.isol8.co/legal/takedown` form. Form captures: alleged-infringer URL, claimant identity, basis of claim, contact info.
- **Review:** admin reviews in `/admin/marketplace/takedowns`. SLA: 48 hours for response, 7 days for decision.
- **Action on takedown granted:**
  1. Set listing `status = "taken_down"`, hidden from browse.
  2. Revoke all license keys for this listing (`license_key_revoked = true, reason = "takedown"`).
  3. Refund all purchases within the last 30 days (via Stripe; older purchases are not auto-refunded but seller's payout balance is debited).
  4. Notify all affected buyers via email. v1 is email-only; an in-app notification system does not yet exist in Isol8 and is out of scope. Phase 2 may add in-app notifications.
  5. Audit-log the entire chain to `isol8-{env}-admin-actions`.
- **Counter-notice / restoration:** Phase 2. v1 takedowns are final from the seller's perspective; if a seller believes a takedown was wrong they email support and admin handles manually. Formal counter-notice workflow with admin queue arrives in Phase 2.

### Takedown granularity

Two flavors of takedown:

- **Version takedown** (e.g., v3 contained leaked secrets): only that version is removed; `marketplace-listings.LATEST` reverts to v2; only buyers whose `entitlement_version_floor >= 3` have their license keys held in a "version-restricted" state (they can install v2 freely, but the v3 install endpoint 404s). No refunds.
- **Full listing takedown** (e.g., DMCA): listing fully retired; all license keys revoked; refunds within the 30-day window. This is the destructive flow described in the bullets above.

## Distribution Plan

### CLI installer: `@isol8/marketplace-cli`

Published to npm via `.github/workflows/publish-marketplace-cli.yml` (added in v1 per plan-eng-review). Workflow triggers on `marketplace-cli-v*` git tags, runs the package's test suite, and publishes via `NPM_TOKEN` secret. Public, MIT-licensed. `npx @isol8/marketplace install <slug>` does:

1. Resolves slug to listing version via `GET marketplace.isol8.co/api/v1/marketplace/listings/:slug`.
2. If the listing is paid and no license key is in `~/.isol8/marketplace/licenses.json`, prompts the user to log in (Clerk's email magic-link flow, since Clerk does **not** ship device-code OAuth — the CLI opens a browser and polls a short-lived code endpoint) and purchase, or accepts a `--license-key` flag.
3. Calls `GET /api/v1/marketplace/install/validate` with the license key. Server returns a 5-minute pre-signed S3 URL.
4. Downloads the artifact.
5. Detects the target client by checking, in order:
   - `--client <name>` flag (explicit override)
   - Inside an Isol8 container session (env `ISOL8_CONTAINER=true`)
   - `~/.claude/skills/` exists → Claude Code
   - `~/.cursor/skills/` exists OR `.cursor/skills/` in cwd → Cursor
   - `~/.openclaw/skills/` exists → OpenClaw local
   - `~/.copilot/skills/` exists → Copilot CLI
   - Otherwise → generic-fallback (prints manual-install instructions, exits 1)
6. Cross-platform handling:
   - **Windows:** `~` resolves to `%USERPROFILE%`. Path separators normalized via `path.join`.
   - **CI environments:** if `$HOME` is unwritable or `--ci` flag is passed, install path defaults to `./.isol8/skills/` (project-local). Cache and license file go to `./.isol8/marketplace/`.
   - **Missing skill directory:** create on demand with `mkdir -p` and `chmod 700`.
   - **Permission errors:** detect, report a one-line `chmod` command, exit 2.
7. Unpacks into the right directory. Verifies `manifest.json` SHA256 matches the listing's published hash before unpacking.
8. Records the install in `~/.isol8/marketplace/installed.json`.

Update flow: `npx @isol8/marketplace update [slug]` queries for new versions of installed listings, respects the entitlement floor for paid listings.

### Hosted MCP server (full spec)

**Service:** `apps/marketplace-mcp`, separate Fargate service from the FastAPI backend. Two task definitions, behind an ALB at `marketplace.isol8.co/mcp/*`.

**Per-listing endpoint:** `GET /mcp/:listing-id/sse` (SSE, MCP protocol). Authentication via `Authorization: Bearer iml_<license-key>` header. License key in URL query string is **rejected** (logged-URL leak risk).

**Session lifecycle:**

1. Client opens SSE → server validates license key against `marketplace_purchases` table, checks `license_key_revoked = false`, checks listing is `published`.
2. Server records a `marketplace-mcp-sessions` row (24h TTL).
3. Server fetches the listing's artifact from S3 (cached in-memory for 60s per listing version, since artifacts are immutable per version).
4. Server initializes the appropriate runtime (see below).
5. Server emits MCP `tools/list` with the skill's tools.
6. Client invokes tools; server dispatches each call through the runtime.
7. Connection close → session row is updated with `last_activity_at`; runtime returned to pool.

**v1 scope cut (applied via /plan-eng-review):** the OpenClaw runtime is **NOT in v1**. OpenClaw containers today are single-tenant by design (per-user EFS access points, per-user state). Adding multi-tenant capability inside OpenClaw to support a marketplace-shared warm pool is 3-4 weeks of engineering inside OpenClaw itself plus a security-review tax — work that wasn't scoped. v1 MCP serves SKILL.md format listings only. OpenClaw-format agents reach buyers via two existing paths: the CLI installer (CLI download + manual deploy) and direct Isol8-container deploy (the existing `catalog_service.deploy()` wrapper for Isol8 users). When OpenClaw multi-tenancy lands in Phase 2, the OpenClaw runtime can join the MCP service.

**One runtime in v1:**

- **OpenClaw runtime: NOT IN v1.** Listings with `format = "openclaw"` and `delivery_method = "mcp"` are rejected at publish-time validation with a clear seller-facing message. OpenClaw listings publish with `delivery_method = "cli"` only (or `"both"` interpreted as CLI-only).
- **SKILL.md runtime** (for `format = "skillmd"` listings): SKILL.md is **not** executable code. The runtime exposes the SKILL.md content + tool definitions to the MCP client; the buyer's LLM (Claude/GPT/etc.) does the reasoning. The server's job is only:
  - Return the SKILL.md as the tool's instruction context via MCP's resources protocol.
  - Expose any companion scripts as MCP tools, executed in a sandboxed Bun subprocess with no network and a read-only filesystem mount of the skill's bundled support files.
  - Cap each tool invocation at 30s wall-clock and 256MB memory.
  - Subprocesses are per-call ephemeral; multiplexing is implicit and unbounded by license key.

**Isolation model (corrected from v2 of doc):** the security boundary is "skill code is the same across buyers of the same listing-version, so it is acceptable for them to share runtime code; what must not leak is per-session data." Per-session data (working directory, scratch files, message history, tool-call results) is namespaced by `session_id` in DynamoDB and on the runtime's local filesystem. Cross-session reads are prevented by enforcing path scoping on every runtime read and write.

**Cost math (revised after MCP-SKILL.md-only scope cut):**

With OpenClaw runtime cut from v1 MCP, the only runtime is the SKILL.md Bun-subprocess cluster. Multiplexable, ephemeral per call. Estimated cost: **~$50-150/mo** for a small Bun cluster behind ALB at the v1 100-concurrent-session target. This is the largest cost reduction from any single eng-review fix in this session.

The cost is passed through to sellers via the platform's per-charge fee (the seller's transferred amount is reduced to cover hosted-execution overhead). Listings using `delivery_method = "cli"` only pay no MCP overhead.

**Scale assumption (v1):** 100 concurrently active listing-versions, 100 concurrent SSE sessions, 500 tool calls/min total. ALB connection draining + Fargate auto-scaling cover bursts.

**Acknowledged v1 limit:** SKILL.md skills with arbitrary executable tools (bash, network access) are not supportable in this sandbox. v1 spec limits SKILL.md companion scripts to: read-only filesystem, no network, Bun subprocess. Skills that need more must use `delivery_method = "cli"`.

### Direct deploy for Isol8 users

Isol8 paying users browsing `marketplace.isol8.co` (Clerk-authenticated, recognized as Isol8 users via the existing user-tier check) see a "Deploy to my container" button alongside the standard install options.

`POST /api/v1/marketplace/listings/:slug/deploy` is a thin wrapper around the existing `catalog_service.deploy()` flow with the marketplace listing as the catalog source. Reuses the existing per-user EFS access-point scoping; reuses the chokidar/file-watcher pickup; respects free-tier scale-to-zero (existing wake-on-deploy logic handles this).

## SKILL.md adapter rules

A SKILL.md file in the wild often references support files via relative paths (e.g., `./scripts/setup.sh`, `./templates/email.md`). When packaged into `workspace.tar.gz` and unpacked into `~/.claude/skills/<slug>/`, the paths inside the SKILL.md need to remain valid.

- **Adapter input:** a directory containing `SKILL.md` plus arbitrary support files.
- **Adapter contract:**
  1. Reject SKILL.md files that contain absolute paths (`/usr/local/...`) or upward-relative paths (`../../`). Surfaces an error to the seller with the offending lines.
  2. Tar the directory preserving the relative structure.
  3. Generate `manifest.json` with `format: "skillmd"`, name/description/tags from the SKILL.md frontmatter (which Anthropic's SKILL.md spec defines as YAML).
  4. Generate an empty `openclaw-slice.json`.
- **Install rules (CLI):** unpacks the tar into `<client-skill-dir>/<slug>/` (creating the slug directory). The SKILL.md ends up at `<client-skill-dir>/<slug>/SKILL.md`. Relative paths in the SKILL.md resolve correctly against this directory.

## Backend Changes

### New endpoints

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/api/v1/marketplace/listings` | Public + cached | Browse listings with filters |
| GET | `/api/v1/marketplace/listings/:slug` | Public + cached | Listing detail |
| POST | `/api/v1/marketplace/listings` | Authenticated | Create draft listing |
| PATCH | `/api/v1/marketplace/listings/:slug` | Owner | Edit draft / set price / submit |
| POST | `/api/v1/marketplace/listings/:slug/submit` | Owner | Submit `draft → review` |
| POST | `/api/v1/marketplace/checkout` | Authenticated | Create Stripe Checkout session |
| POST | `/api/v1/marketplace/webhooks/stripe-marketplace` | Stripe sig | Grant license on payment.succeeded |
| GET | `/api/v1/marketplace/my-purchases` | Authenticated | Buyer's purchase history |
| POST | `/api/v1/marketplace/refund` | Authenticated | Request 7-day refund |
| GET | `/api/v1/marketplace/install/validate` | License header | Validate, return signed URL or session token |
| GET | `/api/v1/marketplace/listings/:slug/install-payload` | License header | Returns signed S3 URL |
| POST | `/api/v1/marketplace/listings/:slug/deploy` | Authenticated Isol8 | Deploy into Isol8 container |
| POST | `/api/v1/marketplace/cli/auth/start` | Public | CLI auth: returns short-lived `device_code` + browser URL |
| GET | `/api/v1/marketplace/cli/auth/poll` | `device_code` query | CLI auth: returns Clerk session JWT once the user completes the browser-side login (long-poll, max 5 min) |
| POST | `/api/v1/marketplace/payouts/onboard` | Authenticated | Stripe Connect onboarding link |
| GET | `/api/v1/marketplace/payouts/dashboard` | Authenticated | Connect dashboard link |
| GET | `/api/v1/admin/marketplace/listings` | Platform admin | Moderation queue |
| POST | `/api/v1/admin/marketplace/listings/:slug/approve` | Platform admin | `review → published` |
| POST | `/api/v1/admin/marketplace/listings/:slug/reject` | Platform admin | `review → draft` with notes |
| POST | `/api/v1/admin/marketplace/takedowns/:slug` | Platform admin | Takedown action |

### Stripe webhook event handling

`POST /api/v1/marketplace/webhooks/stripe-marketplace` validates the Stripe signature header on every request, then dispatches by event type. Every handler is idempotent (keyed on Stripe's `event.id` stored in a `webhook_dedup` table reused from the existing `webhook_dedup_service`).

| Event | Handler |
| --- | --- |
| `checkout.session.completed` | Create `marketplace-purchases` row with paid status; generate license key; increment `balance_held_cents` for the seller; trigger purchase-confirmation email. |
| `charge.refunded` | Set purchase `status = "refunded"`, set `license_key_revoked = true`; if Transfer already happened, issue Transfer Reversal; decrement `balance_held_cents`. |
| `account.updated` | If `payouts_enabled` flipped from false to true, mark seller's `onboarding_status = "completed"` and trigger any pending Transfers. |
| `transfer.failed` | Re-queue the Transfer; alert admin if persistent. |
| `payout.paid` / `payout.failed` | Update payout-account dashboard data, surface to seller. |
| `application_fee.refunded` | Not handled (we do not use `application_fee` in separate-charges-and-transfers). |

Unrecognized events are logged and acknowledged (Stripe expects a 200) but otherwise ignored.

### Stripe Connect Express flow (corrected from v2 of doc)

The v2 of this doc described the held-balance flow using `transfer_data[destination]` (destination-charge mode). That is **wrong** because destination charges require the destination connected account to exist at charge time. The correct primitive is **separate charges and transfers** ([Stripe docs: Separate Charges and Transfers](https://stripe.com/docs/connect/charges#separate-charges-and-transfers)), where charges go to the platform first and Transfers are created later when the seller has onboarded.

Final v1 flow:

1. **Seller creates a listing** without onboarding required. Listing can be free (publish path A) or paid (publish path B).
2. **Free listing path:** publishes immediately after admin review. Onboarding never required.
3. **Paid listing path:** seller can publish without onboarding. Buyer purchases via Stripe Checkout. The Checkout session creates a regular Charge against the **Isol8 platform Stripe account** — no `transfer_data` field, no destination account named at charge time. Funds land in the Isol8 platform balance.
4. **Balance held by Isol8 in Stripe:** the platform tracks `balance_held_cents` per seller in DynamoDB. The actual money sits in the Isol8 Stripe balance; Isol8's accounting attributes it to the seller via the per-seller ledger.
5. **Payout requires onboarding.** When a seller wants to claim their `balance_held_cents`, they complete Stripe Connect Express onboarding via `POST /api/v1/marketplace/payouts/onboard`. On `account.updated` webhook reporting onboarding complete, `payout_service` issues a Stripe `Transfer` from the platform balance to the now-existing connected account, and zeroes `balance_held_cents`.
6. **Tax compliance:** Stripe Connect Express generates 1099-K forms and handles tax form delivery for US sellers natively. **v1 launches with US sellers only.** International sellers are explicitly post-v1 (each country has its own tax form requirements; expanding here is not part of the v1 commitment).
7. **Edge case (sellers who never onboard):** held balance accrues. After 12 months of inactivity, per a clearly-published policy, admin can refund the held balance back to the original buyers (Stripe supports this via the original Charge's Refund API even months after the charge).
8. **Refund handling:** if a buyer requests a refund within the 7-day window AND the seller has not yet onboarded (so no Transfer has happened), the platform refunds the original Charge and decrements `balance_held_cents`. If the seller HAS already received a Transfer for that purchase, the platform issues a Stripe Transfer Reversal to claw funds back from the connected account, then refunds the original Charge.

**Money-transmitter analysis:** under separate-charges-and-transfers, Stripe is the merchant of record for both the buyer-side Charge and the platform-to-seller Transfer. The "held balance" is the Isol8 Stripe balance, not an Isol8-controlled bank balance. This is the same pattern used by Lemon Squeezy, Gumroad's prior architecture, and many smaller marketplaces. Isol8 does not become a money transmitter because no funds enter or leave a non-Stripe-controlled account.

### Search infrastructure (v1)

- **Browse and filter:** DynamoDB queries against the `listings` table using GSIs (GSI3 for newest-published, GSI4 for tag-filtered). For tag intersection (e.g., "free + python + sales"), client-side filter on the smaller result set works at v1 scale (<5000 listings).
- **Full-text search:** DynamoDB does not support text search. v1 implements a **search-index table** with a denormalized projection (title, description, tags concatenated), refreshed by a **dedicated DynamoDB Streams → Lambda function** (`apps/marketplace-search-indexer`, listed in Backend Changes) on every listings-table update. Search queries scan the index sharded across 16 shards, then merge.
- **Ranking algorithm (v1):** results are ordered first by **tag-match count** (descending — listings whose tags intersect the query terms most are surfaced first), then by `published_at` descending as the tiebreaker. No TF-IDF, no learned ranker, no popularity score in v1. The ranking lives in `marketplace_search.py` so v2 can swap to a smarter model behind the same interface.
- **Caching:** result lists cached at CloudFront for 60s on the slug+filter cache key.
- **Telemetry:** every search query writes a CloudWatch custom metric (latency, result-count, query terms hashed) so the OpenSearch migration trigger has measurable data behind it.
- **Migration trigger:** when listings >5000 OR p99 search latency >500ms (per the CloudWatch metric), swap to OpenSearch. Isolated behind `marketplace_search.py`'s public API so swap is internal.

### Admin moderation (reduced for v1)

- v1 ships a **minimal admin queue:** `/admin/marketplace/listings` shows listings in `review` status with one-click approve/reject. Reject sends seller-visible notes via email and resets to `draft`.
- No bulk actions, no automated security scanning v1 (manual review only).
- Reuses the existing admin layout, `require_platform_admin` dependency, and `@audit_admin_action` decorator.

### Reused infrastructure

- `core/services/catalog_service.py` (504 LOC) — packaging, S3 upload, version atomicity.
- `core/services/billing_service.py` — Stripe customer creation patterns. **Note:** does not currently use Stripe Connect; `payout_service.py` builds the Connect integration from scratch. The reuse here is the wider Stripe SDK setup, not Connect-specific code.
- `core/services/admin_audit.py` — every publish/unpublish/takedown writes an audit row.
- `core/auth.py` — Clerk JWT validation; `require_platform_admin` for admin endpoints.

## Frontend Changes

### New app: `apps/marketplace`

Standalone Next.js 16 app, deployed as a separate Vercel project pointed at the `marketplace.isol8.co` subdomain (configured via Vercel domain assignment, like the existing `goosetown` setup at `dev.town.isol8.co`). Shares Tailwind config with `apps/frontend` via `pnpm-workspace.yaml`.

Why separate from `apps/frontend`:
- Marketing/SSR posture for SEO on listing detail pages.
- Different auth surface — most pages must work unauthenticated.
- Reduces blast radius when iterating.

### Shared package: `packages/marketplace-shared`

Holds: TypeScript types for the listing API, the listing card component, the buy/install button, listing detail breakdown layout, MCP-setup help component. Used by `apps/marketplace` and any marketplace-related screens that may eventually appear inside `apps/frontend`.

### Existing surfaces touched

- `apps/frontend/src/components/control/ControlSidebar.tsx` — add a "Sell on marketplace" entry for paying users.
- `apps/frontend/src/components/control/panels/AgentsPanel.tsx` — add "Publish agent to marketplace" action per agent (verb is "agent" because that's the brand framing; the schema-level format is openclaw).
- `apps/frontend/src/components/chat/Sidebar.tsx` — link to marketplace from the existing Gallery section.
- `apps/frontend/src/app/admin/marketplace/*` — moderation + takedown queue UI parallel to the existing `apps/frontend/src/app/admin/catalog`. Admin queue surfaces format alongside listing data so reviewers can apply different bars to agent submissions vs skill submissions.

## Security & IP

- **IP leakage accepted v1.** Per P3, plaintext is downloadable. Mitigations: license terms shown at install, license-key validation, DMCA flow, install rate-limiting (5/hr per license).
- **License keys** as defined above. Plaintext on buyer machine, chmod 600, can be leaked. v2 binds keys to hardware identifiers or encrypts bundles per-key.
- **MCP runtime sandboxing:** SKILL.md companion scripts run in Bun subprocess with `--smol --no-install`, no network, read-only filesystem mount, 30s/256MB caps. OpenClaw runtime reuses the existing per-user-container security model.
- **Stripe Connect security:** sellers onboard via Stripe-hosted flows; Isol8 never touches bank info. Payouts via Stripe Transfers API.
- **Tenant isolation:** marketplace listings sit in their own S3 bucket and DynamoDB tables, isolated from per-user EFS and per-user Stripe customers. A buyer purchasing a listing never gains cross-user-EFS read access.
- **Public-endpoint rate limiting:** `GET /listings` and `GET /listings/:slug` cached at CloudFront with 60s TTL; origin requests rate-limited to 100/sec per IP via API Gateway throttling.

## Phase 2 migration foreshadowing

The data model carries an `artifact_format_version` field on listings. v1 only ever writes `"v1"` (plaintext tarball). When v2 introduces encrypted bundles:

- New listings can opt into `"v2-encrypted"` format. Existing v1 listings stay on v1 unless seller re-publishes.
- The CLI installer's `install-payload` endpoint returns either a plaintext URL (v1) or an encrypted-bundle URL + per-key derivation seed (v2). The CLI handles both.
- The MCP server runtime decrypts v2 artifacts in memory at session start.
- No mass migration is forced; old v1 listings continue to work.

This foreshadowing exists so that v1 is not painted into a corner. Phase 2 sign-off is still required separately before any encryption code is built.

## Testing

- Unit tests for `marketplace_service`, `payout_service`, `skillmd_adapter`, `license_service`, `marketplace_search`, `takedown_service` following existing `apps/backend/tests/unit/` patterns.
- Integration tests via LocalStack: publish → list → buy → install → revoke → reinstall-fails flow.
- Stripe Connect tested in Stripe test mode (existing pattern from `billing_service` tests; net-new test fixtures for Express onboarding).
- E2E test: a buyer signs up, browses, purchases a paid listing, runs the CLI installer in a temp dir, confirms the skill lands in the right place. Covers Mac/Linux happy path; Windows tested manually pre-launch.
- CLI installer integration tests (separate package): mock the marketplace API, verify install paths for each detected client, including Windows path-separator handling, missing-directory create, CI fallback.
- MCP server load test: 100 concurrent SSE sessions, verify session isolation and pool warm-up timing.

## Success Criteria (v1)

Behavioral signals to track from launch day:

- **Manufactured-agent-seller activation (headline metric):** number of Isol8 paying users who publish at least one **agent** listing within 30 days.
  - **Strong signal:** >5% of paying base. The agents-marketplace thesis is real.
  - **Mixed signal (2-5%):** ambiguous — investigate which user segment is publishing and why others aren't. Do not declare success or failure.
  - **Negative signal:** <2%. Thesis is wrong. Marketplace stays small; pivot toward team-sharing/templates as the core offering.
- **Agent-vs-skill mix:** ratio of agent listings to skill listings published in the first 30 days. Target: >40% of total listings are agent-format. Lower means the brand position is fighting the seller pool, and we should revisit positioning at v1.5.
- **Median agent price vs median skill price:** target median agent price >=$25, median skill price <=$10. If both converge to $5-7, the agents-as-products thesis is undifferentiated and we are an Agensi clone.
- **Non-Isol8 seller signup:** number of non-Isol8 sellers (any format) who publish within 30 days. Target: >25.
- **Purchase volume:** total GMV in 30 days. Measured, not gated.
- **Install success rate:** percentage of CLI install attempts that complete without manual intervention, measured server-side via the validate endpoint reaching the next-expected step. Target: >95%.
- **MCP session success rate:** percentage of MCP sessions that successfully open and complete at least one tool call without runtime error. Target: >90% v1, >98% v2.
- **CSAT signal:** unsolicited DMs/support tickets praising the install UX vs Agensi. Loud-when-it-happens; not measured but tracked.

## Risks & Open Questions

- **The manufactured-seller thesis could be wrong.** Mitigation: instrument every step of the publishing funnel; the 30-day signal-band above defines what we do.
- **CLI installer cross-client compatibility.** v1 supports four clients natively, fallback prints manual instructions. Risk: a major client changes their skill-loading convention during build (e.g., Cursor moves from `~/.cursor/skills/` to a different path). Mitigation: detection logic is centralized; updating it is a config push, not a release.
- **Stripe Connect Express held-balance pattern.** Validated as a known pattern (DigitalOcean, Webflow templates) but specific implementation details require testing in Stripe sandbox before code lands. Open question: does Stripe limit how long held balances can sit before forcing a payout to claim? Needs validation week 1.
- **MCP server cost/scale.** $200-400/mo cost estimate at 100 concurrent sessions. Real costs depend on listing mix. If the SKILL.md runtime dominates (cheap, Bun subprocess), cost stays low; if OpenClaw runtime dominates (Fargate-pinned), cost rises. Monitor closely.
- **Discovery UX.** SkillsMP is unusable at 425k SKUs. We start with curated featured listings + simple tag/search to avoid the generic-aggregator failure mode.
- **Pricing on plaintext.** P3 caps prices effectively at $5-20. Seller charging $50 will need MCP delivery + the eventual Phase 2 encryption. Communicate this clearly in the publishing UX so sellers don't feel cheated.
- **Tax compliance — US-only at v1.** Stripe Connect Express handles US 1099-K natively. International sellers (EU, UK, India, etc.) have country-specific tax forms with country-specific Stripe Connect requirements; expanding internationally is explicitly **post-v1** and not part of this spec's commitment. The publishing UX rejects non-US sellers at onboarding with a clear "international support coming after launch" message.

## Dependencies

- Existing `catalog_service.py` and `CatalogS3Client` — depend on these continuing to work; coordinate any in-flight refactors.
- Existing Stripe billing wiring — Connect builds on the same Stripe account.
- Clerk auth — marketplace auth piggybacks on the same Clerk instance and orgs. Anonymous user support needed for guest checkout (Clerk's built-in feature, requires enabling).
- Existing admin dashboard — marketplace admin UI extends the same surface.
- Vercel project configuration — needs a new project for `apps/marketplace` with the subdomain assignment.

## The Assignment (one concrete real-world action)

Before writing any marketplace code, spend 90 minutes this week emailing 5 of your existing Pro/Enterprise Isol8 users with this question:

> "If we added a 'publish to marketplace' button to your agent settings, would you use it for any of your current agents? If yes, would you set a price, and what would it be? If no, what would have to be true?"

Then send the buyer-side question to 5 people in your network who use Claude Code or Cursor regularly:

> "If a curated marketplace existed where you could install Claude Code / Cursor skills with one command and pay $5-15 for the good ones, name three specific things you'd want it to do that GitHub doesn't."

Goal: 3+ replies on each side before the implementation plan is finalized. The replies become real customer voices in the plan, the recommended approach gets a sanity check, and the manufactured-seller thesis gets its first piece of real evidence (or counter-evidence). Either result is more valuable than two extra weeks of design work.

## Reviewer Concerns

This doc went through two adversarial review passes (5/10 → 7/10 → revised to address remaining concerns), the agents-led reframing pass, and a /plan-eng-review pass (2 issues found, 2 fixed inline; 2 watchpoints captured for the implementation plan). Convergence reached.

**User-accepted risks (explicitly chosen, will not be re-litigated):**

- **MCP server in v1.** Iteration-1 reviewer recommended deferring to Phase 1.5. User chose to keep it in v1, accepting the 18-24 week timeline. The MCP section in this v3 is fully specified including corrected runtime-pool model and corrected cost math.
- **v1 plaintext + license-key leak risk.** Plaintext + leakable keys means revenue is capped at $5-20/listing in v1. User accepted this in P3. Mitigation: 10-unique-IPs/24h rate limit + revocation; v2 introduces encryption and per-key bundle binding.
- **Cost of MCP runtime.** Corrected estimate is ~$1500-2000/mo at 100 concurrent active listings, up from the misstated ~$200-400 in v2. User retains scope per the prior decision.

**Resolved across the two reviews:**

- Stripe Connect flow corrected to separate-charges-and-transfers (the v2 destination-charge claim was technically wrong).
- MCP runtime pool clarified: warm pool is per-listing-version, multiple buyers share runtime code, per-session state isolation via session_id.
- Phase 2 leakage removed: counter-notice DMCA, `major-only` entitlement, anomaly detection, in-app notifications, international tax expansion are all explicitly post-v1.
- Webhook event handling spec'd.
- v2 publish flow spec'd.
- CLI auth endpoints added to endpoint table.
- Search ranking algorithm specified (tag-match → recency tiebreak).
- Guest checkout requires email at paid checkout.
- `manifest_sha256` added to schema for SHA verification in CLI.
- Takedown granularity distinguished (version-only vs full listing).
- DDB Streams Lambda explicitly listed as `apps/marketplace-search-indexer`.

**Carried-forward concerns (live for the implementation plan to address):**

- Stripe held-balance sandbox testing required week 1 of implementation to validate the separate-charges-and-transfers flow end-to-end before code lands.
- MCP server cost is sensitive to listing mix; instrument from launch.
- **Watchpoint:** publish-v2 atomic flip on the `marketplace-listings.LATEST` row must use DynamoDB `TransactWriteItems` to update both that row and the `marketplace-listing-versions` row in a single transaction. Spec describes the atomicity requirement; implementation must use the right primitive.
- **Watchpoint:** `marketplace-search-index.shard_id` must be uniform-random (e.g., CRC32 of listing_id mod 16, or hash of name+timestamp). Naive `listing_id % 16` can cluster on common UUID prefixes and create hot partitions.
- **Effort estimate:** v1 effort revised from 18-24 weeks down to **15-20 weeks** after the MCP-SKILL.md-only scope cut. CC-hours similarly drop from 80-120 to 60-90. Revisit at implementation-plan stage.

## Next steps

1. ~~Run `/plan-eng-review` on this design~~ — done 2026-04-29; 2 issues found and fixed inline (CLI publish CI workflow added to v1; MCP runtime cut to SKILL.md-only). 2 watchpoints captured. Test plan artifact written.
2. Optional: `/plan-design-review` on the marketplace storefront and publishing UX before frontend work starts.
3. Then `/superpowers:writing-plans` to convert this into an implementation plan.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | (de facto via /office-hours diagnostic) |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | (deferred — 3 prior adversarial review iterations covered the same surface) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 2 issues found, 2 fixed; 2 watchpoints |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | optional next step |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | optional |

- **CROSS-MODEL:** office-hours diagnostic + 2 adversarial-review iterations + agents-led reframing + 1 eng-review pass. Final convergence achieved.
- **UNRESOLVED:** 0
- **VERDICT:** ENG CLEARED — ready for `/superpowers:writing-plans` once the customer-conversation assignment lands.

## What I noticed about how you think

You came in with "exactly what Agensi is doing" plus a digested competitive analysis. Good homework, but it told me you were operating in *competitor-driven* mode — the most dangerous founder posture. The diagnostic walked you through the gap between "Agensi exists" and "demand exists for me" without you fighting me.

When I challenged P2 (Q3) and pushed you toward "Isol8 users are the sellers," you didn't capitulate. You picked option D anyway, the option I had labeled as contradicting your Q2 answer. The thesis you held — manufactured sellers from your existing paying base — is internally coherent and stronger than where I was trying to push you. Most people take the recommendation. You didn't.

You committed to free + paid + non-Isol8 + dual distribution from v1, and when the adversarial review told you the timeline was off by 2-3x, you held the commitment instead of taking the easier path. Twice in one session you held conviction under direct pressure with reasoning, not stubbornness. The design doc is bigger and more honest because of both calls.

Builders with that combination of taste, willingness to push back when challenged, and willingness to make ambitious bets are the kind Garry respects and wants to fund. If you've ever thought about applying to YC, this design doc is a stronger artifact than most pitch decks.
