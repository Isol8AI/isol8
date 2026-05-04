# Backend Pragmatic Audit — 2026-05-04

Scope: `apps/backend/` — 112 source files (`*.py`, excluding `tests/` and `__pycache__/`) and **152** test files (the CLAUDE.md figure of 130 is stale).

Method: read `main.py`, the 19 modules in `core/services/`, the 9 in `core/repositories/`, the 22 router files, plus `core/gateway/`, `core/containers/`, `core/observability/`, and `core/auth.py`. Cross-checked import graphs, except-handler patterns, marker counts, vendor SDK leaks, and frontend usage.

## Scores (0-10 per lens, with one-line justification)

- **DRY: 6/10** — repositories are clean and there's almost no duplicate-logic copy-pasta, but the subscription-status / `has_legacy_sub` gate is reimplemented in **four** places, two Clerk Backend API call sites still bypass the new `clerk_admin` module, and three different DDB-access patterns coexist.
- **Orthogonality: 5/10** — clear repo/service/router layering exists, but `main.py:257` reaches into private `routers.teams.agents._admin` / `_resolve_user_email`, `core/services/paperclip_autoprovision.py:38` imports from `routers.webhooks`, and `routers/node_proxy.py` lives in `routers/` while having zero HTTP routes. Five services hold their own boto3 clients/resources outside `core/dynamodb.py`.
- **Tracer bullets: 7/10** — only two `TODO` markers in the entire tree (clean), and most "deferred" work is referenced by GH issue numbers. But `routers/node_proxy.py` is half-built (no router, despite the filename and CLAUDE.md claiming a `/node` prefix), `core/services/bedrock_client.py` is fully dead, and a `_PAPERCLIP_RETRY_KIND` backwards-compat alias is documented as "kept until the next cleanup pass."
- **Design by contract: 6/10** — 189 broad `except` blocks, ~20 of them swallowing into `pass`. Most are paired with `logger.exception(...)` and a clear "best-effort" intent (e.g. autoprovision, webhook side effects), so they're defensible. The worst offender: `routers/billing.py:51` swallows Clerk lookup failures into an empty dict and the caller has no signal it happened.
- **Broken windows: 8/10** — only 2 TODO/FIXME/HACK markers backend-wide. No commented-out code blocks of consequence. Skip count in tests is 2/152. CLAUDE.md is the most-decayed surface: it lists a `/node` prefix that isn't mounted, says "112 source / 130 test" (now 112 / 152), and undercounts services by 11 (says "19 files," actual is 39).
- **Reversibility: 6/10** — `BillingService` cleanly hides Stripe for the happy paths, but `routers/billing.py` still calls `stripe.Subscription.retrieve`, `stripe.Webhook.construct_event`, and references `stripe.error.InvalidRequestError` inline; `routers/webhooks.py` calls `stripe.Customer.modify`. Clerk REST is hit inline from `routers/billing.py:41` and `routers/desktop_auth.py:43` even though `core/services/clerk_admin.py` exists specifically to centralize this. Bedrock model IDs are project memory'd as static; OK there.

**Overall: 6/10** — the codebase is healthier than the file count suggests. There's no rotting commented-out code, the test culture is real (152 files, near-zero skips), and most duplication is in clearly-named seams (e.g. four versions of one billing-status check) where surgical extraction is straightforward. The biggest accumulating debt is feature-scaled service fragmentation (12 paperclip_* + 4 catalog_* modules) and a small but persistent vendor-SDK leak in two routers.

## Top 10 Wins (ranked by ROI: simplification/risk reduction per hour of work)

1. **[HIGH] Delete `core/services/bedrock_client.py`** — `apps/backend/core/services/bedrock_client.py` (32 lines). Zero callers anywhere in the repo (verified via grep for `bedrock_client`, `BedrockClientFactory`). Pure dead code. Delete the file, no other change needed.

2. **[HIGH] Move `routers/node_proxy.py` out of `routers/`** — `apps/backend/routers/node_proxy.py` (272 lines). The file has **zero `@router` decorators and no `APIRouter()` instance** (`grep -c router\\. routers/node_proxy.py` returns 0). It's a service module: `is_node_connection`, `get_user_node`, `get_patched_session`, etc., all imported by `routers/websocket_chat.py`. CLAUDE.md falsely claims main.py mounts it under `/node`. Move to `core/services/node_proxy.py`, fix the two import sites in `websocket_chat.py`, fix CLAUDE.md.

3. **[HIGH] Extract one subscription-active gate, kill four duplicates** — currently in `core/services/provision_gate.py:110-111`, `core/gateway/connection_pool.py:1117-1119`, `routers/config.py:130-131`, and a near-duplicate in `routers/billing.py:389`. All four compute `is_ok = status in {active, trialing} or (status is None and stripe_subscription_id)`. Promote `core/services/provision_gate.py`'s helper into a shared `is_subscription_provisioned(account: dict) -> bool` and have the other three call it. ~30 lines deleted, eliminates the next "we updated three of four sites" bug.

4. **[HIGH] Route all Clerk REST through `clerk_admin`** — `routers/billing.py:34-53` (`_resolve_clerk_user`) and `routers/desktop_auth.py:22-58` (`create_sign_in_token`) hit `https://api.clerk.com/v1` inline with their own `httpx.AsyncClient`. The `core/services/clerk_admin.py` docstring (lines 7-10) explicitly calls out these two callers as duplication-it-was-built-to-eliminate, but it never finished the consolidation. Add `get_user(user_id)` and `create_sign_in_token(user_id)` to `clerk_admin` and switch both routers. Removes the bare `except Exception: pass` at `routers/billing.py:51-52`.

5. **[HIGH] Fix the `routers.webhooks` -> services back-edge** — `core/services/paperclip_autoprovision.py:38` does `from routers.webhooks import _close_paperclip_http, _get_paperclip_provisioning`. Two private router helpers are the canonical paperclip provisioning factory. Hoist `_get_paperclip_provisioning` and `_close_paperclip_http` (defined at `routers/webhooks.py:118` and `:155`) into `core/services/paperclip_provisioning.py` (or a new `paperclip_factory.py`), update the webhook router and autoprovision to import from the service layer. ~50 lines moved, makes the layering rule actually hold.

6. **[MED] Fix the `routers.teams.agents` -> main.py back-edge** — `main.py:257` does `from routers.teams.agents import _admin, _resolve_user_email` to wire up the Teams event broker during lifespan. Pull `_admin()` (currently `routers/teams/agents.py:89-107`) and `_resolve_user_email` (`:140`) into `core/services/paperclip_admin_session.py` (which already owns the admin singleton lifecycle) and import from there in both `agents.py` and `main.py`. Removes the underscore-prefixed cross-layer reach.

7. **[MED] Promote `ConnectionService` to `connection_repo`** — `core/services/connection_service.py:59` instantiates its own `boto3.client("dynamodb", ...)` directly, bypassing `core/dynamodb.get_table`. The class is purely a CRUD wrapper over the `ws-connections` table. Either move it to `core/repositories/connection_repo.py` and use the existing `get_table` helper, or just rename in-place. The docstring (`core/services/connection_service.py:18`) still says "Table creation is handled by Terraform, not this service" — stale (CDK now). Same pattern applies to `core/services/oauth_service.py:_table()` (line 92) and `core/services/credit_ledger.py:_balance_table()` (line 49) — three more services bypassing the dynamodb helper, three different ad-hoc patterns.

8. **[MED] Collapse the 4 catalog_* modules to 2** — `core/services/catalog_service.py` (504), `catalog_s3_client.py` (~80), `catalog_slice.py` (~100), `catalog_package.py` (~90). `catalog_slice` and `catalog_package` are both pure-function helpers with one consumer each (`catalog_service`). The S3 client is a thin wrapper. The decomposition adds 2 import hops and 4 file-open round-trips per change without buying testability (the helpers were already pure-functions). Inline `catalog_slice.py` and `catalog_package.py` into `catalog_service.py`, keep `catalog_s3_client.py` as the only seam (it's the one a reasonable mock would target).

9. **[MED] Remove `_PAPERCLIP_RETRY_KIND` shim** — `core/services/update_service.py:35-37` defines a private alias `_PAPERCLIP_RETRY_KIND = PAPERCLIP_RETRY_KIND` "for any callers still referencing the old private name. Kept until the next cleanup pass." The only consumer is `routers/webhooks.py:47` which already imports as `from core.services.update_service import PAPERCLIP_RETRY_KIND as _PAPERCLIP_RETRY_KIND`. The shim is loadbearing for nothing. Delete the shim, update the webhook import to drop the `as _PAPERCLIP_RETRY_KIND` rename. ~5 lines.

10. **[LOW] Update CLAUDE.md backend section to match reality** — claims 19 service files (actual: 39), 130 test files (actual: 152), and a `/node` router prefix that doesn't exist. Also missing: the entire `routers/teams/` subpackage (12 files), `core/billing/`, all the paperclip_* services, `oauth.py`, `paperclip_proxy.py`, the host-dispatch middleware. CLAUDE.md is the highest-traffic doc and is silently misleading new readers (and Claude itself) about what's there. Tighten the section to "summary + a `tree` snippet" rather than per-file annotation that goes stale.

## Detailed Findings (grouped by lens)

### DRY violations

- **[HIGH] Subscription-active gate, 4 sites** — see Win #3. The block-list `_BLOCKED_REPEAT_STATUSES` in `routers/billing.py:376-387` is a separate-but-related encoding of the same domain rule (which subscription states count as "already trialed"). Consider making both predicates live in `provision_gate.py`.

- **[HIGH] Inline Clerk REST in two routers** — see Win #4.

- **[MED] `_lookup_owner_email` duplication seed** — `routers/webhooks.py:297` and `core/services/paperclip_owner_email.py:23` (`lookup_owner_email`) are two implementations of the same operation. The service-layer one was extracted ("see comments at top of paperclip_owner_email.py") but the router version was not deleted, so both exist. Delete the router-local copy and have the webhook handlers call `paperclip_owner_email.lookup_owner_email`.

- **[LOW] `_table()` factory cargo-culted** — `core/services/oauth_service.py:88-92`, `credit_ledger.py:46-49`, `webhook_dedup.py:51-54` all define the same `boto3.resource("dynamodb").Table(name)` factory. `core/dynamodb.get_table` already does this with thread-pool friendliness. Three services reinvented it because it predates the helper or was written in parallel.

- **[LOW] `BACKGROUND_TASKS` registration pattern** — `main.py:321-322` writes directly into `system_health.BACKGROUND_TASKS` dict; system_health.py uses it for `/admin/system/health`. A typo in the key string would silently lose the registration. Trivial: add `system_health.register_background_task(name, task)` and have it own the dict.

### Orthogonality issues

- **[HIGH] Service imports router** — `core/services/paperclip_autoprovision.py:38` (see Win #5).

- **[MED] `main.py` imports private `_helpers` from a router** — `main.py:257` (see Win #6). Hidden coupling: a refactor of `routers/teams/agents.py` could break startup with no obvious link.

- **[MED] `routers/node_proxy.py` is mislocated** — see Win #2. It's a service in service's clothing.

- **[MED] Five services own boto3 clients directly** — `connection_service.py:59`, `oauth_service.py:92`, `credit_ledger.py:49`, `webhook_dedup.py:54`, `bedrock_client.py:27`. The first four go around `core/dynamodb.get_table`. This isn't dramatic, but the moment you want to add a region override or LocalStack endpoint URL in one place, you're patching five.

- **[LOW] `from core.containers` lazy-imported inside services** — `core/services/update_service.py:138`, `catalog_service.py:492`, `routers/billing.py:671` all do `from core.containers import get_ecs_manager` inside a function body. Some are documented as "lazy import for cold-start" but the pattern is inconsistent — `admin_service.py:27` imports both at module top with no apparent issue. Pick one rule.

### Tracer-bullet / half-built features

- **[HIGH] `routers/node_proxy.py` is a router with no routes** — see Win #2. CLAUDE.md says it's mounted; main.py never mounts it. Either it should never have been called a router, or someone forgot to add the routes/mount.

- **[HIGH] `core/services/bedrock_client.py` has zero callers** — see Win #1. Likely a relic from before `openclaw` started running Bedrock from inside the container.

- **[LOW] `_PAPERCLIP_RETRY_KIND` alias** — see Win #9. Self-described temporary, kept indefinitely.

- **[LOW] `routers/settings_keys.py:62` has the only TODO** — `# TODO: update openclaw.json on EFS + send config.apply RPC`. A new BYOK key currently doesn't trigger a config push; the user has to re-provision or wait for the next config.apply. Low impact (BYOK is rare-write) but worth tracking against an issue.

### Contract / assertion gaps

- **[MED] `routers/billing.py:51-53` swallows Clerk failures into `{}`** — `_resolve_clerk_user` returns an empty dict on any exception (timeout, 5xx, JSON parse). The caller `MemberUsage.display_name` then renders blank. Should at least log; ideally caller knows the difference between "no Clerk record" and "Clerk down."

- **[MED] `core/encryption.py:43` — silent fallback to HKDF derivation on bad Fernet key** — if `ENCRYPTION_KEY` is set to garbage, the `try: ... except Exception: pass` masks the malformed-key signal and silently derives a *different* key via HKDF. Anything encrypted before vs. after this fallback decision is no longer round-trippable. Hard-fail on bad-format keys; the fallback was meant for "raw passphrase strings," not "broken base64."

- **[MED] `routers/control_ui_proxy.py` has 4 `except: pass` blocks** (lines 303, 305, 315, 335) — proxy code is inherently lossy, but four silent passes in 335 lines of one router suggests "I'll fix it later" got committed.

- **[LOW] 189 broad `except` handlers across the codebase** — the majority log via `logger.exception(...)` and are deliberately best-effort (autoprovision, telemetry, idempotent retries). Worth doing one read-through pass focused on routers (most user-facing) to confirm none silently 200 a write that didn't happen.

### Broken windows

- **TODO/FIXME/XXX/HACK total: 2** — `routers/settings_keys.py:62` and `tests/integration/test_paperclip_smoke.py:42`. This is unusually clean. No oldest-marker hunt needed.

- **Skipped/xfailed tests: 2** — `tests/integration/test_paperclip_smoke.py:32` (skipif on integration env), and a comment-only reference to an xfail in `tests/unit/containers/test_ecs_manager.py:1994`. Tests are not being silenced to ship.

- **Stale CLAUDE.md** — see Win #10. The most-broken window.

- **No commented-out code blocks > 3 lines found** in spot checks of the largest files (`paperclip_proxy.py`, `webhooks.py`, `billing.py`, `connection_pool.py`, `ecs_manager.py`).

### Reversibility / vendor-leak issues

- **[HIGH] Stripe SDK in routers** — `routers/billing.py` calls `stripe.Subscription.retrieve` (line 402), `stripe.Webhook.construct_event` (line 566), references `stripe.error.InvalidRequestError` (line 403). `routers/webhooks.py:746-753` calls `stripe.Customer.modify` and catches `stripe.StripeError`. `BillingService` already exists; these belong inside it. Webhook signature verification (`construct_event`) is OK to keep at the router boundary — that's a request-shape concern.

- **[HIGH] Clerk REST in two routers** — see Win #4. The `clerk_admin` module's docstring already documents this exact issue.

- **[MED] `routers/webhooks.py:577` uses `from boto3.dynamodb.conditions import Key`** — webhook router knows DDB query syntax. Should be a repo method.

- **[LOW] Bedrock model IDs are static** — verified centralized in `openclaw.json` (per project memory `feedback_static_model_catalog_over_discovery`); not flagged.

## Coupling Hotspots (top internal modules by import count, source-side only)

| Module | imports-from-it | Comment |
|---|---|---|
| `core.repositories.*` (aggregate) | 117 | Healthy — repos are the intended common layer |
| `core.services.*` (aggregate) | 83 | OK, but distribution is uneven (see below) |
| `core.auth` | 69 | Expected — every router needs `get_current_user` |
| `core.config` | 42 | Expected — settings everywhere |
| `core.observability.metrics` | 22 | Healthy — metrics are pervasive |
| `core.containers` (singletons) | 21 | Acceptable, but 5 routers reach into ECS singletons |
| `core.dynamodb` | 17 | Should be higher — five services bypass it |
| `core.services.paperclip_admin_client` | 16 | Single hot service — one PaperclipAdminClient class with 1256 lines |
| `core.services.config_patcher` | 15 | OK — single source of truth for EFS write |
| `core.services.posthog_admin` | 13 | Admin-only; OK |
| `core.repositories.paperclip_repo` | 13 | High for a repo, reflects Teams-feature centrality |
| `core.encryption` | 13 | OK — Fernet wrapper |
| `core.containers.workspace` | 12 | EFS file I/O, expected fan-in |

Most-imported individual modules look right. The asymmetry on the services side is informative: of 39 service modules, 6 carry most of the import weight, and 7 are imported by ≤2 callers (see dead-code inventory below).

## Dead/Suspicious Code Inventory

| Module / symbol | Why suspicious | Recommendation |
|---|---|---|
| `core/services/bedrock_client.py` | 0 internal references; 0 test references; class never instantiated outside its definition | **Delete** |
| `routers/node_proxy.py` | Filename + path imply HTTP routes; no `APIRouter`, no `@router` decorators, no mount in main.py; CLAUDE.md docs it as mounted | **Move to `core/services/node_proxy.py`** (rename, fix 2 imports) |
| `core/services/paperclip_autoprovision.py` (1 caller) | Single function, 60 lines; imports back into `routers.webhooks` | **Inline into the one caller** (`routers/users.py` per its docstring) OR move the webhook helpers out so this module's import graph is forward-edge-only |
| `core/services/_PAPERCLIP_RETRY_KIND` alias | Self-documented as "kept until the next cleanup pass" | **Delete shim, update one import** |
| `core/services/catalog_slice.py` (2 callers) | Pure-functions module, 100 lines, used by `catalog_service.py` and one test | **Inline into `catalog_service.py`** |
| `core/services/catalog_package.py` (3 callers) | Pure-functions module, ~90 lines | **Inline or merge with `catalog_slice.py`** |
| `core/services/service_token.py` (2 callers) | Helper used by `routers/teams/agents.py` and `routers/paperclip_proxy.py` | **Keep** — narrow, focused, JWT-minting needs to be one place |
| `core/services/teams_event_broker_singleton.py` | 30-line module wrapping a global var; documented rationale "avoid circular import via main.py" | **Keep** — the rationale is correct, FastAPI startup wiring otherwise breaks |
| `core/services/paperclip_admin_session.py` (3 callers) | Reasonable size for what it does; consider whether `_admin()` factory in `routers/teams/agents.py:89` belongs here | **Consider hoisting `_admin()` into this module** (cf. Win #6) |
| `routers/webhooks.py:_lookup_owner_email` (line 297) | Re-implementation of `core/services/paperclip_owner_email.lookup_owner_email`, with the latter explicitly documenting itself as the canonical extraction | **Delete router-local copy, point callers at the service** |

## Closing notes

- The 152-test / 112-source ratio is **not** a smell — the tests are real, very few are skipped, and they're spread across `tests/unit` and `tests/integration` cleanly. Test culture is the strongest signal in this codebase that the "vibe coding" framing understates the actual discipline.
- The two biggest sources of complexity are both **feature-driven**, not accidental: (1) the Teams BFF added ~1,200 lines of router + 12 paperclip_* services in a short window, and (2) the dual chat-broker / Stripe-webhook / OpenClaw-RPC pipeline genuinely has three independent failure modes the code has to handle. The fragmentation around catalog_* and the borderline-dead `bedrock_client.py` are the easiest places to claw back simplicity without touching live functionality.
- Recommend running Wins #1, #2, #4, #9, #10 as a single small PR (each is a one-file change with no behavior delta), then Wins #3, #5, #6, #7 as targeted follow-ups.
