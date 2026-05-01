# Provider rules + LLM/Credits control-panel redesign

**Date:** 2026-05-01
**Branch (proposed):** `provider-rules-and-control-panels` (off `main`, not on top of the in-flight `trial-frontend-cutover` PR #393)
**Scope:** two adjacent changes shipped together as one PR, three logical commits.

## Context

Two issues showed up while reviewing the post-flat-fee-cutover surface:

1. **ChatGPT OAuth is supposed to be personal-only**, per the 2026-04-30 decision (`memory/project_chatgpt_oauth_personal_only.md`). The decision was made for ToS-compliance reasons (OpenAI Plus terms forbid reselling Plus access; Anthropic banned the equivalent pattern on 2026-04-04, naming OpenClaw as a target). The decision is documented but not enforced — the ProviderPicker still shows all three cards to org users, and `POST /billing/trial-checkout` / `POST /oauth/start` accept `chatgpt_oauth` regardless of org context. Until both halves land, an org admin can route teammates' prompts through their personal ChatGPT account.

2. **The LLM Provider and Credits control panels look unfinished** compared to the rest of the app. They're styled with default Tailwind classes — no warm palette, no card pattern, raw `<input type="number">`, no icons, no status chips. They were added during the flat-fee cutover (commit `e15c41f1 feat(chat,control): trial + out-of-credits banners + LLM/Credits panels`) and never got design polish. Additionally, the Credits panel is shown to all users via the sidebar even though credits only apply to the `bedrock_claude` provider — a `byo_key` or `chatgpt_oauth` user has no credit ledger to manage.

## Goal

- Org users physically cannot pick ChatGPT OAuth (UI hides it; backend rejects it).
- LLM Provider and Credits panels match the visual quality of `UsagePanel` / `ProviderPicker`.
- The Credits sidebar item is hidden from `byo_key` and `chatgpt_oauth` users (they manage billing on the provider's own site).

## Out of scope

- Removing the `/onboarding` Personal/Org choice page — we considered this and decided to leave it as-is. The "extra click" is acceptable for the org-flow minority; restructuring the landing page to encode pod-vs-org introduces a card-based decision that's effectively the onboarding page in a different location.
- Self-serve "Create organization" surface in `/settings`. Future change if needed.
- Any change to `OutOfCreditsBanner` — already correctly gated to `bedrock_claude` (Codex P2 fix on PR #393).
- Any change to the `?provider=` query-string flow on landing's `PricingThreeCard` or in `ProvisioningStepper`. That stays as-is.

## Architecture summary

| Area | File | Change |
|---|---|---|
| Onboarding ProviderPicker | `apps/frontend/src/components/chat/ProvisioningStepper.tsx` | Filter `chatgpt_oauth` card when `isOrg`; adjust header copy + grid columns |
| Trial checkout enforcement | `apps/backend/routers/billing.py` | 403 when `auth.is_org_context && provider_choice == "chatgpt_oauth"` |
| OAuth start enforcement | `apps/backend/routers/oauth.py` (`POST /oauth/chatgpt/start`) | 403 when `auth.is_org_context` |
| Control sidebar | `apps/frontend/src/components/control/ControlSidebar.tsx` | Hide `credits` nav item when `provider_choice !== "bedrock_claude"` |
| Control panel router | `apps/frontend/src/components/control/ControlPanelRouter.tsx` | Active-panel guard: fall back to overview when `panel === "credits"` and user isn't Bedrock |
| LLM Provider panel | `apps/frontend/src/components/control/panels/LLMPanel.tsx` | Hero + summary card redesign |
| Credits panel | `apps/frontend/src/components/control/panels/CreditsPanel.tsx` | Dense card redesign aligned with `UsagePanel` |

Reused utilities (no new dependencies):

- `AuthContext.is_org_context` (`apps/backend/core/auth.py:84`) for the org check.
- `OpenAIIcon`, `AnthropicIcon` from `apps/frontend/src/components/chat/ProviderIcons.tsx` for the LLM hero.
- `useCredits`, `useChatGPTOAuth` hooks already in place.
- The warm palette used in `UsagePanel` (`#faf7f2`, `#1a1a1a`, `#8a8578`, `#e0dbd0`, `#f3efe6`) and the `#06402B` accent used in `ProviderPicker`.
- shadcn `Checkbox` and `Input` (already in `apps/frontend/src/components/ui/`) replacing raw HTML controls in CreditsPanel.

## Section A — Org-only ChatGPT OAuth block

### A.1 Frontend: ProviderPicker filter

`apps/frontend/src/components/chat/ProvisioningStepper.tsx`, function `ProviderPicker` (lines ~840–979). The component already receives `{ isOrg, orgName }`.

**Card filter.** After the existing `cards` array literal:

```ts
const visibleCards = isOrg ? cards.filter((c) => c.id !== "chatgpt_oauth") : cards;
```

Render `visibleCards` instead of `cards`. The `bedrock_claude` card keeps `highlighted: true` in both branches.

**Header copy.** The h2 currently reads `"One price. Three ways to power it."` — change the trailing fragment based on `isOrg`:

```tsx
<h2 className="text-2xl font-semibold tracking-tight text-[#1a1a1a] font-lora">
  One price. {isOrg ? "Two" : "Three"} ways to power it.
</h2>
```

The subhead (`"Pick how ${orgName} wants to pay for inference. The $50/month covers..."`) stays as-is.

**Grid layout.** Currently `grid grid-cols-1 md:grid-cols-3 gap-4`. Change to:

```tsx
<div className={`grid grid-cols-1 gap-4 ${isOrg ? "md:grid-cols-2 max-w-3xl mx-auto" : "md:grid-cols-3"}`}>
```

Two cards center cleanly inside a `max-w-3xl` container instead of leaving an empty column slot.

### A.2 Backend: trial-checkout rejection

`apps/backend/routers/billing.py`, `create_trial_checkout` (line ~260). At the top of the function body, before any Stripe calls:

```python
if body.provider_choice == "chatgpt_oauth" and auth.is_org_context:
    raise HTTPException(
        status_code=403,
        detail="ChatGPT OAuth is not available for organization workspaces. "
               "Use Bring-Your-Own-Key or Powered by Claude instead.",
    )
```

The check happens before the existing "refuse second trial-checkout" idempotency guard (line ~290) so a stale subscription doesn't shadow the org-block error.

### A.3 Backend: oauth/chatgpt/start rejection

`apps/backend/routers/oauth.py` — the router has prefix `/oauth/chatgpt`, so the endpoint is `POST /oauth/chatgpt/start` and the function is `async def start(ctx: AuthContext = Depends(get_current_user))` (around line 41). Reject up front:

```python
if ctx.is_org_context:
    raise HTTPException(
        status_code=403,
        detail="ChatGPT OAuth is not available for organization workspaces.",
    )
```

This is belt-and-suspenders — the trial-checkout block already prevents the user from declaring `chatgpt_oauth` as their provider, but a future code path that calls `oauth/chatgpt/start` outside trial-checkout (for example, a "reconnect" flow) shouldn't bypass the rule.

## Section B — Sidebar gate for the Credits tab

`apps/frontend/src/components/control/ControlSidebar.tsx` currently filters one panel by org-admin status (`ADMIN_ONLY_PANELS`). Add a parallel mechanism for provider-specific panels:

```ts
import useSWR from "swr";
import { useApi } from "@/lib/api";

type UserMeResponse = {
  provider_choice?: "chatgpt_oauth" | "byo_key" | "bedrock_claude";
};

const BEDROCK_ONLY_PANELS = new Set(["credits"]);

export function ControlSidebar({ activePanel, onPanelChange }: ControlSidebarProps) {
  const api = useApi();
  const { membership } = useOrganization();
  const isOrgAdmin = !membership || membership.role === "org:admin";
  const { data: me } = useSWR<UserMeResponse>(
    "/users/me",
    () => api.get("/users/me") as Promise<UserMeResponse>,
  );
  const isBedrockUser = me?.provider_choice === "bedrock_claude";
  // ...
  // In the map:
  if (BEDROCK_ONLY_PANELS.has(key) && !isBedrockUser) return null;
```

The same `/users/me` fetch is already used by `LLMPanel` and `OutOfCreditsBanner`; SWR dedupes the request across all three call sites.

**Loading behavior.** While `me` is undefined, render the Credits item normally — it disappears once provider_choice resolves. This avoids a layout shift in the common case where Credits ends up visible (Bedrock users), and is the same pattern `OutOfCreditsBanner` uses.

**Active-panel safety.** If a user is currently on the `credits` panel and the SWR resolves to a non-Bedrock provider, the panel disappears from the sidebar but the parent's `activePanel === "credits"` still drives `ControlPanelRouter.tsx`. Add a guard there: read the same `/users/me` SWR (cached, so it reuses the sidebar's fetch) and treat `panel === "credits" && provider_choice !== "bedrock_claude"` as a fallback to the overview panel. The router is small (currently 41 lines, lines 22–36 are the static `PANELS` map) — the guard is a single conditional before `const Panel = PANELS[panel] || PANELS.overview`.

## Section C — LLMPanel redesign (hero + summary card)

Pattern: the "Hero + summary cards" used by Vercel/Linear billing pages, scaled to the warm palette this app already uses.

`apps/frontend/src/components/control/panels/LLMPanel.tsx` rewrite:

**Outer container** matches `UsagePanel`: `<div className="p-6 space-y-6">`. Page title `<h2 className="text-lg font-semibold">LLM Provider</h2>` with the same weight/size as Usage's heading.

**Hero card** (full-width, top): `rounded-xl border border-[#e0dbd0] bg-white p-6 flex items-center gap-4`. Left: provider mark in a 48×48 rounded square (`rounded-lg bg-[#f3efe6] flex items-center justify-center`):

| provider_choice | Icon (32px) |
|---|---|
| `chatgpt_oauth` | `<OpenAIIcon size={32} />` (the OpenAI hexagonal flower mark, since "Sign in with ChatGPT" uses the OpenAI account) |
| `byo_key` + `byo_provider === "openai"` | `<OpenAIIcon size={32} />` |
| `byo_key` + `byo_provider === "anthropic"` | `<AnthropicIcon size={32} />` |
| `bedrock_claude` | `<AnthropicIcon size={32} />` (Claude is the underlying model; the "via AWS Bedrock" detail goes in the subtitle) |

Middle: title (`font-medium text-[#1a1a1a]`) + one-line subtitle in `text-sm text-[#8a8578]`. Right: status chip — for `chatgpt_oauth` connected, render `<span className="inline-flex items-center gap-1.5 rounded-full bg-[#06402B]/10 text-[#06402B] px-2 py-0.5 text-xs font-medium"><span className="h-1.5 w-1.5 rounded-full bg-[#06402B]" />Connected</span>`; for `byo_key`, "Active"; for `bedrock_claude`, "Active".

Per provider title/subtitle copy:

| provider_choice | Title | Subtitle |
|---|---|---|
| `chatgpt_oauth` | Sign in with ChatGPT | Inference via your ChatGPT account |
| `byo_key` (openai) | Bring your own OpenAI key | Your key, your billing |
| `byo_key` (anthropic) | Bring your own Anthropic key | Your key, your billing |
| `bedrock_claude` | Powered by Claude | Anthropic Claude via AWS Bedrock |

**Action card** (below hero): `rounded-lg border border-[#e0dbd0] p-4 space-y-3`. Contents per provider:

- `chatgpt_oauth`: small eyebrow label "Account" + plain text "Connected via OAuth" + a `Disconnect` button styled as `rounded-md border border-[#e0dbd0] text-[#1a1a1a] hover:bg-[#f3efe6] px-3 py-1.5 text-sm`.
- `byo_key`: eyebrow label "API key" + the existing `ReplaceKeyForm`, restyled. The `<input>` becomes a shadcn `Input`. The Save button becomes `rounded-full bg-[#06402B] hover:bg-[#0a5c3e] text-white px-4 py-2 text-sm`. Error state preserved (the Codex P2 fix that surfaces the error on submission failure stays).
- `bedrock_claude`: eyebrow label "Billing" + a one-line "Manage your Claude credits and auto-reload settings" + a `Manage credits →` button that calls `onPanelChange?.("credits")` (or pushes `/chat?panel=credits` if the parent doesn't supply that callback).

**Empty state** (`!provider_choice`): a single card matching the action card's styling, with the message "You haven't picked a provider yet" and a CTA `Re-onboard →` linking to `/onboarding`. Do not render the hero card in this state.

**Component file shape.** Keep `LLMPanel` as the single export. Extract per-provider sub-renderers (`<ChatGPTOAuthBlock />`, `<ByoKeyBlock />`, `<BedrockBlock />`) inside the same file so the top-level component stays readable. `ReplaceKeyForm` stays inside the file but is restyled.

**Stale comment cleanup.** The current `LLMPanel.tsx` has a header comment (lines 9–14) noting that `GET /users/me` doesn't exist yet. The endpoint *does* exist — `apps/backend/routers/users.py:80–105` returns `{user_id, provider_choice, byo_provider}`. Delete the stale comment as part of this rewrite.

## Section D — CreditsPanel redesign (dense, UsagePanel-aligned)

`apps/frontend/src/components/control/panels/CreditsPanel.tsx` rewrite:

**Outer container.** `<div className="p-6 space-y-6">`. Page title `<h2 className="text-lg font-semibold">Claude credits</h2>`.

**Balance card.** Top of the panel: `rounded-lg border border-[#e0dbd0] p-4`. Inside, an icon-eyebrow row using the `Wallet` lucide icon at 14px next to a uppercase tracked label `"BALANCE"` (matching the `text-[10px] uppercase tracking-wider text-[#8a8578]/60` style used in UsagePanel's stat blocks). Below: the dollar balance in `text-3xl font-semibold font-mono` (mono so digits align). To the right, a `RefreshCw` lucide icon button (mirroring `UsagePanel`'s refresh affordance) that calls `refresh()` from `useCredits`.

**Add credits card.** `rounded-lg border border-[#e0dbd0] p-4 space-y-3`. Eyebrow `"ADD CREDITS"`. Below: the existing $10/$20/$50/$100 quick-pick row, but each button styled as `rounded-md border px-3 py-1.5 text-sm` with active state `border-[#06402B] bg-[#06402B]/5 text-[#06402B]` (vs default `border-[#e0dbd0] text-[#1a1a1a] hover:bg-[#f3efe6]`). Primary "Add $X" button as `rounded-full bg-[#06402B] hover:bg-[#0a5c3e] text-white px-4 py-2 text-sm`.

**Auto-reload card.** `rounded-lg border border-[#e0dbd0] p-4 space-y-3`. Eyebrow `"AUTO-RELOAD"`. Toggle: shadcn `Checkbox` + label "Automatically top up when balance is low". When enabled, two stacked input rows, each with the eyebrow-label-then-input pattern:

```tsx
<div className="space-y-1">
  <label className="text-[10px] uppercase tracking-wider text-[#8a8578]/60">When balance drops below</label>
  <div className="flex items-center gap-1">
    <span className="text-sm text-[#8a8578]">$</span>
    <Input type="number" min={5} step={5} value={threshold / 100} ... className="w-24" />
  </div>
</div>
```

Save button styled as `rounded-md bg-secondary px-4 py-2 text-sm` (secondary because the dominant action is the green Add Credits button above).

**Removed.** Drop the `pendingTopUpSecret` debug paragraph at the bottom of the current panel — it was a TODO marker noting the missing in-panel Stripe Elements flow. The Stripe Elements wiring is still a follow-up but the debug string shouldn't ship in the new design.

**`useCredits` hook.** No changes — already returns `balance`, `startTopUp`, `setAutoReload`, `refresh`. The redesign is purely presentational.

## Section E — Testing

### Backend (pytest)

In `apps/backend/tests/`:

- `test_billing_trial_checkout.py` (or wherever trial-checkout tests live): add `test_trial_checkout_rejects_chatgpt_oauth_for_org` — build an `AuthContext(user_id="u_x", org_id="org_x")`, call the endpoint with `provider_choice="chatgpt_oauth"`, assert 403 with the expected detail substring "organization workspaces". Also add `test_trial_checkout_allows_byo_key_for_org` and `test_trial_checkout_allows_bedrock_claude_for_org` so the negative-case enforcement can't accidentally widen.
- Personal-context test: `test_trial_checkout_allows_chatgpt_oauth_for_personal` — `AuthContext(user_id="u_x", org_id=None)` with `provider_choice="chatgpt_oauth"` proceeds normally (mock the Stripe call so the test doesn't hit the network).
- `test_oauth_chatgpt_start_rejects_org` — same shape against `POST /oauth/chatgpt/start`; assert 403 when `ctx.is_org_context`. Personal-context counterpart `test_oauth_chatgpt_start_allows_personal`.

### Frontend (vitest + React Testing Library)

In `apps/frontend/src/components/`:

- `chat/ProvisioningStepper.test.tsx` (or new file `ProviderPicker.test.tsx` if cleaner): render `<ProviderPicker isOrg={false} />` and assert all three card titles appear; render `<ProviderPicker isOrg={true} orgName="Acme" />` and assert ChatGPT card is absent, the other two are present, the header reads "Two ways", and the grid wrapper carries `md:grid-cols-2`.
- `control/ControlSidebar.test.tsx`: with SWR mocked to return `{ provider_choice: "byo_key" }`, render the sidebar and assert the Credits item is not in the DOM. With `{ provider_choice: "bedrock_claude" }`, assert it is. With `undefined` (loading), assert it is (loading state shows it).
- `control/panels/LLMPanel.test.tsx`: snapshot-style render for each `provider_choice` value to confirm the right hero + action card render. Re-confirm the existing "save key error surfaces and clears `submitting`" behavior still works on the restyled form.
- `control/panels/CreditsPanel.test.tsx`: render with mocked `useCredits` returning a balance, click a quick-pick, assert active-state styling toggles. Toggle Auto-reload checkbox, assert threshold/amount inputs appear. Click Save, assert `setAutoReload` is called with the right payload.

### Manual smoke (per CLAUDE.md UI-test rule)

1. `pnpm dev` from repo root, sign in as a personal account → `/chat` → ProvisioningStepper provider step → confirm all three cards.
2. Sign out, sign up as an org account, create an org → `/chat` → confirm only two cards (no ChatGPT), header reads "Two ways", grid is centered 2-up.
3. Curl `POST /api/v1/billing/trial-checkout` directly with an org-context JWT and `provider_choice=chatgpt_oauth` → 403.
4. Provision through to ProvisioningStepper, pick `byo_key` → after onboarding, open `/chat`, expand control panel sidebar → confirm Credits item is hidden.
5. Same with `bedrock_claude` → confirm Credits item is visible, the redesigned panel renders, balance card + add credits card + auto-reload card are styled per spec.
6. Same with `chatgpt_oauth` → confirm Credits item hidden, LLM Provider panel shows the hero with a Connected status chip, Disconnect button works.
7. On the LLM Provider panel for `byo_key`, confirm Replace key form save success and save failure both work (the Codex P2 fix is preserved).

## Section F — Implementation order + commits

Single PR, three logical commits in this order so each is independently reviewable and CI-stable:

1. **`feat(billing): block chatgpt_oauth for org workspaces`** — Section A (frontend filter + backend 403s) + the corresponding backend tests + the ProviderPicker test.
2. **`feat(control): hide credits sidebar item for non-bedrock users`** — Section B + the ControlSidebar test + the ControlPanelRouter active-panel safety.
3. **`feat(control): redesign LLM Provider and Credits panels`** — Sections C and D + their unit tests.

Branch `provider-rules-and-control-panels` off `main`. Don't pile onto `trial-frontend-cutover` (PR #393) — it's mid-review and these changes are independent.

## Section G — Risks + open questions

- **OAuth path verified.** `POST /oauth/chatgpt/start` (router prefix `/oauth/chatgpt`, function `start`). No further verification needed.
- **`/users/me` verified.** `apps/backend/routers/users.py:80–105` already returns `{user_id, provider_choice, byo_provider}`. The stale comment in `LLMPanel.tsx` claiming it doesn't exist is dead code and gets removed in Section C.
- **Codex re-flag pattern** (`memory/feedback_codex_reflags.md`). Likely re-flags when the PR opens: (a) "Why isn't there a corresponding test for the personal-context happy path?" — covered, see Section E. (b) "ReplaceKeyForm error state" — preserved, see Section C. (c) "Active-panel safety when Credits tab disappears mid-session" — covered in Section B. Address these inline in the PR description so the dedup loop converges fast.
- **Active subscription pre-existing chatgpt_oauth in an org.** A user who was personal at trial-checkout and later created an org in the same Clerk session would already have `provider_choice = "chatgpt_oauth"` on their user row. The backend 403s only block *future* chatgpt_oauth selections; existing subscriptions keep working until the trial ends or the user reconfigures. This is the right behavior (don't yank service mid-session), but call it out in the PR description so reviewers know it's intentional. A future migration sweep could rebill those users onto Bedrock or BYOK if needed.
