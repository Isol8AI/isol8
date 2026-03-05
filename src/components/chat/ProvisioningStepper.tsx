"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Loader2,
  Zap,
  Crown,
  CheckCircle,
  Circle,
  XCircle,
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useBilling } from "@/hooks/useBilling";
import { useContainerStatus } from "@/hooks/useContainerStatus";
import { useGatewayRpc } from "@/hooks/useGatewayRpc";

type Phase = "payment" | "container" | "gateway" | "ready";

const STEPS: { phase: Phase; label: string; activeLabel: string }[] = [
  { phase: "payment", label: "Payment confirmed", activeLabel: "Confirming payment..." },
  { phase: "container", label: "Container started", activeLabel: "Starting your container..." },
  { phase: "gateway", label: "Gateway connected", activeLabel: "Connecting to AI gateway..." },
  { phase: "ready", label: "Ready", activeLabel: "Ready!" },
];

const TIMEOUT_MS = 120_000;

export function ProvisioningStepper({
  children,
}: {
  children: React.ReactNode;
}) {
  const searchParams = useSearchParams();
  const { isLoading: billingLoading, isSubscribed, createCheckout, refresh: refreshBilling } = useBilling();
  const justSubscribed = searchParams.get("subscription") === "success";

  const [phase, setPhase] = useState<Phase>("payment");
  const [startTime] = useState(() => Date.now());
  const [timedOut, setTimedOut] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);

  // Poll billing every 2s until subscribed
  const [billingPolling, setBillingPolling] = useState(false);

  useEffect(() => {
    if (!justSubscribed || isSubscribed || billingLoading) return;
    setBillingPolling(true);
    const interval = setInterval(() => refreshBilling(), 2000);
    return () => clearInterval(interval);
  }, [justSubscribed, isSubscribed, billingLoading, refreshBilling]);

  useEffect(() => {
    if (isSubscribed && billingPolling) {
      setBillingPolling(false);
      window.history.replaceState({}, "", "/chat");
    }
  }, [isSubscribed, billingPolling]);

  // Poll container status every 3s once subscribed
  const shouldPollContainer = isSubscribed && phase !== "ready";
  const { container, refresh: refreshContainer } = useContainerStatus({
    refreshInterval: shouldPollContainer ? 3000 : 0,
    enabled: shouldPollContainer,
  });

  // Poll gateway health every 3s once container is running
  const shouldPollGateway = phase === "gateway";
  const { data: gatewayHealth } = useGatewayRpc<Record<string, unknown>>(
    shouldPollGateway ? "health" : null,
    undefined,
    { refreshInterval: 3000, dedupingInterval: 2000 },
  );

  // Phase state machine
  useEffect(() => {
    if (!isSubscribed) {
      setPhase("payment");
      return;
    }

    if (!container) {
      setPhase("container");
      return;
    }

    if (container.status === "error") {
      return;
    }

    if (container.status === "running" || container.substatus === "gateway_healthy") {
      if (gatewayHealth) {
        setPhase("ready");
      } else {
        setPhase("gateway");
      }
      return;
    }

    setPhase("container");
  }, [isSubscribed, container, gatewayHealth]);

  // Timeout check
  useEffect(() => {
    if (phase === "ready") return;
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

  // Loading billing
  if (billingLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Not subscribed and not just returning from checkout
  if (!isSubscribed && !justSubscribed) {
    return <PricingCards checkoutLoading={checkoutLoading} onCheckout={async (tier) => {
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
          <StepperDisplay currentPhase={phase} error />
          <div className="space-y-2">
            <h2 className="text-lg font-medium">Setup failed</h2>
            <p className="text-sm text-muted-foreground">
              Something went wrong while setting up your container. This is usually temporary.
            </p>
          </div>
          <div className="flex gap-3 justify-center">
            <Button variant="outline" onClick={() => {
              refreshContainer();
              refreshBilling();
            }}>
              Retry Setup
            </Button>
            <Button variant="ghost" asChild>
              <a href="mailto:support@isol8.co">Contact Support</a>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Timeout state
  if (timedOut) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <div className="text-center space-y-6 max-w-sm">
          <StepperDisplay currentPhase={phase} />
          <div className="space-y-2">
            <AlertTriangle className="h-8 w-8 text-yellow-500 mx-auto" />
            <h2 className="text-lg font-medium">Taking longer than expected</h2>
            <p className="text-sm text-muted-foreground">
              Your container is still being set up. This can occasionally take a few minutes.
            </p>
          </div>
          <div className="flex gap-3 justify-center">
            <Button variant="outline" onClick={() => window.location.reload()}>
              Refresh
            </Button>
            <Button variant="ghost" asChild>
              <a href="mailto:support@isol8.co">Contact Support</a>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  // Active provisioning stepper
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center space-y-8 max-w-sm">
        <div className="space-y-2">
          <h2 className="text-xl font-semibold">Setting up your workspace</h2>
          <p className="text-sm text-muted-foreground">
            This usually takes about 30-60 seconds.
          </p>
        </div>
        <StepperDisplay currentPhase={phase} />
      </div>
    </div>
  );
}

function StepperDisplay({
  currentPhase,
  error = false,
}: {
  currentPhase: Phase;
  error?: boolean;
}) {
  const currentIdx = STEPS.findIndex((s) => s.phase === currentPhase);

  return (
    <div className="space-y-3 text-left mx-auto w-fit">
      {STEPS.map((step, idx) => {
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
  onCheckout,
}: {
  checkoutLoading: string | null;
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
            Subscribe to get your own AI agent container with persistent memory,
            custom personality, and access to top-tier models.
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
              <li>Personal AI container</li>
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
