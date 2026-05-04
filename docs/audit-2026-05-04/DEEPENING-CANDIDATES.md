# Deepening Candidates — 2026-05-04

Companion to [SUMMARY.md](SUMMARY.md). Where the SUMMARY ranks tactical wins by ROI, this document ranks **architectural** opportunities — clusters of shallow modules that, if **deepened**, would concentrate **locality** for maintainers and produce more **leverage** at the **interface** for callers and tests.

Vocabulary used per Matt Pocock's `improve-codebase-architecture` skill:
- **Module** — anything with an interface and an implementation.
- **Interface** — everything a caller must know: types, invariants, error modes, ordering, config.
- **Depth** — leverage at the interface; deep = a lot of behaviour behind a small interface.
- **Seam** — where an interface lives; a place behaviour can be altered without editing in place.
- **Adapter** — a concrete thing satisfying an interface at a seam.
- **Leverage** — what callers get from depth.
- **Locality** — what maintainers get from depth.
- **Deletion test** — imagine deleting the module: complexity vanishes (was a pass-through) or reappears across N callers (earned its keep)?
- **One adapter = hypothetical seam; two = real one.** Don't introduce a port unless something actually varies across it.

Note: this repo has no `CONTEXT.md` (domain glossary) or `docs/adr/` (architecture decisions). `CLAUDE.md` partly fills the CONTEXT role. If grilling produces "considered and rejected" decisions, that's where ADRs would be created.

---

## How to use this list

1. Read all eight candidates. They're ranked by my read of impact × tractability, but pick whichever speaks to the friction you actually feel.
2. Pick one to grill. We'll walk constraints, dependencies, what sits behind the seam, what tests survive.
3. If you want to design the new interface deliberately rather than off the cuff, the skill has a "Design It Twice" parallel-sub-agent pattern — three different design constraints, three radically different interfaces, then compare.

---

## 1. The Subscription Access module

**Files involved (current):**
- `apps/backend/core/services/provision_gate.py` (canonical helper, ~110-130)
- `apps/backend/core/gateway/connection_pool.py:1117-1119`
- `apps/backend/routers/config.py:130-131`
- `apps/backend/routers/billing.py:389` (the status predicate) and `:376-387` (the related `_BLOCKED_REPEAT_STATUSES` rule)

**Problem.** "Is this account allowed to use the platform right now?" is one piece of knowledge encoded in **four** places, each with subtle drift. The related "has this account already used their trial?" rule lives in a fifth place. The frontend has its own copies of the same predicate (`isBedrockTier`, the dark-panel gates). Apply the **deletion test**: delete the helper in `provision_gate.py` and the same conditional reappears in three router files — it earns its keep, but the **seam** isn't recognized as a single module. Today there's no module called "subscription access" — only scattered `if status in {...}` checks.

**Solution (plain English).** Give "subscription access" a name and a home. One module that owns every question of the form "what is this account allowed to do right now?" — current status check, repeat-trial check, blocked-status check, and the equivalent of the frontend's `isBedrockTier`. Callers pass an account dict; module returns a typed answer. The four backend sites and the two frontend predicates collapse into calls into this module.

**Benefits.**
- **Locality**: every billing-status decision lives in one file. The next time Stripe adds a status (`paused`, `pending_cancellation`), you fix one place.
- **Leverage**: callers stop having to know the difference between `active`, `trialing`, `has_legacy_sub`, `null-with-stripe-id`. They just ask "can this account use the platform?"
- **Tests**: the **interface is the test surface**. Today these predicates have implicit coverage scattered across billing/config/gateway tests. Concentrating them lets you write one test table that exhausts the state space (every Stripe status × every repeat-trial situation) once, instead of three partial tables.

**Dependency category:** **In-process** — pure computation over a dict. Always deepenable, no adapter needed. The seam is internal to the backend; the frontend gets a parallel pure-function module that mirrors the same predicates (or, better, a single REST endpoint that returns the typed verdict so the rule lives in one language).

---

## 2. The Catalog module collapse

**Files involved:**
- `apps/backend/core/services/catalog_service.py` (504 LOC)
- `apps/backend/core/services/catalog_s3_client.py` (~80 LOC)
- `apps/backend/core/services/catalog_slice.py` (~100 LOC, **2 callers**)
- `apps/backend/core/services/catalog_package.py` (~90 LOC, **3 callers**)

**Problem.** Four modules where two would do. `catalog_slice` and `catalog_package` are pure-function helpers extracted (presumably) for testability — but the **deletion test** says delete them and complexity moves into `catalog_service.py` (one place), it doesn't reappear across N callers. They're shallow modules: their interfaces are nearly as complex as their implementations, and the bugs that matter live in how `catalog_service` orchestrates them, not in the helpers themselves. This is the "pure functions extracted just for testability, but the real bugs hide in how they're called" anti-pattern the skill specifically calls out.

**Solution.** Inline `catalog_slice.py` and `catalog_package.py` into `catalog_service.py`. Keep `catalog_s3_client.py` as the only seam — that's the place a real adapter would swap (LocalStack vs. real S3 vs. an in-memory fake for tests). The result: one deep module owning catalog logic, with one well-placed seam at the I/O boundary.

**Benefits.**
- **Locality**: catalog changes happen in one file instead of three. Code review is a single diff.
- **Leverage**: callers stop having to know the slice/package decomposition (which doesn't matter to them).
- **Tests**: tests target the deepened `catalog_service` interface and exercise the s3 seam with a fake. Old per-helper tests get **replaced, not layered** — write at the deep interface, delete the shallow ones.

**Dependency category:** **True external** for S3 (mock). The s3 client is a real seam — production adapter (boto3) and test adapter (in-memory fake) = two adapters = real seam, not hypothetical.

---

## 3. The `useApi` sole-fetcher

**Files involved:**
- `apps/frontend/src/lib/api.ts` (the existing `useApi`, well-defined)
- `apps/frontend/src/hooks/useBilling.ts:47-110`
- `apps/frontend/src/hooks/useContainerStatus.ts:49`
- `apps/frontend/src/hooks/useProvisioningState.ts:73`
- `apps/frontend/src/hooks/useTeamsApi.ts`
- Plus admin server-side `_actions/adminPost`/`adminFetch` (acceptable parallel because hooks vs server actions can't share a `useApi` hook)

**Problem.** `useApi` is the canonical HTTP module — it owns auth headers, error parsing, `ApiError(status, body)`. Four hooks bypass it and implement the same pipeline by hand, throwing `Error("Failed to fetch")` (no body, no status). The classic shallow-by-duplication situation: each bypass hook is itself thin, but together they make the HTTP **interface** of the frontend non-uniform. Two bugs followed directly: silent error states with no UI feedback, and `useGatewayRpc.ts:42-45` swallowing `"No container"` as `undefined` to "match old behaviour" — a load-bearing contract that has no test.

**Solution.** Make `useApi` the only HTTP entry point. SWR fetcher in each hook becomes `(path) => api.get(path)`. The hooks shrink to "what to fetch / what to do with the result" without re-encoding "how to fetch."

**Benefits.**
- **Locality**: every fetch policy decision (auth header changes, retry logic, error envelope shape, telemetry on failures) is changed in one file.
- **Leverage**: every caller gets `ApiError(status, body)` with the actual server message. Today the bypass paths can't tell "Stripe is down" from "user has no subscription" because both surface as `"Failed to fetch"`.
- **Tests**: one mock at the `useApi` seam covers every hook in test. Today, four mocks (or four real-fetch tests).

**Dependency category:** **True external** (HTTP backend) — but the seam is `useApi` itself. Two adapters: prod (real fetch with Clerk token) and test (in-memory). Already a real seam in spirit; just needs every caller to actually use it.

---

## 4. The Analytics seam

**Files involved:**
- `apps/frontend/src/lib/analytics.ts` (exists, has a `capture()` wrapper)
- `apps/frontend/src/components/providers/PostHogProvider.tsx`
- 14 components that import `usePostHog()` directly and call `posthog?.capture(...)`

**Problem.** `lib/analytics.ts` was created to be the analytics seam — and is then bypassed in 14 places. Apply the **deletion test**: delete `lib/analytics.ts` today and nothing changes (it has almost no callers). This is a hypothetical seam pretending to be a real one. Meanwhile, "switch analytics provider" or "stop sending events from a specific page" or "add a global property to every event" requires touching 14 files.

**Solution.** Move every `posthog?.capture` call to `lib/analytics.capture(event, props)`. Components stop knowing PostHog exists. The Provider stays at the React tree root; the call sites use the wrapper.

**Benefits.**
- **Locality**: every analytics decision (sampling, redaction, environment guards, switching to PostHog v2 or to a different SDK) is made in one file.
- **Leverage**: callers express "track this event," not "do I have a posthog instance? if so, capture."
- **Tests**: analytics becomes mockable at one seam. Today, components that do `usePostHog()?.capture(...)` are hard to assert on without instrumenting PostHog itself.

**Dependency category:** **True external** (PostHog). Two adapters justified: prod (PostHog SDK) and test (record-to-array fake) = real seam.

---

## 5. The Clerk-admin module completion

**Files involved:**
- `apps/backend/core/services/clerk_admin.py` (already exists; its docstring at lines 7-10 explicitly names the bypass sites)
- `apps/backend/routers/billing.py:34-53` (`_resolve_clerk_user` — its own `httpx.AsyncClient`)
- `apps/backend/routers/desktop_auth.py:22-58` (`create_sign_in_token` — its own `httpx.AsyncClient`)

**Problem.** `clerk_admin` is the canonical seam for Clerk REST. Two routers bypass it. The module's own docstring says "I exist to absorb these duplicated calls" and then the calls were never moved. Same hypothetical-vs-real-seam pattern as candidate #4. Compounding: one of the bypass sites (`routers/billing.py:51-53`) silently swallows Clerk failures into `{}`, so the caller can't tell "user has no Clerk record" from "Clerk is down."

**Solution.** Add `get_user(user_id)` and `create_sign_in_token(user_id)` to `clerk_admin`. Switch the two routers to use them. Replace the bare `except Exception: pass` with a typed exception that the caller can choose to handle.

**Benefits.**
- **Locality**: every Clerk REST decision (which fields to fetch, error handling, JWKS caching, rate-limit handling) is in one file.
- **Leverage**: routers ask "give me this user" and get a typed result or a typed exception. They stop knowing Clerk's URL scheme exists.
- **Tests**: Clerk mockable at one seam.

**Dependency category:** **True external** (Clerk). Two adapters: prod httpx and test fake = real seam.

---

## 6. The Stripe boundary tightening

**Files involved:**
- `apps/backend/core/services/billing_service.py` (exists; hides Stripe for happy paths)
- `apps/backend/routers/billing.py` — calls `stripe.Subscription.retrieve` (line 402), references `stripe.error.InvalidRequestError` (line 403)
- `apps/backend/routers/webhooks.py:746-753` — calls `stripe.Customer.modify`
- `apps/backend/routers/billing.py:566` — calls `stripe.Webhook.construct_event` (this one is OK to keep at the router boundary; it's a request-shape verification, not a Stripe operation)

**Problem.** `BillingService` is the deep module for Stripe — except where it isn't. Two routers reach past the interface for specific Stripe operations the service doesn't expose yet. The current state is the worst case: callers can't tell whether to use `BillingService` or hit Stripe directly because the answer is "depends which operation." The interface is leaky, which means every reader has to learn both Stripe AND `BillingService`.

**Solution.** Extend `BillingService`'s interface to cover the missing operations (`get_subscription(id)`, `update_customer_email(id, email)`, `parse_stripe_error(e) -> typed`). Move the calls in. Keep `Webhook.construct_event` at the router boundary as the explicit exception with a comment explaining why (signature verification on the raw request body).

**Benefits.**
- **Locality**: every Stripe call is in one file. Easier to audit, easier to add idempotency keys (per project memory `feedback_stripe_idempotency_with_stable_keys.md`), easier to add test mode toggles.
- **Leverage**: routers express billing intent ("renew this subscription") not Stripe mechanics ("call this SDK method with this shape").
- **Tests**: one Stripe mock at the `BillingService` seam covers everything except webhook signature verification. Today, three mocks.

**Dependency category:** **True external** (Stripe). Two adapters: prod stripe SDK and test fake = real seam.

---

## 7. The DynamoDB ownership consolidation

**Files involved:**
- `apps/backend/core/dynamodb.get_table` (the canonical helper)
- `apps/backend/core/services/connection_service.py:59` (own boto3 client)
- `apps/backend/core/services/oauth_service.py:88-92` (own `_table()` factory)
- `apps/backend/core/services/credit_ledger.py:46-49` (own `_balance_table()` factory)
- `apps/backend/core/services/webhook_dedup.py:51-54` (own `_table()` factory)
- (`bedrock_client.py:27` — caught by deletion in PR 1)

**Problem.** Three services reinvent the same `boto3.resource("dynamodb").Table(name)` factory. Each is tiny, but together they represent four places to patch when you want to add a region override or LocalStack endpoint URL. The deletion test on `core/dynamodb.get_table` says: delete it, complexity reappears in 17+ other files (the repositories) — it earns its keep. The four bypass services are the broken windows on a working pattern.

**Solution.** Promote `connection_service`, `oauth_service`, `credit_ledger` to `repositories/` (matching the existing 9 repos) — they're CRUD wrappers with no service-layer logic. Use `core/dynamodb.get_table`. `webhook_dedup` is borderline (it's idempotency state, sits in services for now), but at minimum should call `get_table` instead of its own factory.

**Benefits.**
- **Locality**: every DynamoDB endpoint/region/credentials decision in `core/dynamodb`. Today, five places.
- **Leverage**: services that bypass dynamodb today are forced to know about boto3 client construction. Routing through `get_table` shrinks them to "what table, what query."
- **Tests**: LocalStack endpoint already configured in `core/dynamodb`; bypass services may or may not pick it up depending on how their tests run.

**Dependency category:** **Local-substitutable** (LocalStack/moto). Internal seam — no port at the external interface, just the existing helper used consistently.

---

## 8. The ChatLayout onboarding-gate extraction

**Files involved:**
- `apps/frontend/src/components/chat/ChatLayout.tsx` (529 LOC; the god-component of the chat shell)

**Problem.** ChatLayout reaches into Clerk × 4 hooks, `useGateway`, `useApi`, `useAgents`, `useBilling`, `useRouter`, `useSearchParams`, plus 9 other components. It owns onboarding routing, post-checkout polling, agent dispatch, sidebar UI, and the `dispatchSelectAgentEvent` window event. Apply the deletion test: hard, because state is interleaved. That's the signal — the **interface** of the component is "everything in the app." It has no depth because it has no real interface.

The lowest-risk extraction the frontend audit identified: lines 105-165 are an onboarding-gate state machine ("loading | redirect-onboarding | auto-activate | ready") that could be its own hook.

**Solution.** Extract `useOnboardingGate(): "loading" | "redirect-onboarding" | "auto-activate" | "ready"`. The hook owns the decision logic across Clerk membership state, billing status, container provisioning state, and search params. ChatLayout consumes the result and renders.

**Benefits.**
- **Locality**: onboarding routing logic in one file. Today, interleaved with rendering.
- **Leverage**: callers (currently just ChatLayout, but the admin/teams shells could benefit too) ask "what's this user's onboarding state?" without knowing the inputs.
- **Tests**: this is the big one. Onboarding gate logic is currently untestable without rendering ChatLayout end-to-end. Extracted hook is testable in isolation with mocked Clerk/billing/gateway state.

**Dependency category:** **In-process** — pure computation over hook results. Always deepenable. The seam is internal (a hook composing other hooks). No new adapters.

---

## Summary table

| # | Candidate | Worst symptom today | Dep category | Risk |
|---|---|---|---|---|
| 1 | Subscription Access module | One predicate in 4+ files; next bug is "we updated 3 of 4 sites" | In-process | Medium (touches gating logic) |
| 2 | Catalog module collapse | Pure-function helpers with single callers, 2 import hops per change | True external (S3) | Low |
| 3 | `useApi` sole-fetcher | 4 hooks throw `Error("Failed to fetch")` instead of `ApiError(status, body)` | True external (HTTP) | Medium (surfaces real errors that were swallowed) |
| 4 | Analytics seam | `lib/analytics.ts` exists and is bypassed in 14 components | True external (PostHog) | Low |
| 5 | Clerk admin completion | Module's own docstring names the bypass sites; bypass swallows failures | True external (Clerk) | Low |
| 6 | Stripe boundary | `BillingService` exists but is leaky; routers call `stripe.*` directly | True external (Stripe) | Medium |
| 7 | DynamoDB ownership | 3-5 services reinvent the table factory | Local-substitutable | Low |
| 8 | ChatLayout onboarding-gate | 529-LOC god-component, untestable in isolation | In-process | Low (extraction only, no behavior change) |

---

## My recommendation

The two highest-leverage candidates by my read:

**#1 (Subscription Access)** because the bug it prevents is exactly the kind that costs a customer trust — a billing-state-mismatch where the gateway lets the user in, the config router blocks them, or vice versa. The four-site predicate is a future-incident generator. Tractable: in-process, no external dependencies, the canonical helper already exists.

**#3 (`useApi` sole-fetcher)** because it's the entry point for *every* future bug-fix in the chat-billing-provisioning flow. Today, when something goes wrong in those flows, the user sees `"Failed to fetch"` and the developer sees the same — the structured error from the backend is being thrown away. Fixing this once unlocks better debugging on every future bug in the four bypass hooks.

Pick one (or any other that matches the friction you actually feel), and we can grill — walk constraints, dependencies, what sits behind the seam, what tests survive. Or, if the candidate is interface-shaped enough that "what should the new interface look like?" is the interesting question, the skill has a parallel-sub-agent design pattern for exploring 3+ radically different interfaces in one shot.
