"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePostHog } from "posthog-js/react";
import useSWR from "swr";
import {
  Loader2,
  Zap,
  Crown,
  XCircle,
  CheckCircle,
  Circle,
  AlertTriangle,
} from "lucide-react";
import { useOrganization } from "@clerk/nextjs";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api";
import { useBilling } from "@/hooks/useBilling";
import { useContainerStatus } from "@/hooks/useContainerStatus";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { BotSetupWizard } from "@/components/channels/BotSetupWizard";
import { capture } from "@/lib/analytics";
import { nextOnboardingCompletion } from "@/components/chat/onboardingAnalytics";

type Phase = "payment" | "container" | "gateway" | "channels" | "ready";

type Provider = "telegram" | "discord" | "slack";
const PROVIDER_PRIORITY: readonly Provider[] = ["telegram", "discord", "slack"];

interface BotEntry {
  agent_id: string;
  bot_username: string;
  linked: boolean;
}
interface LinksMeResponse {
  telegram: BotEntry[];
  discord: BotEntry[];
  slack: BotEntry[];
  can_create_bots: boolean;
}

/**
 * Channel onboarding is always scoped to the `main` agent — additional bots
 * on user-created agents are managed in Settings, not here. Returns the first
 * provider (in PROVIDER_PRIORITY order) where a main-agent bot exists that
 * the current member has not yet paired their identity with. Returns null
 * when there's nothing to link (either no main bot configured at all, or the
 * member is already linked to every main bot).
 */
function findFirstUnlinkedMainProvider(links: LinksMeResponse): Provider | null {
  for (const provider of PROVIDER_PRIORITY) {
    const mainBot = links[provider]?.find((b) => b.agent_id === "main");
    if (mainBot && !mainBot.linked) return provider;
  }
  return null;
}

/** True if any provider has a configured main-agent bot. */
function hasMainBot(links: LinksMeResponse): boolean {
  return PROVIDER_PRIORITY.some((p) =>
    links[p]?.some((b) => b.agent_id === "main"),
  );
}

const STEPS_PAID: { phase: Phase; label: string; activeLabel: string }[] = [
  { phase: "payment", label: "Payment confirmed", activeLabel: "Confirming payment..." },
  { phase: "container", label: "Container started", activeLabel: "Starting your container (this may take a few minutes)..." },
  { phase: "gateway", label: "Gateway connected", activeLabel: "Connecting to AI gateway..." },
  { phase: "ready", label: "Ready", activeLabel: "Ready!" },
];

const STEPS_FREE: { phase: Phase; label: string; activeLabel: string }[] = [
  { phase: "container", label: "Container started", activeLabel: "Starting your container (this may take a few minutes)..." },
  { phase: "gateway", label: "Gateway connected", activeLabel: "Connecting to AI gateway..." },
  { phase: "ready", label: "Ready", activeLabel: "Ready!" },
];

const TIMEOUT_MS = 180_000;

/**
 * Rotating idea prompts shown while the container spins up. Kept short (≤ ~52 chars)
 * so they fit on one line and don't cause layout shift. Tone matches the rest of the
 * onboarding copy: concrete, action-oriented, a little aspirational.
 */
const PROVISION_IDEAS: readonly string[] = [
  "Draft your weekly status report from your inbox",
  "Triage email and reply in your voice",
  "Summarize yesterday's meetings into action items",
  "Spin up a research brief on any topic",
  "Schedule focus time around your calendar",
  "Turn a messy doc into a clean one-pager",
  "Watch a channel and ping you on what matters",
  "Run a recurring morning briefing for you",
  "Pull metrics and drop them into a shared doc",
  "Review a PR and flag the risky changes",
];

const IDEA_ROTATION_MS = 3200;

function RotatingIdeas({ eyebrow }: { eyebrow: string }) {
  const [idx, setIdx] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    if (typeof window !== "undefined" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      return;
    }
    const tick = setInterval(() => {
      setVisible(false);
      const swap = setTimeout(() => {
        setIdx((i) => (i + 1) % PROVISION_IDEAS.length);
        setVisible(true);
      }, 180);
      return () => clearTimeout(swap);
    }, IDEA_ROTATION_MS);
    return () => clearInterval(tick);
  }, []);

  return (
    <>
      <span className="provision-idea-eyebrow">{eyebrow}</span>
      <span
        className={`provision-idea${visible ? "" : " provision-idea-fading"}`}
        aria-live="polite"
        aria-atomic="true"
      >
        {PROVISION_IDEAS[idx]}
      </span>
    </>
  );
}

export function ProvisioningStepper({
  children,
  trigger = "onboarding",
}: {
  children: React.ReactNode;
  /** "onboarding" = full flow (billing → container → gateway → channels → ready).
   *  "recovery" = skip billing, start from container provisioning. */
  trigger?: "onboarding" | "recovery";
}) {
  const posthog = usePostHog();
  const { organization, membership, isLoaded: orgLoaded } = useOrganization();
  const isOrg = !!organization;
  // Personal accounts (no org) and explicit org admins manage channels.
  // Plain members see link-only flows or get sent straight to ready.
  const isAdmin = !isOrg || membership?.role === "org:admin";
  const api = useApi();
  const { isLoading: billingLoading, isSubscribed, planTier, createCheckout } = useBilling();
  const isFree = planTier === "free";
  const provisionRequestedRef = useRef(false);
  const [startTime] = useState(() => Date.now());
  const [timedOut, setTimedOut] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);
  // In-memory only — `channels.status` / `/channels/links/me` is the source
  // of truth for "is the channel onboarding step needed for this user". Cancel
  // hides the wizard for the current session; next mount re-checks the data.
  const [onboardingComplete, setOnboardingComplete] = useState(false);

  // Poll container status every 3s once subscribed or on free tier (auto-provisioned)
  const shouldPollContainer = isSubscribed || isFree;
  const { container, refresh: refreshContainer } = useContainerStatus({
    refreshInterval: shouldPollContainer ? 3000 : 0,
    enabled: shouldPollContainer,
  });

  // When container status returns null (404), trigger provisioning once
  // Trigger provisioning when no container (404) or container is stopped (scale-to-zero)
  const needsProvision = container === null || container?.status === "stopped";
  useEffect(() => {
    // Defensive: don't fire provision until Clerk's org state has fully
    // hydrated. ChatLayout already gates this component behind an onboarded
    // check, so in practice orgLoaded is true by the time we mount — but
    // keeping the guard here means a direct caller (tests, recovery paths)
    // can't accidentally fire /container/provision with a still-loading JWT
    // and get a personal container when an org was expected.
    if (!orgLoaded) return;
    if (needsProvision && shouldPollContainer && !provisionRequestedRef.current) {
      provisionRequestedRef.current = true;
      api.post("/container/provision", {}).catch((err: unknown) => {
        console.error("Container provision failed:", err);
      });
    }
    // Reset the ref when container comes back so it can re-provision on next stop
    if (container && container.status !== "stopped") {
      provisionRequestedRef.current = false;
    }
  }, [needsProvision, orgLoaded, container, shouldPollContainer, api]);

  const containerReady = container?.status === "running" || container?.substatus === "gateway_healthy";

  // Poll gateway health every 3s once container looks ready
  const { data: gatewayHealth } = useGatewayRpc<Record<string, unknown>>(
    shouldPollContainer && containerReady ? "health" : null,
    undefined,
    { refreshInterval: 3000, dedupingInterval: 2000 },
  );

  // Once the gateway is healthy, fetch the caller's channel-link state.
  // `/channels/links/me` returns every bot configured in the org's
  // openclaw.json plus a per-member `linked` flag — exactly what we need to
  // decide whether to show the create wizard (admin), the link-only wizard
  // (member needs to pair), or skip channel onboarding entirely.
  const { data: linksData, error: linksError } = useSWR<LinksMeResponse>(
    gatewayHealth && !onboardingComplete ? "/channels/links/me" : null,
    () => api.get("/channels/links/me") as Promise<LinksMeResponse>,
  );

  // For members, the wizard target is the first main-agent bot they haven't
  // linked yet. Computed once so the phase derivation and the channels-phase
  // render below stay in sync.
  const memberLinkTarget: Provider | null = useMemo(() => {
    if (isAdmin || !linksData) return null;
    return findFirstUnlinkedMainProvider(linksData);
  }, [isAdmin, linksData]);

  // Derive phase purely from data
  const phase: Phase = useMemo(() => {
    // Free tier auto-provisions; paid tiers need subscription first.
    // Recovery flow skips billing — the user already has a plan.
    if (trigger !== "recovery" && !isSubscribed && !isFree) return "payment";
    if (!container || (container.status === "provisioning" && !containerReady)) return "container";
    if (container.status === "error") return "container";
    if (!containerReady || !gatewayHealth) return "gateway";

    // Onboarding already dismissed by user
    if (onboardingComplete) return "ready";

    // /links/me errored — don't block the user, go straight to ready
    if (linksError) return "ready";

    // Still waiting for /links/me to load
    if (!linksData) return "gateway";

    // Free-tier containers scale to zero, so bots can't stay connected —
    // skip channel onboarding entirely. Members in free orgs are also
    // covered by this branch (free orgs can't have bots configured).
    if (isFree) return "ready";

    if (isAdmin) {
      // Admin: if no main-agent bot exists yet, show the create wizard.
      // Otherwise the org is already past channel setup → ready.
      return hasMainBot(linksData) ? "ready" : "channels";
    }

    // Member: only show the link-only wizard if there's actually a main bot
    // they haven't paired with. If main has no bot OR they're fully linked,
    // skip channel onboarding entirely — they'll see the linking UX in
    // Settings → My Channels later if they want it.
    return memberLinkTarget !== null ? "channels" : "ready";
  }, [trigger, isSubscribed, isFree, container, containerReady, gatewayHealth, linksData, linksError, onboardingComplete, isAdmin, memberLinkTarget]);

  // Analytics: fire `onboarding_step_completed` once per step transition,
  // NOT on every render. The prev-phase ref reflects the LAST rendered
  // phase; when it changes, the step the user just advanced past is the
  // previous value. We use the step-list that matches the user's tier
  // (free vs paid) so step_index is meaningful.
  const prevPhaseRef = useRef<Phase | null>(null);
  useEffect(() => {
    const prev = prevPhaseRef.current;
    prevPhaseRef.current = phase;
    if (prev === null || prev === phase) return;
    const completion = nextOnboardingCompletion(prev, phase, isFree ? STEPS_FREE : STEPS_PAID);
    if (completion) capture("onboarding_step_completed", { ...completion });
  }, [phase, isFree]);

  // Timeout check via interval callback (setTimedOut only in callback, not sync in effect body)
  useEffect(() => {
    if (phase === "ready" || phase === "payment" || phase === "channels") return;
    const interval = setInterval(() => {
      if (Date.now() - startTime > TIMEOUT_MS) {
        setTimedOut(true);
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [phase, startTime]);

  // Ready — render children
  if (phase === "ready") {
    return <>{children}</>;
  }

  // Channel onboarding — admins set up the first main-agent bot, members
  // pair their identity with an existing one. Always scoped to `main`.
  if (phase === "channels") {
    const wizardMode = isAdmin ? "create" : "link-only";
    // Admin creates always default to telegram; member link-only uses
    // whichever main-agent provider they haven't paired with yet.
    const wizardProvider: Provider = isAdmin ? "telegram" : (memberLinkTarget ?? "telegram");
    // Look up the actual bot handle so the link-only pair step can tell the
    // member which bot to DM. linksData is guaranteed loaded here because
    // we only enter the channels phase after it resolves.
    const wizardBotUsername = !isAdmin
      ? linksData?.[wizardProvider]?.find((b) => b.agent_id === "main")?.bot_username
      : undefined;
    return (
      <div className="flex-1 flex items-center justify-center p-6 bg-[#faf7f2]">
        <div className="w-full max-w-md">
          <BotSetupWizard
            mode={wizardMode}
            provider={wizardProvider}
            agentId="main"
            botUsername={wizardBotUsername}
            onComplete={() => { posthog?.capture("onboarding_completed"); setOnboardingComplete(true); }}
            onCancel={() => setOnboardingComplete(true)}
          />
        </div>
      </div>
    );
  }

  // Loading billing
  if (billingLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Not subscribed and not free — show pricing
  if (!isSubscribed && !isFree) {
    return <PricingCards checkoutLoading={checkoutLoading} isOrg={isOrg} orgName={organization?.name} onCheckout={async (tier) => {
      posthog?.capture("checkout_started", { tier });
      setCheckoutLoading(tier);
      try {
        await createCheckout(tier);
      } catch (err) {
        console.error("Checkout failed:", err);
        setCheckoutLoading(null);
      }
    }} />;
  }

  // Error state
  if (container?.status === "error") {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#faf7f2]">
        <div className="text-center space-y-6 max-w-sm">
          <StepperDisplay currentPhase={phase} steps={isFree ? STEPS_FREE : STEPS_PAID} error />
          <div className="space-y-2">
            <XCircle className="h-8 w-8 text-[#dc2626] mx-auto" />
            <h2 className="text-lg font-medium text-[#1a1a1a]">Setup failed</h2>
            <p className="text-sm text-[#8a8578]">
              {isOrg
                ? `Something went wrong while setting up the container for ${organization.name}. This is usually temporary.`
                : "Something went wrong while setting up your container. This is usually temporary."}
            </p>
          </div>
          <div className="flex gap-3 justify-center">
            <Button variant="outline" className="rounded-full border-[#e0dbd0]" onClick={() => refreshContainer()}>
              Retry
            </Button>
            <Button variant="ghost" className="rounded-full" asChild>
              <a href="mailto:support@isol8.co">Contact Support</a>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Provisioning stepper — animated 4-step flow
  const steps = isFree ? STEPS_FREE : STEPS_PAID;
  const currentIdx = steps.findIndex((s) => s.phase === phase);
  const currentStep = steps[currentIdx] || steps[0];

  return (
    <>
      <style>{`
        .provision-wrapper {
          flex: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          background: #faf7f2;
        }
        .provision-card {
          text-align: center;
          max-width: 400px;
          width: 100%;
          padding: 48px 32px;
        }
        .provision-logo {
          margin-bottom: 32px;
        }
        .provision-stage {
          width: 80px;
          height: 80px;
          margin: 0 auto 32px;
          position: relative;
        }
        .provision-anim {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
          opacity: 0;
          transition: opacity 400ms ease-out;
        }
        .provision-anim.active { opacity: 1; }

        /* Key spinner */
        .anim-key-circle {
          width: 56px; height: 56px;
          border: 2px solid #e0dbd0;
          border-top-color: #06402B;
          border-radius: 50%;
          animation: key-spin 1.2s linear infinite;
        }
        .anim-key-icon {
          position: absolute;
          inset: 0;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        @keyframes key-spin { to { transform: rotate(360deg); } }

        /* Pod opening */
        .anim-pod { position: relative; width: 56px; height: 56px; }
        .pod-body {
          position: absolute; bottom: 0; left: 4px; right: 4px; height: 32px;
          background: #06402B; border-radius: 0 0 8px 8px;
        }
        .pod-window {
          width: 20px; height: 10px; background: #a8e6c6; border-radius: 4px;
          margin: 8px auto 0;
        }
        .pod-lid-l, .pod-lid-r {
          position: absolute; top: 16px; width: 50%; height: 12px;
          background: #06402B; transition: transform 600ms ease-out;
        }
        .pod-lid-l { left: 4px; border-radius: 8px 0 0 0; transform-origin: left center; }
        .pod-lid-r { right: 4px; border-radius: 0 8px 0 0; transform-origin: right center; }
        .pod-open .pod-lid-l { transform: rotate(-35deg); }
        .pod-open .pod-lid-r { transform: rotate(35deg); }
        .pod-steam-line {
          position: absolute; width: 2px; background: #c8e6c9; border-radius: 1px;
          opacity: 0; transition: opacity 400ms ease-out 300ms;
        }
        .pod-open .pod-steam-line { opacity: 1; animation: steam 1.5s ease-out infinite; }
        .pod-steam-line:nth-child(1) { left: 14px; height: 16px; top: -4px; animation-delay: 0s; }
        .pod-steam-line:nth-child(2) { left: 26px; height: 12px; top: -2px; animation-delay: 0.3s; }
        .pod-steam-line:nth-child(3) { left: 38px; height: 14px; top: -6px; animation-delay: 0.6s; }
        @keyframes steam {
          0% { transform: translateY(0); opacity: 0.7; }
          100% { transform: translateY(-18px); opacity: 0; }
        }

        /* Gateway */
        .anim-gate { position: relative; width: 56px; height: 56px; }
        .gate-frame {
          position: absolute; inset: 4px; border: 2px solid #06402B;
          border-radius: 12px 12px 4px 4px; overflow: hidden;
        }
        .gate-glow {
          position: absolute; inset: 0; background: #a8e6c6; opacity: 0;
          transition: opacity 500ms ease-out;
        }
        .gate-opening .gate-glow { opacity: 0.3; }
        .gate-door-l, .gate-door-r {
          position: absolute; top: 0; bottom: 0; width: 50%;
          background: #06402B; transition: transform 600ms ease-out;
        }
        .gate-door-l { left: 0; }
        .gate-door-r { right: 0; }
        .gate-opening .gate-door-l { transform: translateX(-100%); }
        .gate-opening .gate-door-r { transform: translateX(100%); }
        .gate-signal {
          position: absolute; inset: 0; display: flex;
          align-items: center; justify-content: center;
          opacity: 0; transition: opacity 400ms ease-out 400ms;
        }
        .gate-opening .gate-signal { opacity: 1; }

        /* Done check */
        .anim-done { display: flex; align-items: center; justify-content: center; }
        .check-path {
          stroke-dasharray: 30; stroke-dashoffset: 30;
          animation: draw-check 600ms ease-out forwards;
        }
        @keyframes draw-check { to { stroke-dashoffset: 0; } }

        /* Title fade */
        .provision-title {
          font-family: var(--font-lora-serif), serif;
          font-size: 22px; font-weight: 400; color: #1a1a1a;
          margin-bottom: 8px; transition: opacity 150ms ease-out;
        }
        .provision-desc {
          font-family: var(--font-dm-sans), sans-serif;
          font-size: 14px; color: #8a8578;
          margin-bottom: 32px; transition: opacity 150ms ease-out;
        }
        .provision-fading { opacity: 0; }

        /* Rotating idea suggestions — stacked eyebrow + phrase, space reserved
           so the layout never shifts during crossfade. */
        .provision-desc-ideas {
          display: flex; flex-direction: column; align-items: center;
          gap: 6px; min-height: 56px;
        }
        .provision-idea-eyebrow {
          font-family: var(--font-dm-sans), sans-serif;
          font-size: 12px; font-weight: 500;
          color: #a8a396; letter-spacing: 0.3px;
          text-transform: uppercase;
        }
        .provision-idea {
          font-family: var(--font-lora-serif), serif;
          font-size: 15px; font-style: italic;
          color: #4a4638; line-height: 1.4;
          max-width: 42ch; text-align: center;
          transition: opacity 180ms ease-out, transform 180ms ease-out;
          will-change: opacity, transform;
        }
        .provision-idea-fading { opacity: 0; transform: translateY(4px); }

        /* Progress dots */
        .provision-dots {
          display: flex; align-items: center; justify-content: center; gap: 0;
        }
        .provision-dot {
          width: 10px; height: 10px; border-radius: 50%;
          background: #e0dbd0; transition: background 300ms ease-out, transform 300ms ease-out;
        }
        .provision-dot.active { background: #06402B; transform: scale(1.2); }
        .provision-dot.done { background: #2d8a4e; }
        .provision-connector {
          width: 32px; height: 2px; background: #e0dbd0;
          transition: background 300ms ease-out;
        }
        .provision-connector.done { background: #2d8a4e; }

        .provision-free-banner {
          margin-top: 24px;
          padding: 12px 16px;
          background: #e8f5e9;
          border: 1px solid #c8e6c9;
          border-radius: 12px;
          font-size: 13px;
          color: #2d7a50;
        }
        .provision-free-sub {
          font-size: 12px; color: #8a8578; margin-top: 8px;
        }
        .provision-timeout {
          margin-top: 24px; display: flex; flex-direction: column;
          align-items: center; gap: 12px;
        }
        .provision-timeout-msg {
          display: flex; align-items: center; gap: 8px;
          color: #8a6a22; font-size: 14px;
        }

        @media (prefers-reduced-motion: reduce) {
          .anim-key-circle { animation: none; }
          .pod-steam-line { animation: none; }
          .check-path { animation: none; stroke-dashoffset: 0; }
          .provision-title, .provision-desc { transition: none; }
        }
      `}</style>
      <div className="provision-wrapper">
        <div className="provision-card">
          <div className="provision-logo">
            <svg width="48" height="48" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect width="100" height="100" rx="22" fill="#06402B" />
              <text x="50" y="68" textAnchor="middle" fontFamily="var(--font-lora-serif), serif" fontStyle="italic" fontSize="52" fill="white">8</text>
            </svg>
          </div>

          {/* Animation stage */}
          <div className="provision-stage" aria-hidden="true">
            {/* Step: payment/container — key spinner */}
            <div className={`provision-anim ${phase === "payment" || phase === "container" ? "active" : ""}`}>
              <div className="anim-key-circle" />
              <div className="anim-key-icon">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#06402B" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.78 7.78 5.5 5.5 0 0 1 7.78-7.78zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
                </svg>
              </div>
            </div>

            {/* Step: gateway — pod opening */}
            <div className={`provision-anim ${phase === "gateway" ? "active" : ""}`}>
              <div className={`anim-pod ${phase === "gateway" ? "pod-open" : ""}`}>
                <div className="pod-steam-line" /><div className="pod-steam-line" /><div className="pod-steam-line" />
                <div className="pod-lid-l" /><div className="pod-lid-r" />
                <div className="pod-body"><div className="pod-window" /></div>
              </div>
            </div>

            {/* Step: channels — gate opening */}
            <div className={`provision-anim ${(phase as string) === "channels" ? "active" : ""}`}>
              <div className={`anim-gate ${(phase as string) === "channels" ? "gate-opening" : ""}`}>
                <div className="gate-frame">
                  <div className="gate-glow" />
                  <div className="gate-door-l" /><div className="gate-door-r" />
                  <div className="gate-signal">
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#06402B" strokeWidth="2.5" strokeLinecap="round">
                      <path d="M5 12.55a11 11 0 0 1 14.08 0" /><path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
                      <circle cx="12" cy="20" r="1" fill="#06402B" />
                    </svg>
                  </div>
                </div>
              </div>
            </div>

            {/* Step: ready — checkmark */}
            <div className={`provision-anim ${(phase as string) === "ready" ? "active" : ""}`}>
              <div className="anim-done">
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#06402B" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" className="check-path" />
                </svg>
              </div>
            </div>
          </div>

          <h2 className="provision-title">{currentStep?.activeLabel || "Setting up..."}</h2>
          <div className="provision-desc provision-desc-ideas">
            <RotatingIdeas
              eyebrow={
                isOrg
                  ? `Preparing workspace for ${organization?.name} — try asking your agent to…`
                  : "While you wait, try asking your agent to…"
              }
            />
          </div>

          {/* Progress dots */}
          <div className="provision-dots">
            {steps.map((step, i) => (
              <span key={step.phase}>
                {i > 0 && <span className={`provision-connector ${i <= currentIdx ? "done" : ""}`} />}
                <span className={`provision-dot ${i === currentIdx ? "active" : i < currentIdx ? "done" : ""}`} />
              </span>
            ))}
          </div>

          {isFree && (
            <div className="provision-free-banner">
              You have $2 in free usage. Subscribe anytime for more.
              <div className="provision-free-sub">
                Free tier agents sleep after 5 minutes of inactivity.
              </div>
            </div>
          )}

          {timedOut && (
            <div className="provision-timeout">
              <div className="provision-timeout-msg">
                <AlertTriangle className="h-4 w-4" />
                <span>Taking longer than expected</span>
              </div>
              <div className="flex gap-3">
                <Button variant="outline" size="sm" onClick={() => window.location.reload()}>
                  Refresh
                </Button>
                <Button variant="ghost" size="sm" asChild>
                  <a href="mailto:support@isol8.co">Contact Support</a>
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  );
}


function StepperDisplay({
  currentPhase,
  steps,
  error = false,
}: {
  currentPhase: Phase;
  steps: { phase: Phase; label: string; activeLabel: string }[];
  error?: boolean;
}) {
  const currentIdx = steps.findIndex((s) => s.phase === currentPhase);

  return (
    <div className="space-y-3 text-left mx-auto w-fit">
      {steps.map((step, idx) => {
        const isComplete = idx < currentIdx;
        const isCurrent = idx === currentIdx;
        const isErrorStep = error && isCurrent;

        return (
          <div key={step.phase} className="flex items-center gap-3">
            {isErrorStep ? (
              <XCircle className="h-5 w-5 text-[#dc2626] flex-shrink-0" />
            ) : isComplete ? (
              <CheckCircle className="h-5 w-5 text-[#2d8a4e] flex-shrink-0" />
            ) : isCurrent ? (
              <Loader2 className="h-5 w-5 animate-spin text-[#06402B] flex-shrink-0" />
            ) : (
              <Circle className="h-5 w-5 text-[#d4cfc5] flex-shrink-0" />
            )}
            <span
              className={
                isErrorStep
                  ? "text-sm text-[#dc2626]"
                  : isComplete
                    ? "text-sm text-[#1a1a1a]"
                    : isCurrent
                      ? "text-sm text-[#1a1a1a] font-medium"
                      : "text-sm text-[#c5bfb6]"
              }
            >
              {isCurrent && !error ? step.activeLabel : step.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function PricingCards({
  checkoutLoading,
  isOrg,
  orgName,
  onCheckout,
}: {
  checkoutLoading: string | null;
  isOrg: boolean;
  orgName?: string;
  onCheckout: (tier: "starter" | "pro") => Promise<void>;
}) {
  return (
    <div className="flex-1 flex items-center justify-center p-8 bg-[#faf7f2]">
      <div className="max-w-2xl w-full space-y-8 text-center">
        <div className="space-y-3">
          <svg width="48" height="48" viewBox="0 0 100 100" fill="none" xmlns="http://www.w3.org/2000/svg" className="mx-auto mb-4">
            <rect width="100" height="100" rx="22" fill="#06402B" />
            <text x="50" y="68" textAnchor="middle" fontFamily="var(--font-lora-serif), serif" fontStyle="italic" fontSize="52" fill="white">8</text>
          </svg>
          <h2 className="text-2xl font-semibold tracking-tight text-[#1a1a1a] font-lora">
            Choose your plan
          </h2>
          <p className="text-[#8a8578] text-sm max-w-md mx-auto">
            {isOrg
              ? `Subscribe to get an AI agent container for ${orgName} with persistent memory, custom personality, and access to top-tier models.`
              : "Subscribe to get your own AI agent container with persistent memory, custom personality, and access to top-tier models."}
          </p>
        </div>

        <div className="grid sm:grid-cols-2 gap-4 max-w-lg mx-auto">
          <div className="rounded-xl border border-[#e0dbd0] p-6 space-y-4 bg-white">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-[#2d8a4e]" />
                <h3 className="font-medium text-[#1a1a1a]">Starter</h3>
              </div>
              <div className="flex items-baseline gap-1">
                <span className="text-3xl font-semibold text-[#1a1a1a]">$40</span>
                <span className="text-[#8a8578] text-sm">/mo</span>
              </div>
            </div>
            <ul className="text-sm text-[#5a5549] space-y-2 text-left">
              <li>{isOrg ? "Organization AI container" : "Personal AI container"}</li>
              <li>Persistent memory</li>
              <li>1 free model included</li>
              <li>Pay-per-use premium models</li>
            </ul>
            <Button
              className="w-full rounded-full border-[#e0dbd0] text-[#1a1a1a] hover:bg-[#f3efe6]"
              variant="outline"
              onClick={() => onCheckout("starter")}
              disabled={!!checkoutLoading}
            >
              {checkoutLoading === "starter" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                "Get Started"
              )}
            </Button>
          </div>

          <div className="rounded-xl border-2 border-[#06402B] p-6 space-y-4 bg-white relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 bg-[#06402B] text-white text-xs font-medium rounded-full">
              Popular
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Crown className="h-4 w-4 text-amber-500" />
                <h3 className="font-medium text-[#1a1a1a]">Pro</h3>
              </div>
              <div className="flex items-baseline gap-1">
                <span className="text-3xl font-semibold text-[#1a1a1a]">$75</span>
                <span className="text-[#8a8578] text-sm">/mo</span>
              </div>
            </div>
            <ul className="text-sm text-[#5a5549] space-y-2 text-left">
              <li>Everything in Starter</li>
              <li>Higher usage budget</li>
              <li>Priority support</li>
              <li>Advanced agent features</li>
            </ul>
            <Button
              className="w-full rounded-full bg-[#06402B] hover:bg-[#0a5c3e] text-white"
              onClick={() => onCheckout("pro")}
              disabled={!!checkoutLoading}
            >
              {checkoutLoading === "pro" ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                "Upgrade to Pro"
              )}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
