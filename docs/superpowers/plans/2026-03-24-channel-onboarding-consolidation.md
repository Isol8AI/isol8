# Channel Onboarding Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two-step channel onboarding (ChannelSetupStep → ChannelCards) with a single flow using ChannelCards inside ProvisioningStepper.

**Architecture:** ProvisioningStepper owns channel onboarding via its `"channels"` phase. ChannelCards is fixed to handle brand-new users (WhatsApp not yet enabled) and moved into ProvisioningStepper. AgentChatWindow is stripped of its ChannelCards overlay. ChannelSetupStep is deleted.

**Tech Stack:** Next.js 16 App Router, React 19, TypeScript, SWR (`useGatewayRpc`/`useGatewayRpcMutation`)

**Spec:** `docs/superpowers/specs/2026-03-24-channel-onboarding-consolidation-design.md`

---

## File Map

| Action | File |
|--------|------|
| Modify | `apps/frontend/src/components/chat/ChannelCards.tsx` |
| Modify | `apps/frontend/src/components/chat/ProvisioningStepper.tsx` |
| Modify | `apps/frontend/src/components/chat/AgentChatWindow.tsx` |
| Delete | `apps/frontend/src/components/chat/ChannelSetupStep.tsx` |
| Delete | `apps/frontend/src/__tests__/ChannelSetupStep.test.tsx` |

---

## Task 1: Fix ChannelCards WhatsApp — enable plugin + per-call RPC timeouts

`ChannelCards` was previously shown after provisioning where WhatsApp was already enabled. Moved to provisioning, it must handle brand-new users where WhatsApp may not be enabled yet in `openclaw.json`. Two bugs to fix in `handleWhatsAppQr` and `handleWhatsAppWait`.

**Files:**
- Modify: `apps/frontend/src/components/chat/ChannelCards.tsx`

- [ ] **Step 1: Replace `handleWhatsAppQr` with the version that enables the plugin first**

Open `ChannelCards.tsx`. Find `handleWhatsAppQr` (around line 253). Replace the entire function with:

```tsx
const handleWhatsAppQr = async () => {
  setWaBusy("qr");
  setWaLoginFailed(false);
  setErrors((prev) => {
    const next = { ...prev };
    delete next["whatsapp"];
    return next;
  });
  try {
    // Enable WhatsApp plugin if not already enabled (required for brand-new users)
    const snapshot = configData as ConfigSnapshot | undefined;
    const waAlreadyEnabled =
      (snapshot?.config as Record<string, unknown> | undefined)?.channels !== undefined &&
      ((snapshot?.config as Record<string, Record<string, unknown>>)
        ?.channels?.["whatsapp"] as { enabled?: boolean } | undefined)?.enabled === true;

    if (!waAlreadyEnabled && snapshot?.hash) {
      setWaMessage("Enabling WhatsApp…");
      await callRpc("config.patch", {
        raw: JSON.stringify({ channels: { whatsapp: { enabled: true, dmPolicy: "pairing" } } }),
        baseHash: snapshot.hash,
      });
      // Poll until the gateway is back up after restarting (max 20s).
      setWaMessage("Waiting for gateway to restart…");
      const pollDeadline = Date.now() + 20_000;
      while (Date.now() < pollDeadline) {
        await new Promise((r) => setTimeout(r, 1500));
        try {
          await callRpc("config.get", undefined);
          break; // Gateway responded — plugin is loaded
        } catch {
          // Still restarting, keep waiting
        }
      }
      setWaMessage(null);
    }

    // Pass a 60s frontend RPC timeout — the 30s OpenClaw-side timeout plus buffer
    const res = await callRpc<WebLoginResult>("web.login.start", {
      force: waLoginFailed,
      timeoutMs: 30000,
    }, 60000);
    setQrDataUrl(res.qrDataUrl ?? null);
    setWaMessage(res.message ?? null);
  } catch (err) {
    setErrors((prev) => ({
      ...prev,
      whatsapp: err instanceof Error ? err.message : String(err),
    }));
    setQrDataUrl(null);
    setWaMessage(null);
  } finally {
    setWaBusy(null);
  }
};
```

- [ ] **Step 2: Add the 130s frontend RPC timeout to `web.login.wait` in `handleWhatsAppWait`**

In `handleWhatsAppWait`, find the `callRpc("web.login.wait", ...)` call (around line 287). Change:

```tsx
const res = await callRpc<WebLoginResult>("web.login.wait", {
  timeoutMs: 120000,
});
```

To:

```tsx
// 130s frontend RPC timeout = 120s OpenClaw wait + 10s network buffer
const res = await callRpc<WebLoginResult>("web.login.wait", {
  timeoutMs: 120000,
}, 130000);
```

- [ ] **Step 3: Run lint to verify no TypeScript errors**

```bash
cd apps/frontend && npm run lint
```

Expected: no errors

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/chat/ChannelCards.tsx
git commit -m "fix: add WhatsApp enable/poll step and RPC timeouts to ChannelCards"
```

---

## Task 2: Update ProvisioningStepper — swap ChannelSetupStep for ChannelCards

**Files:**
- Modify: `apps/frontend/src/components/chat/ProvisioningStepper.tsx`

- [ ] **Step 1: Replace the ChannelSetupStep import with ChannelCards**

At the top of `ProvisioningStepper.tsx`, find:

```tsx
import { ChannelSetupStep } from "@/components/chat/ChannelSetupStep";
```

Replace with:

```tsx
import { ChannelCards, isChannelCardsDismissed } from "@/components/chat/ChannelCards";
```

- [ ] **Step 2: Initialize `onboardingComplete` from localStorage via useEffect**

Find:

```tsx
const [onboardingComplete, setOnboardingComplete] = useState(false);
```

Replace with:

```tsx
const [onboardingComplete, setOnboardingComplete] = useState(false);
useEffect(() => {
  if (isChannelCardsDismissed()) setOnboardingComplete(true);
}, []);
```

(The `useEffect` import is already present in the file.)

- [ ] **Step 3: Swap the "channels" phase render — replace ChannelSetupStep with ChannelCards, fix wrapper**

Find the `phase === "channels"` render block:

```tsx
  // Channel onboarding — shown after gateway is connected for users with no channels
  if (phase === "channels") {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <ChannelSetupStep onComplete={() => {
            localStorage.setItem("isol8:channel-cards-dismissed", "true");
            setOnboardingComplete(true);
          }} />
        </div>
      </div>
    );
  }
```

Replace with:

```tsx
  // Channel onboarding — shown after gateway is connected for users with no channels
  if (phase === "channels") {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <ChannelCards onDismiss={() => setOnboardingComplete(true)} />
      </div>
    );
  }
```

Note: the `max-w-sm` wrapper div is removed. `ChannelCards` manages its own `max-w-3xl` width internally. The `localStorage.setItem` workaround is also removed — `ChannelCards.handleDismiss` already sets the key before calling `onDismiss`.

- [ ] **Step 4: Run lint**

```bash
cd apps/frontend && npm run lint
```

Expected: no errors. If it flags `ChannelSetupStep` as still imported somewhere, re-check step 1.

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/chat/ProvisioningStepper.tsx
git commit -m "feat: move ChannelCards into ProvisioningStepper, remove ChannelSetupStep"
```

---

## Task 3: Update AgentChatWindow — remove ChannelCards overlay

**Files:**
- Modify: `apps/frontend/src/components/chat/AgentChatWindow.tsx`

- [ ] **Step 1: Remove the ChannelCards import**

Find:

```tsx
import { ChannelCards, isChannelCardsDismissed } from "./ChannelCards";
```

Delete the entire line.

- [ ] **Step 2: Remove the `showChannelCards` state**

Find:

```tsx
const [showChannelCards, setShowChannelCards] = useState(() => !isChannelCardsDismissed());
```

Delete the entire line.

- [ ] **Step 3: Remove the ChannelCards overlay render block**

Find and delete this entire block (lines 138–149):

```tsx
  if (isInitialState) {
    // Show channel cards on first visit (one-time onboarding)
    if (showChannelCards) {
      return (
        <div className="flex flex-col h-full bg-background/20">
          <ConnectionStatusBar />
          <div className="flex-1 flex items-center justify-center p-4">
            <ChannelCards onDismiss={() => setShowChannelCards(false)} />
          </div>
        </div>
      );
    }
```

Replace with just the opening of the outer `isInitialState` block (the inner `return` that follows it is unchanged):

```tsx
  if (isInitialState) {
```

- [ ] **Step 4: Run lint**

```bash
cd apps/frontend && npm run lint
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/components/chat/AgentChatWindow.tsx
git commit -m "fix: remove ChannelCards overlay from AgentChatWindow"
```

---

## Task 4: Delete ChannelSetupStep

**Files:**
- Delete: `apps/frontend/src/components/chat/ChannelSetupStep.tsx`
- Delete: `apps/frontend/src/__tests__/ChannelSetupStep.test.tsx`

- [ ] **Step 1: Delete both files**

```bash
rm apps/frontend/src/components/chat/ChannelSetupStep.tsx
rm apps/frontend/src/__tests__/ChannelSetupStep.test.tsx
```

- [ ] **Step 2: Verify no remaining imports**

```bash
grep -r "ChannelSetupStep" apps/frontend/src/
```

Expected: no output. If any file still imports it, fix that import before continuing.

- [ ] **Step 3: Run lint and tests**

```bash
cd apps/frontend && npm run lint && pnpm test
```

Expected: lint clean, all tests pass (the deleted test file is gone, no other tests reference it)

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete ChannelSetupStep — replaced by ChannelCards in ProvisioningStepper"
```

---

## Task 5: Final verification and PR update

- [ ] **Step 1: Run full lint one more time from repo root**

```bash
cd apps/frontend && npm run lint
```

Expected: clean

- [ ] **Step 2: Push and update the existing PR**

```bash
git push origin fix/channel-onboarding-duplicate
```

The existing PR #73 will automatically update with the new commits.

- [ ] **Step 3: Watch CI run to completion**

```bash
gh run list --repo Isol8AI/isol8 --branch fix/channel-onboarding-duplicate --limit 1
```

Copy the run ID from the output, then:

```bash
gh run watch <run-id> --repo Isol8AI/isol8 --exit-status
```

Expected: all checks pass

- [ ] **Step 4: Verify PR on GitHub**

```bash
gh pr view 73 --repo Isol8AI/isol8
```

Confirm the PR diff includes:
- `ChannelCards.tsx` modified (WhatsApp enable/poll + timeouts)
- `ProvisioningStepper.tsx` modified (ChannelCards swap, useEffect, wrapper fix)
- `AgentChatWindow.tsx` modified (overlay removed)
- `ChannelSetupStep.tsx` deleted
- `ChannelSetupStep.test.tsx` deleted
