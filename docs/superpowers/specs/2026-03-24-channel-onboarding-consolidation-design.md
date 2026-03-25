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

#### `ProvisioningStepper.tsx`
- Replace `ChannelSetupStep` import with `ChannelCards` and `isChannelCardsDismissed`
- Initialize `onboardingComplete` from `isChannelCardsDismissed()` so dismissal persists across page refreshes
- Phase `"channels"` renders `<ChannelCards onDismiss={() => setOnboardingComplete(true)} />`
- Remove the `localStorage.setItem` workaround added in the previous fix (ChannelCards manages its own localStorage key internally)

#### `AgentChatWindow.tsx`
- Remove `showChannelCards` state
- Remove `ChannelCards` and `isChannelCardsDismissed` imports
- Remove the `ChannelCards` conditional render block

#### `ChannelSetupStep.tsx`
- Deleted entirely

#### `ChannelCards.tsx`
- No changes. Already has the correct API (`onDismiss` prop, `isChannelCardsDismissed()` export, localStorage key `isol8:channel-cards-dismissed`)

### Files Not Touched
- `ChannelsPanel.tsx` — ongoing management panel, unrelated to onboarding
- All backend files
- All other frontend files

### Data Flow

```
ProvisioningStepper
  phase: "channels"  (gateway healthy + no channels connected + not dismissed)
    └── <ChannelCards onDismiss={() => setOnboardingComplete(true)} />
          └── on dismiss: sets localStorage("isol8:channel-cards-dismissed", "true")
                          calls onDismiss → setOnboardingComplete(true)
                          → phase becomes "ready" → renders children

  phase: "ready"  (onboardingComplete || anyConnected || channelsError)
    └── renders children (AgentChatWindow, no ChannelCards overlay)
```

### Persistence

`onboardingComplete` is initialized as `useState(() => isChannelCardsDismissed())`. On subsequent page loads, if the user previously dismissed the cards, `onboardingComplete` starts as `true` and the channel phase is skipped immediately.

## Out of Scope

- Deduplication of WhatsApp QR logic between `ChannelSetupStep` and `ChannelsPanel` (ChannelSetupStep is being deleted, so this is resolved on one side automatically)
- Any changes to `ChannelsPanel` (ongoing management, separate concern)
