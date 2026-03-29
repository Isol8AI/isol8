"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Loader2,
  Zap,
  Crown,
  CheckCircle,
  Circle,
  XCircle,
  AlertTriangle,
} from "lucide-react";
import { useOrganization } from "@clerk/nextjs";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api";
import { useBilling } from "@/hooks/useBilling";
import { useContainerStatus } from "@/hooks/useContainerStatus";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";
import { ChannelCards, isChannelCardsDismissed } from "@/components/chat/ChannelCards";
type Phase = "payment" | "container" | "gateway" | "channels" | "ready";

const STEPS_PAID: { phase: Phase; label: string; activeLabel: string }[] = [
  { phase: "payment", label: "Payment confirmed", activeLabel: "Confirming payment..." },
  { phase: "container", label: "Container started", activeLabel: "Starting your container..." },
  { phase: "gateway", label: "Gateway connected", activeLabel: "Connecting to AI gateway..." },
  { phase: "ready", label: "Ready", activeLabel: "Ready!" },
];

const STEPS_FREE: { phase: Phase; label: string; activeLabel: string }[] = [
  { phase: "container", label: "Container started", activeLabel: "Starting your container..." },
  { phase: "gateway", label: "Gateway connected", activeLabel: "Connecting to AI gateway..." },
  { phase: "ready", label: "Ready", activeLabel: "Ready!" },
];

const TIMEOUT_MS = 180_000;

export function ProvisioningStepper({
  children,
}: {
  children: React.ReactNode;
}) {
  const { organization } = useOrganization();
  const isOrg = !!organization;
  const api = useApi();
  const { isLoading: billingLoading, isSubscribed, planTier, createCheckout } = useBilling();
  const isFree = planTier === "free";
  const provisionRequestedRef = useRef(false);
  const [startTime] = useState(() => Date.now());
  const [timedOut, setTimedOut] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);
  // Lazy initializer reads localStorage once on mount. isChannelCardsDismissed()
  // guards SSR (returns true when window is undefined) so this is SSR-safe.
  // eslint-config-next blocks setState-in-effect, so useEffect is not an option here.
  const [onboardingComplete, setOnboardingComplete] = useState(() => isChannelCardsDismissed());

  // Poll container status every 3s once subscribed or on free tier (auto-provisioned)
  const shouldPollContainer = isSubscribed || isFree;
  const { container, refresh: refreshContainer } = useContainerStatus({
    refreshInterval: shouldPollContainer ? 3000 : 0,
    enabled: shouldPollContainer,
  });

  // When container status returns null (404), trigger provisioning once
  useEffect(() => {
    if (container === null && shouldPollContainer && !provisionRequestedRef.current) {
      provisionRequestedRef.current = true;
      api.post("/container/provision", {}).catch((err: unknown) => {
        console.error("Container provision failed:", err);
      });
    }
  }, [container, shouldPollContainer, api]);

  const containerReady = container?.status === "running" || container?.substatus === "gateway_healthy";

  // Poll gateway health every 3s once container looks ready
  const { data: gatewayHealth } = useGatewayRpc<Record<string, unknown>>(
    shouldPollContainer && containerReady ? "health" : null,
    undefined,
    { refreshInterval: 3000, dedupingInterval: 2000 },
  );

  // Check channels status once when gateway is healthy — used to detect first-time users
  const { data: channelsData, error: channelsError } = useGatewayRpc<{
    channelAccounts: Record<string, { connected?: boolean; configured?: boolean; running?: boolean; linked?: boolean }[]>;
  }>(
    gatewayHealth && !onboardingComplete ? "channels.status" : null,
    undefined,
    { refreshInterval: 0 },
  );

  // Derive phase purely from data
  const phase: Phase = useMemo(() => {
    // Free tier auto-provisions; paid tiers need subscription first
    if (!isSubscribed && !isFree) return "payment";
    if (!container || (container.status === "provisioning" && !containerReady)) return "container";
    if (container.status === "error") return "container";
    if (!containerReady || !gatewayHealth) return "gateway";

    // Onboarding already dismissed by user
    if (onboardingComplete) return "ready";

    // channels.status errored — don't block the user, go straight to ready
    if (channelsError) return "ready";

    // Still waiting for channels.status to load
    if (!channelsData) return "gateway";

    // Check if any channel is already connected/configured
    const anyConnected = Object.values(channelsData.channelAccounts ?? {}).some(
      (accounts) => accounts.some((a) => a.connected || a.configured || a.running || a.linked),
    );
    if (anyConnected) return "ready";

    // No channels connected — show onboarding
    return "channels";
  }, [isSubscribed, isFree, container, containerReady, gatewayHealth, channelsData, channelsError, onboardingComplete]);

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

  // Channel onboarding — shown after gateway is connected for users with no channels
  if (phase === "channels") {
    return (
      <div className="flex-1 flex items-center justify-center p-6">
        <ChannelCards onDismiss={() => setOnboardingComplete(true)} />
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
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-6 max-w-sm">
          <StepperDisplay currentPhase={phase} steps={isFree ? STEPS_FREE : STEPS_PAID} error />
          <div className="space-y-2">
            <XCircle className="h-8 w-8 text-red-500 mx-auto" />
            <h2 className="text-lg font-medium">Setup failed</h2>
            <p className="text-sm text-muted-foreground">
              {isOrg
                ? `Something went wrong while setting up the container for ${organization.name}. This is usually temporary.`
                : "Something went wrong while setting up your container. This is usually temporary."}
            </p>
          </div>
          <div className="flex gap-3 justify-center">
            <Button variant="outline" onClick={() => refreshContainer()}>
              Retry
            </Button>
            <Button variant="ghost" asChild>
              <a href="mailto:support@isol8.co">Contact Support</a>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Provisioning stepper — always shown during container/gateway phases
  const steps = isFree ? STEPS_FREE : STEPS_PAID;

  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center space-y-8 max-w-sm">
        <div className="space-y-2">
          <h2 className="text-xl font-semibold">
            {isOrg
              ? `Setting up workspace for ${organization.name}...`
              : "Setting up your personal workspace..."}
          </h2>
          <p className="text-sm text-muted-foreground">
            This usually takes about 30-60 seconds.
          </p>
        </div>
        {isFree && (
          <div className="space-y-2">
            <div className="px-4 py-3 bg-blue-900/20 border border-blue-500/30 rounded-lg text-sm text-blue-200">
              You have $2 in free usage. Subscribe anytime for more.
            </div>
            <p className="text-xs text-muted-foreground">
              Free tier agents sleep after 5 minutes of inactivity. They restart in ~30 seconds.
            </p>
          </div>
        )}
        <StepperDisplay currentPhase={phase} steps={steps} />
        {timedOut && (
          <div className="space-y-4 pt-2">
            <div className="flex items-center justify-center gap-2 text-yellow-500">
              <AlertTriangle className="h-4 w-4" />
              <p className="text-sm">Taking longer than expected</p>
            </div>
            <div className="flex gap-3 justify-center">
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
              <XCircle className="h-5 w-5 text-red-500 flex-shrink-0" />
            ) : isComplete ? (
              <CheckCircle className="h-5 w-5 text-green-500 flex-shrink-0" />
            ) : isCurrent ? (
              <Loader2 className="h-5 w-5 animate-spin text-primary flex-shrink-0" />
            ) : (
              <Circle className="h-5 w-5 text-muted-foreground/30 flex-shrink-0" />
            )}
            <span
              className={
                isErrorStep
                  ? "text-sm text-red-400"
                  : isComplete
                    ? "text-sm text-foreground"
                    : isCurrent
                      ? "text-sm text-foreground font-medium"
                      : "text-sm text-muted-foreground/50"
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
    <div className="flex-1 flex items-center justify-center p-8">
      <div className="max-w-2xl w-full space-y-8 text-center">
        <div className="space-y-3">
          <h2 className="text-2xl font-semibold tracking-tight">
            Choose your plan
          </h2>
          <p className="text-muted-foreground text-sm max-w-md mx-auto">
            {isOrg
              ? `Subscribe to get an AI agent container for ${orgName} with persistent memory, custom personality, and access to top-tier models.`
              : "Subscribe to get your own AI agent container with persistent memory, custom personality, and access to top-tier models."}
          </p>
        </div>

        <div className="grid sm:grid-cols-2 gap-4 max-w-lg mx-auto">
          <div className="rounded-xl border border-border p-6 space-y-4 bg-card/50">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Zap className="h-4 w-4 text-blue-400" />
                <h3 className="font-medium">Starter</h3>
              </div>
              <div className="flex items-baseline gap-1">
                <span className="text-3xl font-semibold">$25</span>
                <span className="text-muted-foreground text-sm">/mo</span>
              </div>
            </div>
            <ul className="text-sm text-muted-foreground space-y-2 text-left">
              <li>{isOrg ? "Organization AI container" : "Personal AI container"}</li>
              <li>Persistent memory</li>
              <li>1 free model included</li>
              <li>Pay-per-use premium models</li>
            </ul>
            <Button
              className="w-full"
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

          <div className="rounded-xl border border-primary/50 p-6 space-y-4 bg-card/50 relative">
            <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 bg-primary text-primary-foreground text-xs font-medium rounded-full">
              Popular
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <Crown className="h-4 w-4 text-amber-400" />
                <h3 className="font-medium">Pro</h3>
              </div>
              <div className="flex items-baseline gap-1">
                <span className="text-3xl font-semibold">$75</span>
                <span className="text-muted-foreground text-sm">/mo</span>
              </div>
            </div>
            <ul className="text-sm text-muted-foreground space-y-2 text-left">
              <li>Everything in Starter</li>
              <li>Higher usage budget</li>
              <li>Priority support</li>
              <li>Advanced agent features</li>
            </ul>
            <Button
              className="w-full"
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
