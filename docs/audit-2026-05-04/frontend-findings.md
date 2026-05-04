# Frontend Pragmatic Audit — 2026-05-04

Scope: `apps/frontend/` (Next.js 16 App Router). 225 source files, 70 test files,
8 control panels in the sidebar (5 more reachable only by URL hack), 13 teams
panels, 7 admin sections, landing page with 11 components.

## Scores (0-10 per lens)

- **DRY: 5/10** — `useApi` is well-defined but four hooks (`useBilling`,
  `useContainerStatus`, `useProvisioningState`, `useTeamsApi`) re-implement the
  auth+fetch+error pipeline by hand. `/users/me` is fetched in 3 places with
  the response type re-declared. `Provider` channel-list union exists in 3
  variants (`lib/channels.ts`, `ProvisioningStepper.tsx`, `ActionsPanel.tsx`)
  with WhatsApp inconsistently included. `provider_choice` "treat undefined as
  Bedrock" rule is reimplemented in `ControlSidebar` and `ControlPanelRouter`.
- **Orthogonality: 6/10** — Hook layering is clean
  (`useGateway` → `useGatewayRpc` → `useAgents`/`useAgentChat`/`useSystemHealth`).
  Admin and teams subapps are properly isolated (no cross-imports). But
  `ChatLayout.tsx` (529 lines) reaches into Clerk x4 hooks, `useGateway`,
  `useApi`, `useAgents`, `useBilling`, router, search params — it is the
  god-component of the chat shell.
- **Tracer bullets: 4/10** — `ControlIframe.tsx` is dead (zero imports).
  `ActionsPanel.tsx` is dead (zero imports, not in `ControlPanelRouter`).
  Five panels (`Instances`, `Nodes`, `Config`, `Debug`, `Logs`) are wired into
  the router but never linked from `ControlSidebar` — reachable only via
  `?panel=debug` URL surgery, none touched since 2026-03-15. The
  `useGateway.send` raw fire-and-forget surface has no callers (artifact of
  the deleted scale-to-zero ping). `hooks/index.ts` barrel exports nothing
  anyone imports.
- **Design by contract: 6/10** — `useApi` correctly throws `ApiError` with
  parsed body. Most catches `console.error` and continue; few crash. Two
  troubling silent-fails: `UpdateBanner.fetchUpdates` (`} catch {}` — backend
  endpoint missing is normal, but errors are indistinguishable from rate
  limit), and `MessageList`-side handlers that drop the error. Several catch
  blocks set local state but provide no UI feedback (`AgentOverviewTab` model
  update, `SkillsPanel` install).
- **Broken windows: 7/10** — Only 1 TODO total. Three `any` casts (all
  `(window as any).__TAURI__` in 2 files, justified). One `@ts-expect-error`
  in test only. 32 `console.*` calls in source (mostly justified
  `console.error` in catch blocks). `next.config.ts` excludes
  `@huggingface/transformers` and `onnxruntime-node` from build but neither
  package is in `package.json` — pure stale config. `useGateway.tsx:443`
  and `ActionsPanel.tsx:106` carry stale "free-tier" comments after the
  flat-fee cutover. `ContainerActionsPanel.tsx:16` admin tier dropdown still
  lists `["free", "starter", "pro", "enterprise"]`.
- **Reversibility: 7/10** — One backend URL (`https://api-dev.isol8.co/api/v1`)
  is the env-fallback in `desktop-callback/page.tsx`; everything else routes
  through `BACKEND_URL`/`WS_URL` derivation. PostHog is wrapped in
  `PostHogProvider` and `lib/analytics.ts`, but `usePostHog()` is still pulled
  into 14 components for direct `posthog?.capture(...)` calls — switching
  analytics SDKs would touch every chat/control component. Clerk is similarly
  spread across 22 files (`useAuth`, `useUser`, `useOrganization`,
  `UserButton`) with no thin wrapper.

**Overall: 5.8/10** — Foundations are sound (cleanly layered hooks, isolated
admin/teams subapps, real test coverage on the highest-risk hook
`useAgentChat`). But there is a steady drift of dead code, panels half-wired,
and four hooks that go around the central `useApi` rather than through it.
The flat-fee cutover left several stale plan-tier mentions that haven't been
swept.

## Top 10 Wins (ranked by ROI)

1. **[HIGH]** Delete `ControlIframe.tsx` and `ActionsPanel.tsx` — `apps/frontend/src/components/control/ControlIframe.tsx` and `apps/frontend/src/components/control/panels/ActionsPanel.tsx`. Zero imports each, ~370 lines combined. ActionsPanel still uses the stale `whatsapp` channel name. Surgical fix: `git rm` both files.
2. **[HIGH]** Either link the 5 dark panels in `ControlSidebar` or delete them — `apps/frontend/src/components/control/panels/{InstancesPanel,NodesPanel,ConfigPanel,DebugPanel,LogsPanel}.tsx`. ~660 lines wired into `ControlPanelRouter` but invisible from the sidebar; last touched 2026-03-15. Decision needed: real product feature or cruft? If real, add to `ControlSidebar.NAV_ITEMS`. If not, drop them and the router branches.
3. **[HIGH]** Fix stale tier dropdown — `apps/frontend/src/app/admin/users/[id]/container/ContainerActionsPanel.tsx:16`. `TIERS = ["free", "starter", "pro", "enterprise"]` post-flat-fee. Resize-container action presents tiers that no longer map to backend. Replace with the current single-tier value or pull from backend `/admin/system/health`.
4. **[HIGH]** Route `useBilling`, `useContainerStatus`, `useProvisioningState` through `useApi` — three hooks reimplement auth+fetch+error. The DRY violation is a contract trap: `useApi` throws `ApiError(status, body)`; these throw `Error("Failed to fetch")` with no body. Switch each `await fetch(\`${BACKEND_URL}…\`)` to `api.get(path)`.
5. **[MED]** Centralize the "current user provider" hook — `apps/frontend/src/components/chat/OutOfCreditsBanner.tsx:17`, `apps/frontend/src/components/control/ControlSidebar.tsx:54`, `apps/frontend/src/components/control/ControlPanelRouter.tsx:48`. Same `useSWR("/users/me")` + same `UserMeResponse` type re-declared. Extract `useCurrentUser()` in `src/hooks/`. SWR dedupes the request, so this is just for the type + the "treat undefined as Bedrock" predicate.
6. **[MED]** Remove dead `next.config.ts` exclusions — `apps/frontend/next.config.ts:63-80`. Excludes `@huggingface/transformers` and `onnxruntime-node` from output tracing/bundling, but neither is in `package.json`. Either re-add the packages (if client-side inference is on the roadmap) or strip the dead webpack config.
7. **[MED]** Sweep stale "free-tier" / scale-to-zero comments — `apps/frontend/src/hooks/useGateway.tsx:442-444`, `apps/frontend/src/components/control/panels/ActionsPanel.tsx:106` (going away with #1). Delete or rewrite to reflect the trial-cutover model. Per project memory `feedback_scale_to_zero_design.md` the feature is gone.
8. **[MED]** Drop the dead `useGateway.send` raw send method — `apps/frontend/src/hooks/useGateway.tsx:89,445,476-477`. Exposed in the context type but no caller. Was the entry point for `useActivityPing`. Cuts the surface area of a 497-line hook.
9. **[LOW]** Consolidate the `Provider` channel-type union — `apps/frontend/src/lib/channels.ts:10` declares `"telegram" | "discord" | "slack"`; `apps/frontend/src/components/chat/ProvisioningStepper.tsx:63` redeclares the same; `apps/frontend/src/components/control/panels/ActionsPanel.tsx:31-55` uses `"telegram" | "discord" | "whatsapp"`. Pick one. Then re-export `Provider` from `lib/channels.ts` to ProvisioningStepper.
10. **[LOW]** Delete the unused `hooks/index.ts` barrel — `apps/frontend/src/hooks/index.ts`. Re-exports six hooks; nothing imports `from "@/hooks"` (everyone uses `from "@/hooks/useXxx"`). Removing this prevents the future "should I add my hook to the barrel?" decision and a few tree-shaking regressions in tests.

## Detailed Findings

### DRY

- **HIGH** — `apps/frontend/src/hooks/useBilling.ts:47-110`, `useContainerStatus.ts:49`, `useProvisioningState.ts:73`, `useTeamsApi.ts`. Each builds its own `await fetch(\`${BACKEND_URL}${url}\`)` + token + error handling. The shared `useApi()` already does this and surfaces structured `ApiError(status, body)`; bypassing it loses the `body` / `detail` parse. Fix: route every hook fetch through `api.get/post/etc.`. SWR fetcher becomes `(path) => api.get(path)`.
- **MED** — `/users/me` SWR fetch duplicated in `OutOfCreditsBanner.tsx`, `ControlSidebar.tsx`, `ControlPanelRouter.tsx` with `UserMeResponse` re-declared three times. Same key dedupes the network call but the type drift is real (`ControlSidebar` adds `byo_provider`; the others don't). Extract a `useCurrentUser()` hook returning a typed object.
- **MED** — `/billing/account` SWR fetched in both `useBilling.ts:69` and `TrialBanner.tsx:40` with overlapping but slightly different `BillingAccount` types (`TrialBanner` adds `subscription_status`, `trial_end` that `useBilling`'s type omits). `TrialBanner` should consume `useBilling()` and read the same field set; today it parallel-fetches the same endpoint with different shape and a 60-second `refreshInterval`.
- **MED** — `provider_choice === "bedrock_claude"` predicate (with the "undefined treats as Bedrock" tolerance) duplicated at `ControlSidebar.tsx:61` and `ControlPanelRouter.tsx:58`. Centralize as `function isBedrockTier(me): boolean` in `lib/` (or on the `useCurrentUser` hook above).
- **MED** — `isOrgAdmin = !membership || membership.role === "org:admin"` repeated in `ControlSidebar.tsx:52`, `UsagePanel.tsx:31`, `AgentChatWindow.tsx:59` (subtly different — no `!membership` shortcut), `ProvisioningStepper.tsx:192`, `settings/page.tsx:150`. Extract `useIsOrgAdmin()`.
- **LOW** — `Provider` channel-type union triplicated; `ActionsPanel` (dead) uses `whatsapp` instead of `slack`. See win #9.
- **LOW** — `ConfigSnapshot` shape (`raw`/`config`/`hash`/`valid`) is re-declared inline in `ActionsPanel.tsx:21-27` and `ConfigPanel.tsx`. Once dead code is purged this collapses; otherwise extract to a shared types file.

### Orthogonality

- **MED** — `ChatLayout.tsx` (529 lines) imports from Clerk x4 hooks, useGateway, useApi, useAgents, useBilling, router, search params, and 9 other components. It owns onboarding routing, post-checkout polling, agent dispatch, sidebar UI, and the `dispatchSelectAgentEvent` window event. Splitting is non-trivial (state is interleaved); at minimum, extract the `OnboardingGate` block (lines 105-165) into `useOnboardingGate(): "loading" | "redirect-onboarding" | "auto-activate" | "ready"` so the rendering body shrinks.
- **MED** — `AgentChatWindow.tsx` mixes the chat surface, `UpdateBanner` (own SWR loop on `/container/updates`), and orchestration of `useGateway`/`useAgentChat`/`useApi`/`useAgents`. The `UpdateBanner` could be extracted to `components/chat/UpdateBanner.tsx` and the parent shrinks ~130 lines.
- **OK** — Hook layering: `useGateway` (Clerk + WS_URL only) → `useGatewayRpc` (uses `useGateway`) → `useAgents` (uses `useGatewayRpc`) → `useAgentChat` (uses `useGateway` directly for sendChat plus `useGatewayRpc` for history). Linear, no cycles. `useSystemHealth` correctly composes the three lower-level hooks.
- **OK** — Admin (`src/app/admin/`, `src/components/admin/`) and Teams (`src/app/teams/`, `src/components/teams/`) subapps don't import from chat/control or vice versa. Clean boundary.

### Tracer bullets / dead code

- **HIGH** — `ControlIframe.tsx`. Imports `BACKEND_URL`, builds an iframe URL with the Clerk token in the query string. Zero imports. The OpenClaw control-ui SPA mentioned in `CLAUDE.md` is no longer iframe-embedded. Delete.
- **HIGH** — `ActionsPanel.tsx`. Channel pairing UI for Telegram/Discord/WhatsApp. Not in `ControlPanelRouter.PANELS`. The pairing flow lives in `BotSetupWizard` + `MyChannelsSection` now. Delete.
- **HIGH** — Five "dark panels" in `ControlPanelRouter` (`instances`, `nodes`, `config`, `debug`, `logs`) reachable only via `?panel=debug` URL hack. Last commit on each: 2026-03-15 (initial monorepo split). Either link them in `ControlSidebar.NAV_ITEMS` (with admin/dev gating where appropriate) or remove the router entries + files.
- **MED** — `useGateway.send` raw send method exposed in the context type (`useGateway.tsx:89,445`) but unused. Was the entry point for the deleted `useActivityPing` hook (memory `feedback_scale_to_zero_design.md`). Drop.
- **MED** — `hooks/index.ts` barrel — exports `useAgents`, `useAgentChat`, `useBilling`, `useContainerStatus`, `GatewayProvider`, `useGateway`, `useGatewayRpc`, `useGatewayRpcMutation` but nothing imports from `@/hooks`. Drop.
- **MED** — `ChatLayout.tsx:36` `dispatchSelectAgentEvent(agentId)` window CustomEvent — used by who? Search: `selectAgent` listener is in `app/chat/page.tsx`. Real usage but bypasses prop drilling for one parent → child relationship. Worth noting; not a fix in this audit.
- **LOW** — `next.config.ts` ML exclusions for absent packages (`@huggingface/transformers`, `onnxruntime-node`). Stale.

### Design by contract

- **MED** — `AgentChatWindow.tsx:69` `} catch { /* Endpoint may not exist yet */ }` — silently drops both "endpoint not deployed" and a real 500/timeout. Pattern recurs in `useGateway.tsx:370` (`tauri.core.invoke(...).catch(() => {})`). When the only signal of breakage is a missing UI element, debugging gets harder. Fix: log the error with `posthog?.captureException` and a one-line `if (status === 404) return; throw`.
- **MED** — `AgentOverviewTab.tsx:57-59` model-update catch: `console.error("Failed to update model:", msg)` then no UI change. The dropdown will appear to "stick" at the new value but the backend rejected it. Add a toast or revert local state.
- **MED** — `useGatewayRpc.ts:42-45` swallows `"No container"` errors as `undefined`. Comment says "match old behavior" but the contract is now load-bearing — tests don't pin it. Add a unit test against `useGatewayRpc` (currently zero tests for it).
- **MED** — `useApi.uploadFiles` does `errorData.detail || "Upload failed"` but throws `new Error(...)`, not `ApiError`. Inconsistent with the rest of `useApi`. Switch to `ApiError`.
- **OK** — `useApi.authenticatedFetch` correctly preserves response body via `ApiError(status, body, message)` — most callers can switch on `err.body`.

### Broken windows

- **OK** — Only 1 TODO in source: `ProvisioningStepper.tsx:49` (`TODO(cold-start-signals)`). No FIXME/XXX/HACK.
- **OK** — 32 `console.*` calls; almost all are intentional `console.error` in catch blocks. The two `console.log("[catalog deploy]"...)` (`ChatLayout.tsx:404`) and the `[desktop-auth]` traces (`useDesktopAuth.ts`) are dev-noise; consider gating on `process.env.NODE_ENV !== "production"`.
- **OK** — 3 `any` casts, all `(window as any).__TAURI__` for the desktop-app feature detection. Justified.
- **HIGH** — Stale tier strings post-flat-fee cutover:
  - `ContainerActionsPanel.tsx:16` `TIERS = ["free", "starter", "pro", "enterprise"]`
  - `useGateway.tsx:443` "free-tier scale-to-zero reaper" comment
  - `ActionsPanel.tsx:106` "free-tier-channels" comment (going away with delete)
- **MED** — `next.config.ts` carries 18 lines of webpack/tracing config for packages that aren't installed.
- **LOW** — `ScrollManager.tsx:35` `console.log` is the intentional landing-page easter egg; leave alone.

### Reversibility

- **MED** — Clerk SDK calls scattered across 22 source files. There is no thin internal wrapper; ripping out Clerk would touch every chat/control panel that gates on `membership.role`. Not urgent (we use Clerk deeply), but worth noting that "switch identity provider" is a major refactor today.
- **MED** — PostHog: `usePostHog()` direct in 14 components (`posthog?.capture(...)`). `lib/analytics.ts` exists with a `capture()` wrapper but most components prefer the React hook. Consolidate on `lib/analytics.capture()` so a single grep can find every analytics call site.
- **LOW** — `desktop-callback/page.tsx:6` hard-codes `https://api-dev.isol8.co/api/v1` as the env fallback — only place in src. Pull from `BACKEND_URL` (this page already runs as a client-rendered Next page; it has access).
- **OK** — `BACKEND_URL`/`WS_URL` correctly derived from `NEXT_PUBLIC_API_URL` in `lib/api.ts`. The hostname rewrite (`api → ws`) is well-commented and tested.

## Component Coupling Hotspots (top imports across non-test files)

| Symbol | Files importing |
|---|---|
| `useApi` | 26 |
| `useGatewayRpc` | 25 |
| `useSWR` | 16 |
| `usePostHog` | 14 |
| `@clerk/nextjs.useAuth` | 13 |
| `useGateway` | 11 |
| `next/navigation.useRouter` | 10 |
| `useBilling` | 10 |
| `useAgents` | 8 |
| `@clerk/nextjs.useOrganization` | 7 |

The 22 files importing from `@clerk/nextjs` (any hook) and 14 files using `posthog-js/react` represent the two biggest "vendor lock" surfaces. PostHog is the cheaper one to abstract behind `lib/analytics`; Clerk is intentional.

## Dead/Suspicious Code Inventory

| Path | Why suspicious | Recommendation |
|---|---|---|
| `apps/frontend/src/components/control/ControlIframe.tsx` | Zero imports. Replaced by native panels. | DELETE |
| `apps/frontend/src/components/control/panels/ActionsPanel.tsx` | Zero imports, not in router. | DELETE |
| `apps/frontend/src/components/control/panels/InstancesPanel.tsx` | In router, not in sidebar. Last touched 2026-03-15. | INVESTIGATE then link or delete |
| `apps/frontend/src/components/control/panels/NodesPanel.tsx` | In router, not in sidebar. Last touched 2026-03-15. | INVESTIGATE (desktop node-host status — may be useful for support) |
| `apps/frontend/src/components/control/panels/ConfigPanel.tsx` | In router, not in sidebar. Last touched 2026-03-15. | INVESTIGATE (raw config editor — power-user surface?) |
| `apps/frontend/src/components/control/panels/DebugPanel.tsx` | In router, not in sidebar. Last touched 2026-03-15. | DELETE or move behind admin-only env gate |
| `apps/frontend/src/components/control/panels/LogsPanel.tsx` | In router, not in sidebar. Last touched 2026-03-15. | INVESTIGATE — admin already has `/admin/users/[id]/logs`, this may be redundant |
| `apps/frontend/src/hooks/index.ts` | Barrel re-exports 6 hooks, zero importers. | DELETE |
| `useGateway.send` (`useGateway.tsx:89,445`) | Raw fire-and-forget exposed; no callers since `useActivityPing` was deleted. | DELETE method + context type field |
| `next.config.ts:63-80` ML exclusions | References `@huggingface/transformers` + `onnxruntime-node` not in `package.json`. | DELETE config blocks |
| `ContainerActionsPanel.tsx:16` `TIERS` array | Lists `free/starter/pro/enterprise` post-flat-fee. | UPDATE to current model or read from backend |
| `useGateway.tsx:442-443` comment | Mentions deleted free-tier scale-to-zero. | UPDATE comment (after determining if any caller needs the method) |

## Panel Inventory

### Control Panels (`src/components/control/panels/`)

| Panel | Sidebar? | Router? | Native vs iframe | Last meaningful change | Status |
|---|---|---|---|---|---|
| `OverviewPanel` | yes | yes | native | recent | LIVE |
| `AgentsPanel` (+ `AgentOverviewTab`, `AgentToolsTab`, `AgentCreateForm`, `AgentChannelsSection`) | yes | yes | native | recent | LIVE |
| `SkillsPanel` | yes | yes | native | recent (PR #460s era) | LIVE |
| `SessionsPanel` | yes | yes | native | recent | LIVE |
| `CronPanel` (+ `cron/` subdir) | yes | yes | native | recent | LIVE — only panel with its own subdir, justified by 17 sub-components |
| `UsagePanel` | yes (admin-only) | yes | native | recent | LIVE |
| `LLMPanel` | yes | yes | native | recent (PR #479 trail in router) | LIVE |
| `CreditsPanel` | yes (Bedrock-only) | yes | native | recent | LIVE |
| `InstancesPanel` | NO | yes | native | 2026-03-15 | DARK |
| `NodesPanel` | NO | yes | native | 2026-03-15 | DARK |
| `ConfigPanel` | NO | yes | native | 2026-03-15 | DARK |
| `DebugPanel` | NO | yes | native | 2026-03-15 | DARK |
| `LogsPanel` | NO | yes | native | 2026-03-15 | DARK |
| `ActionsPanel` | NO | NO | native | 2026-03-15 (last commit before initial split) | ORPHAN — delete |
| `McpServersTab` | (subcomponent of `SkillsPanel`) | n/a | native | recent | LIVE |
| `ControlIframe.tsx` (not a panel) | n/a | n/a | iframe (dead) | 2026-04-10 | ORPHAN — delete |

The `cron/` subdirectory is the only intra-panel directory. It's justified — `CronPanel` is genuinely a multi-component sub-app (17 files including pickers, formatters, adapters, types). Other panels stay flat at one file. Pattern is consistent.

### Teams Panels (`src/components/teams/panels/`)

13 panels, all routed via `TeamsPanelRouter` and listed in `TeamsSidebar`.
Coverage: every panel has a `*.test.tsx` under `src/__tests__/teams/`. This is
the best-tested subapp in the frontend.

### Admin Sections (`src/app/admin/`)

Routed by Next.js file-system: `users/`, `users/[id]/{activity,agents,billing,
container,logs,actions}`, `health/`, `catalog/`. Server components + Server
Actions in `_actions/`. Action helpers (`adminPost`/`adminFetch`) duplicate the
pattern in `useApi` but for server-side; this duplication is harder to fix
because `useApi` is a React hook. Acceptable.

## High-risk components missing tests

- `useGateway.tsx` (497 lines, every chat/control feature depends on it) — NO test
- `useBilling.ts` — NO test (despite being the source of truth for the trial banner + checkout flow)
- `AgentChatWindow.tsx` — NO test (the user-facing chat surface)
- `ChatLayout.tsx` — only 1 narrow test (`ChatLayout.teamsLink.test.ts`)
- `useGatewayRpc.ts` — NO test (the SWR-wrapped RPC layer; the `"No container"` swallow at line 42 is a load-bearing contract)

`useAgentChat.ts` HAS a test, which is the right one to have if you only had one.

## Bottom line

Three biggest payoffs:

1. Delete the obvious orphans (`ControlIframe`, `ActionsPanel`, `hooks/index.ts`, dead `next.config.ts` blocks, `useGateway.send`) — ~600 lines, zero risk.
2. Decide what to do with the 5 dark panels — keep them (link in sidebar) or kill them (~660 lines).
3. Route `useBilling`/`useContainerStatus`/`useProvisioningState` through `useApi` so error contracts are consistent across the codebase.

After those three, the frontend health score moves from 5.8 to ~7.5.
