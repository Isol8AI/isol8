# Channel Onboarding Consolidation Design

**Date:** 2026-03-24
**Status:** Approved

## Problem

There are two separate channel onboarding flows shown sequentially to new users:

1. `ChannelSetupStep` — rendered by `ProvisioningStepper` during the `"channels"` phase (accordion UI, no step-by-step instructions)
2. `ChannelCards` — rendered as an overlay in `AgentChatWindow` after provisioning completes (card grid UI, has step-by-step instructions, localStorage dismiss)

This causes new users to see the channel setup prompt twice in a single session. The two components also duplicate the same logic: channel field definitions, WhatsApp QR flow, `config.patch` + gateway poll.

## Goal

Single channel onboarding flow. `ChannelCards` is the better UI (card grid, per-channel instructions, animated dismiss) and becomes the only onboarding surface. `ChannelSetupStep` is deleted.

## Design

### Component Ownership

`ProvisioningStepper` owns channel onboarding via the `"channels"` phase. `AgentChatWindow` has no channel onboarding responsibility.

### Changes

#### `ChannelCards.tsx` (requires fixes before it can replace ChannelSetupStep)

Two bugs must be fixed — `ChannelCards` was previously shown after provisioning where WhatsApp was already enabled. In the new position (during provisioning), it handles brand-new users where WhatsApp may not yet be enabled in `openclaw.json`.

**Fix 1 — WhatsApp enable/poll step:**
`ChannelCards.handleWhatsAppQr` currently calls `web.login.start` directly. It must first check if `whatsapp.enabled` is true in the config snapshot, and if not: call `config.patch` to enable it, then poll `config.get` until the gateway restarts (max 20s, poll every 1.5s) before calling `web.login.start`. This logic exists in `ChannelSetupStep` (lines 231–257) and must be ported to `ChannelCards`.

**Fix 2 — Per-call RPC timeouts:**
`ChannelCards` calls `callRpc("web.login.start", {...})` and `callRpc("web.login.wait", {...})` with no frontend timeout argument. These must pass explicit timeouts matching `ChannelSetupStep`:
- `web.login.start`: `callRpc("web.login.start", { force: waLoginFailed, timeoutMs: 30000 }, 60000)`
- `web.login.wait`: `callRpc("web.login.wait", { timeoutMs: 120000 }, 130000)`

This matches the fix applied to `ChannelsPanel` (see commit `fix: add per-call RPC timeout`).

#### `ProvisioningStepper.tsx`

- Replace `ChannelSetupStep` import with `ChannelCards` and `isChannelCardsDismissed`
- Initialize `onboardingComplete` from localStorage to persist dismissal across refreshes. Use `useEffect` (not lazy `useState` initializer) to avoid SSR hydration mismatch:
  ```tsx
  const [onboardingComplete, setOnboardingComplete] = useState(false);
  useEffect(() => {
    if (isChannelCardsDismissed()) setOnboardingComplete(true);
  }, []);
  ```
- Phase `"channels"` renders `<ChannelCards onDismiss={() => setOnboardingComplete(true)} />` — remove the `max-w-sm` wrapper div; use `flex-1 flex items-center justify-center p-6` only, letting `ChannelCards` control its own width (`max-w-3xl`)
- Remove the `localStorage.setItem` workaround added in a prior fix (ChannelCards manages its own localStorage key internally via `handleDismiss`)

#### `AgentChatWindow.tsx`

- Remove `showChannelCards` state
- Remove `ChannelCards` and `isChannelCardsDismissed` imports
- Remove the `ChannelCards` conditional render block

#### `ChannelSetupStep.tsx`

- Deleted entirely

### Files Not Touched

- `ChannelsPanel.tsx` — ongoing management panel, unrelated to onboarding
- All backend files
- All other frontend files

### Data Flow

```
ProvisioningStepper
  phase: "payment"   → not subscribed
  phase: "container" → subscribed, container not ready
  phase: "gateway"   → container ready, gateway not healthy (or channels.status not loaded)
  phase: "channels"  → gateway healthy + channels.status loaded + no channels connected + not dismissed
    └── <ChannelCards onDismiss={() => setOnboardingComplete(true)} />
          └── on dismiss: sets localStorage("isol8:channel-cards-dismissed", "true")
                          calls onDismiss → setOnboardingComplete(true)
                          → phase becomes "ready"
  phase: "ready"     → containerReady && gatewayHealth &&
                        (onboardingComplete || anyConnected || channelsError)
    └── renders children (AgentChatWindow, no ChannelCards overlay)
```

Note: `"ready"` always requires `containerReady && gatewayHealth` — `onboardingComplete` alone does not skip the container/gateway phases.

### Persistence & SSR

`isChannelCardsDismissed()` includes an SSR guard (`typeof window === "undefined" → true`). To avoid a hydration mismatch if `useState` were initialized from it directly, the dismissed state is read in a `useEffect` instead. This means on first render the `useEffect` has not yet run, so `onboardingComplete` is briefly `false`.

In practice, no flicker occurs for returning users because `channels.status` (with `refreshInterval: 0`) will not be synchronously cached by SWR across page navigations, so the phase stays at `"gateway"` until `channelsData` loads — by which time the `useEffect` has already run and set `onboardingComplete`. Within the same React session (e.g. a component re-mount), SWR may return a cached `channelsData` synchronously, causing a one-frame flash of `ChannelCards` before the `useEffect` fires. This is accepted as a minor known limitation; the fix (reading localStorage synchronously) is not worth the hydration complexity it introduces.

## Out of Scope

- Deduplication of WhatsApp QR logic between `ChannelCards` and `ChannelsPanel` (separate concern, can be addressed independently)
- Any changes to `ChannelsPanel` (ongoing management, separate concern)
