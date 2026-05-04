# Provision Gate UI — Design

Date: 2026-05-03
Status: Draft

## Goal

When `/container/provision` (or `/container/status`) cannot proceed because of a known precondition — no subscription, $0 credits, missing OAuth tokens, etc. — the chat-page centerpiece flips from "Provisioning your container…" to a clear blocked state with the right copy and the right action, and auto-recovers when the gate clears server-side.

A real incident on 2026-05-03 traced to a missed Stripe webhook subscription left admin@isol8.co's prod org with $0 credits. The Bedrock gate returned 402 to ten consecutive provision attempts, the frontend swallowed each 402 and kept polling, and the user saw "Provisioning your container…" for 80 minutes. This design makes that failure mode self-explanatory.

## Non-goals

- Not changing what gates exist or where they're enforced — that's the per-container-provider-choice work (Workstream B).
- Not building a notification system to ping admins when a member is blocked. Plain "ask your admin" text is enough for now.
- Not refactoring the existing onboarding wizard. The same component should also catch this case during onboarding, but onboarding redesign is its own scope.

## Backend contract

### Today

```json
{ "detail": "Top up Claude credits before provisioning" }
```

A free-form string. Frontend has nothing structured to switch on.

### New shape

Returned by both `/container/provision` (POST) and `/container/status` (GET) whenever a gate fails:

```json
{
  "detail": "Top up Claude credits before provisioning",
  "blocked": {
    "code": "credits_required",
    "title": "Top up Claude credits to start your container",
    "message": "Top up some Claude credits to start your Bedrock container.",
    "action": {
      "kind": "link",
      "label": "Top up now",
      "href": "/settings/billing#credits",
      "admin_only": false
    },
    "owner_role": "admin"
  }
}
```

- `code` — switch field. Frontend uses it for copy + recovery condition.
- `title` / `message` — server-rendered so copy changes ship without a frontend deploy.
- `action.admin_only` + `owner_role` — drive the "Top up now" button vs "ask your admin" text branching.
- `detail` — kept for FastAPI-default error rendering of any not-yet-upgraded path.

### Initial code values

| code                  | gate                                                   | who can resolve                                                         |
| --------------------- | ------------------------------------------------------ | ----------------------------------------------------------------------- |
| `subscription_required` | no `stripe_subscription_id` or non-active status      | admin                                                                   |
| `credits_required`    | `bedrock_claude` + balance ≤ 0                         | admin                                                                   |
| `oauth_required`      | `chatgpt_oauth` + no tokens                            | self (in personal context); never reachable in org context after Wkstrm B |
| `payment_past_due`    | subscription status `past_due`                         | admin                                                                   |

### Backend implementation

A new helper `core/services/provision_gate.py` owns the gate logic that today lives in `_assert_provision_allowed` inside `routers/container.py`. The helper returns a structured `Gate` object (or `None` when no gate fires). Both `/container/provision` and `/container/status` call it; routers translate `Gate` into `HTTPException(status_code=..., detail=gate.to_payload())`.

Sharing the helper guarantees provision and status can never disagree about whether a gate is active. `payload()` includes the structured `blocked` field plus a legacy `detail` string for backwards-compat.

## Frontend changes

### Centerpiece state machine

```
   /status load
        |
  +-----+------+
  |   200      | 404                    | 402
  v            v                         v
[normal]   [POST /provision] -- 402 --> [blocked]
                    |  200                ^
                    v                     | (poll /status,
              [normal stepper]            | gate clears → 404 or 200 → [normal])
```

- `200` from `/container/status` → render the existing `ProvisioningStepper`.
- `404` → no container, no gate-block: call `POST /container/provision` (initial create flow).
- `402` → gate is up: render the new `blocked` state.

`POST /provision` also returns the same `blocked` shape on 402 so the initial-create path matches polling.

### `blocked` state rendering

In `ProvisioningStepper.tsx` (and `OnboardingStepper` if it owns its own copy of this surface):

- **Title** = `blocked.title`.
- **Body** = `blocked.message`.
- **Action**:
  - if `action.admin_only && owner_role !== "admin"` — render plain text "Ask your org admin to fix this", no button.
  - otherwise render the action button using `action.label` / `action.href`.
- **Footer buttons** ("Check again" / "Contact support") stay. "Check again" becomes the manual nudge that bypasses backoff.

### Polling cadence

While in `blocked`:

- 5s for the first minute (covers the quick-top-up case).
- 30s thereafter.
- Fixed cadence, no exponential backoff — bounded by the user's actual wait, predictable for support.
- "Check again" resets the cadence to 5s.

### Hooks affected

- `useContainerStatus.ts` — consume the new shape; expose `blocked` cleanly to consumers.
- `useApi.ts` — `get`/`post` should preserve 402 response bodies, not throw on the helper level. Most callers today treat any non-2xx as opaque error; this is a behavior change worth pinning in tests.
- New: `useProvisioningState.ts` — owns the state machine above so `ProvisioningStepper` and any other consumer (admin debug surface, future onboarding rework) don't reimplement it.

## Testing

### Backend (pytest)

- `provision_gate.py` unit tests — each input combination (no sub, past_due, $0 credits + bedrock, etc.) returns the expected `code` and the expected `action.admin_only`.
- Router tests for `/container/provision` and `/container/status` — assert 402 + structured payload shape; 200/404 unchanged when no gate fires.
- Idempotence — hitting `/status` repeatedly with the gate up returns the same `blocked.code` (no first-call/second-call divergence).

### Frontend (vitest + testing-library)

- `useProvisioningState.ts` state machine — every transition (200→normal, 404→provision-then-202, 402→blocked, blocked→200 on next poll → normal). Mock fetch responses.
- `ProvisioningStepper.tsx` snapshot per state. Member-vs-admin role-rendering tests for `admin_only` actions.
- `useApi.ts` — pin that 402 responses preserve the body and don't throw at the helper level.

## Rollout & compatibility

- Backend ships first; frontend after.
- Old frontend keeps working — `blocked` is additive; old code ignores it and renders `detail` via the existing toast path.
- New frontend keeps working against old backend in the small window — if `blocked` is missing on a 402, fall back to legacy "Provisioning your container…" behavior.
- No DB migration. No env var. No feature flag.

### Investigation note

Confirm whether the centerpiece in `ChatLayout` (the "Provisioning your container…" with the key icon) is rendered by `ProvisioningStepper` directly or by a separate component. If separate, the shared `useProvisioningState` hook plugs in with no behavior duplication. Quick grep, not a design fork — resolved during implementation.

## Out of scope

- Anything from Workstream B (provider_choice keying refactor) — even though it would simplify the `oauth_required` story, it's its own design.
- Notification system to ping admins from member screens.
- Changing existing gate logic. If a gate is wrong today, it stays wrong today; this work makes the wrongness visible faster.
