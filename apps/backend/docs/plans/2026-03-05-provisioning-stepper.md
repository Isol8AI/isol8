# Unified Provisioning Stepper Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the fragmented SubscriptionGate + ContainerGate + AgentCreateDialog onboarding flow with a single ProvisioningStepper component backed by real-time container substatus tracking.

**Architecture:** Add a `substatus` column to the Container model that gets updated at each ECS provisioning step. The frontend polls `GET /container/status` and maps substatus to a 4-step visual stepper. The old SubscriptionGate, ContainerGate, and AgentCreateDialog are removed and replaced by a single ProvisioningStepper component.

**Tech Stack:** FastAPI + SQLAlchemy (backend), Next.js 16 + React 19 + Tailwind CSS v4 + lucide-react (frontend), SWR for polling.

---

### Task 1: Add `substatus` column to Container model

**Files:**
- Modify: `backend/models/container.py:64-70`
- Test: `backend/tests/unit/models/test_container.py`

**Step 1: Write the failing test**

Add to `backend/tests/unit/models/test_container.py`:

```python
@pytest.mark.asyncio
async def test_container_substatus(self, db_session, test_user):
    """Test substatus column can be set and read."""
    container = Container(
        user_id=test_user.id,
        gateway_token="tok-substatus",
        status="provisioning",
        substatus="efs_created",
    )
    db_session.add(container)
    await db_session.flush()

    result = await db_session.execute(
        select(Container).where(Container.user_id == test_user.id)
    )
    found = result.scalar_one()
    assert found.substatus == "efs_created"

@pytest.mark.asyncio
async def test_container_substatus_nullable(self, db_session, test_user):
    """Test substatus defaults to None."""
    container = Container(
        user_id=test_user.id,
        gateway_token="tok-sub-null",
        status="running",
    )
    db_session.add(container)
    await db_session.flush()
    assert container.substatus is None
```

**Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/models/test_container.py::TestContainerModel::test_container_substatus -v`
Expected: FAIL with "unexpected keyword argument 'substatus'"

**Step 3: Add substatus column to Container model**

In `backend/models/container.py`, add after the `status` column (line 69):

```python
    # Granular provisioning substatus for frontend stepper
    substatus = Column(String, nullable=True, default=None)
```

Update the `CheckConstraint` in `__table_args__` to add a substatus constraint:

```python
    __table_args__ = (
        CheckConstraint(
            "status IN ('provisioning', 'running', 'stopped', 'error')",
            name="chk_container_status",
        ),
        CheckConstraint(
            "substatus IS NULL OR substatus IN ("
            "'efs_created', 'task_registered', 'service_created', "
            "'task_pending', 'gateway_healthy')",
            name="chk_container_substatus",
        ),
        Index("idx_containers_status", "status"),
        Index("idx_containers_gateway_token", "gateway_token", unique=True),
    )
```

**Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/unit/models/test_container.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
cd backend
git add models/container.py tests/unit/models/test_container.py
git commit -m "feat: add substatus column to Container model for provisioning progress"
```

---

### Task 2: Update ECS manager to write substatus during provisioning

**Files:**
- Modify: `backend/core/containers/ecs_manager.py:190-285`

**Step 1: Write a helper to update substatus**

In `create_user_service()`, we need to update the Container record's substatus at each provisioning step. The Container record is created/updated at the end (Step 4 of the current code), so we need to create the record early and update substatus as we go.

Refactor `create_user_service()` in `backend/core/containers/ecs_manager.py` — replace lines 190-285 with:

```python
    async def create_user_service(self, user_id: str, gateway_token: str, db: AsyncSession) -> str:
        """Create an ECS Service for a user with per-user EFS isolation.

        1. Creates/upserts Container DB record with status=provisioning
        2. Creates a per-user EFS access point → substatus=efs_created
        3. Registers a per-user task definition → substatus=task_registered
        4. Creates the ECS service → substatus=service_created

        On failure, rolls back created resources and sets status=error.

        Args:
            user_id: Clerk user ID.
            gateway_token: Auth token for the OpenClaw gateway HTTP API.
            db: Async database session.

        Returns:
            The ECS service name.

        Raises:
            EcsManagerError: If any step fails.
        """
        service_name = self._service_name(user_id)
        access_point_id = None
        task_def_arn = None

        # Create/upsert container record early so frontend can poll substatus
        result = await db.execute(select(Container).where(Container.user_id == user_id))
        container = result.scalar_one_or_none()
        if container:
            container.service_name = service_name
            container.gateway_token = gateway_token
            container.status = "provisioning"
            container.substatus = None
        else:
            container = Container(
                user_id=user_id,
                service_name=service_name,
                gateway_token=gateway_token,
                status="provisioning",
            )
            db.add(container)
        await db.commit()

        try:
            # Step 1: Create per-user EFS access point
            access_point_id = self._create_access_point(user_id)
            container.access_point_id = access_point_id
            container.substatus = "efs_created"
            await db.commit()

            # Step 2: Register per-user task definition with that access point
            task_def_arn = self._register_task_definition(access_point_id)
            container.task_definition_arn = task_def_arn
            container.substatus = "task_registered"
            await db.commit()

            # Step 3: Create ECS service with per-user task definition
            create_kwargs = dict(
                cluster=self._cluster,
                serviceName=service_name,
                taskDefinition=task_def_arn,
                desiredCount=1,
                launchType="FARGATE",
                networkConfiguration={
                    "awsvpcConfiguration": {
                        "subnets": self._subnets,
                        "securityGroups": self._security_groups,
                        "assignPublicIp": "DISABLED",
                    }
                },
                serviceRegistries=[{"registryArn": self._cloud_map_service_arn}],
            )
            # Only enable ECS Exec for non-production environments
            if settings.ENVIRONMENT != "prod":
                create_kwargs["enableExecuteCommand"] = True
            self._ecs.create_service(**create_kwargs)

            container.substatus = "service_created"
            await db.commit()

        except EcsManagerError:
            # Rollback already-created resources
            if task_def_arn:
                self._deregister_task_definition(task_def_arn)
            if access_point_id:
                self._delete_access_point(access_point_id)
            container.status = "error"
            container.substatus = None
            await db.commit()
            raise
        except Exception as e:
            # Rollback already-created resources
            if task_def_arn:
                self._deregister_task_definition(task_def_arn)
            if access_point_id:
                self._delete_access_point(access_point_id)
            container.status = "error"
            container.substatus = None
            await db.commit()
            logger.error(
                "Failed to create ECS service %s for user %s: %s",
                service_name,
                user_id,
                e,
            )
            raise EcsManagerError(f"Failed to create ECS service: {e}", user_id)

        logger.info("Created ECS service %s for user %s", service_name, user_id)
        return service_name
```

**Step 2: Update `resolve_running_container` to set substatus on transitions**

In the auto-transition block (around line 516), update to also set substatus:

```python
        # Auto-transition provisioning → running once the task is reachable
        if container.status == "provisioning" and self.is_healthy(ip):
            container.status = "running"
            container.substatus = "gateway_healthy"
            await db.commit()
            logger.info(
                "Container %s for user %s transitioned to running",
                container.service_name,
                user_id,
            )
```

**Step 3: Run full backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
cd backend
git add core/containers/ecs_manager.py
git commit -m "feat: write substatus during ECS provisioning for real-time progress tracking"
```

---

### Task 3: Include substatus in container status endpoint

**Files:**
- Modify: `backend/routers/container_rpc.py:134-150`

**Step 1: Update the `/status` endpoint response**

In `backend/routers/container_rpc.py`, update the `container_status` function to include `substatus`:

```python
    return {
        "service_name": container.service_name,
        "status": container.status,
        "substatus": container.substatus,
        "created_at": container.created_at.isoformat() if container.created_at else None,
        "updated_at": container.updated_at.isoformat() if container.updated_at else None,
        "region": settings.AWS_REGION,
    }
```

**Step 2: Run backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
cd backend
git add routers/container_rpc.py
git commit -m "feat: include substatus in container status endpoint response"
```

---

### Task 4: Update useContainerStatus hook to include substatus

**Files:**
- Modify: `frontend/src/hooks/useContainerStatus.ts:8-14`

**Step 1: Add substatus to ContainerStatus interface**

In `frontend/src/hooks/useContainerStatus.ts`, update the `ContainerStatus` interface:

```typescript
interface ContainerStatus {
  service_name: string;
  status: string;
  substatus: string | null;
  created_at: string | null;
  updated_at: string | null;
  region: string;
}
```

No other changes needed — the hook already returns the full response.

**Step 2: Build to verify**

Run: `cd frontend && npm run build`
Expected: PASS (no consumers reference `substatus` yet, so backward compatible)

**Step 3: Commit**

```bash
cd frontend
git add src/hooks/useContainerStatus.ts
git commit -m "feat: add substatus field to ContainerStatus interface"
```

---

### Task 5: Create the ProvisioningStepper component

**Files:**
- Create: `frontend/src/components/chat/ProvisioningStepper.tsx`

**Step 1: Create the component**

Create `frontend/src/components/chat/ProvisioningStepper.tsx`:

```tsx
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

/** Provisioning phases — each maps to a stepper step. */
type Phase = "payment" | "container" | "gateway" | "ready";

const STEPS: { phase: Phase; label: string; activeLabel: string }[] = [
  { phase: "payment", label: "Payment confirmed", activeLabel: "Confirming payment..." },
  { phase: "container", label: "Container started", activeLabel: "Starting your container..." },
  { phase: "gateway", label: "Gateway connected", activeLabel: "Connecting to AI gateway..." },
  { phase: "ready", label: "Ready", activeLabel: "Ready!" },
];

const TIMEOUT_MS = 120_000; // 2 minutes

export function ProvisioningStepper({
  children,
}: {
  children: React.ReactNode;
}) {
  const searchParams = useSearchParams();
  const { isLoading: billingLoading, isSubscribed, createCheckout, refresh: refreshBilling } = useBilling();
  const justSubscribed = searchParams.get("subscription") === "success";

  // Determine current phase
  const [phase, setPhase] = useState<Phase>("payment");
  const [startTime] = useState(() => Date.now());
  const [timedOut, setTimedOut] = useState(false);
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);

  // Poll billing every 2s until subscribed (only when waiting for payment)
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

    // Phase: payment confirmed, check container
    if (!container) {
      setPhase("container");
      return;
    }

    if (container.status === "error") {
      // Error state handled separately
      return;
    }

    if (container.status === "running" || container.substatus === "gateway_healthy") {
      // Container is running, check gateway
      if (gatewayHealth) {
        setPhase("ready");
      } else {
        setPhase("gateway");
      }
      return;
    }

    // Still provisioning
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

  // --- Render ---

  // Phase: ready — render children
  if (phase === "ready") {
    return <>{children}</>;
  }

  // Phase: loading billing
  if (billingLoading) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Phase: not subscribed and not just returning from checkout → show pricing
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

// --- Sub-components ---

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
          {/* Starter */}
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

          {/* Pro */}
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
```

**Step 2: Build to verify**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 3: Commit**

```bash
cd frontend
git add src/components/chat/ProvisioningStepper.tsx
git commit -m "feat: add ProvisioningStepper component with real-time status tracking"
```

---

### Task 6: Wire ProvisioningStepper into ChatLayout and remove old gates

**Files:**
- Modify: `frontend/src/components/chat/ChatLayout.tsx`

**Step 1: Replace gates in ChatLayout**

In `frontend/src/components/chat/ChatLayout.tsx`:

1. Replace imports (lines 7-9):

```typescript
// Remove these:
// import { SubscriptionGate } from "@/components/chat/SubscriptionGate";
// import { ContainerGate } from "@/components/chat/ContainerGate";
// import { AgentCreateDialog } from "@/components/chat/AgentCreateDialog";

// Add this:
import { ProvisioningStepper } from "@/components/chat/ProvisioningStepper";
```

2. Remove the `AgentCreateDialog` usage (lines 171-175) and the `createDialogOpen` state and the "New Agent" button (lines 122-131). Also remove the `createAgent` destructure from `useAgents()` and the `handleCreateAgent` function.

3. Replace the gates (lines 198-200):

```tsx
            <ProvisioningStepper>{children}</ProvisioningStepper>
```

**Step 2: The full updated ChatLayout should look like:**

```tsx
"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth, UserButton } from "@clerk/nextjs";
import { Bot, Trash2 } from "lucide-react";

import { ProvisioningStepper } from "@/components/chat/ProvisioningStepper";
import { useApi } from "@/lib/api";
import { useAgents, type Agent } from "@/hooks/useAgents";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { ControlSidebar } from "@/components/control/ControlSidebar";
import { cn } from "@/lib/utils";

interface ChatLayoutProps {
  children: React.ReactNode;
  activeView: "chat" | "control";
  onViewChange: (view: "chat" | "control") => void;
  activePanel?: string;
  onPanelChange?: (panel: string) => void;
}

function dispatchSelectAgentEvent(agentId: string): void {
  window.dispatchEvent(
    new CustomEvent("selectAgent", { detail: { agentId } }),
  );
}

function agentDisplayName(agent: Agent): string {
  return agent.identity?.name || agent.name || agent.id;
}

export function ChatLayout({
  children,
  activeView,
  onViewChange,
  activePanel,
  onPanelChange,
}: ChatLayoutProps): React.ReactElement {
  const { isSignedIn } = useAuth();
  const api = useApi();
  const { agents, defaultId, deleteAgent } = useAgents();
  const [userSelectedId, setUserSelectedId] = useState<string | null>(null);

  // Derive effective agent: user selection > default > first agent
  const currentAgentId = userSelectedId ?? defaultId ?? agents[0]?.id ?? null;

  useEffect(() => {
    if (!isSignedIn) return;

    api.syncUser().catch((err) => console.error("User sync failed:", err));
  }, [isSignedIn, api]);

  // Dispatch DOM event so page.tsx picks up the current agent (external system sync)
  const lastDispatchedRef = useRef<string | null>(null);
  useEffect(() => {
    if (currentAgentId && currentAgentId !== lastDispatchedRef.current) {
      lastDispatchedRef.current = currentAgentId;
      dispatchSelectAgentEvent(currentAgentId);
    }
  }, [currentAgentId]);

  function handleSelectAgent(agentId: string): void {
    setUserSelectedId(agentId);
    dispatchSelectAgentEvent(agentId);
  }

  async function handleDeleteAgent(agentId: string): Promise<void> {
    await deleteAgent(agentId);
    if (currentAgentId === agentId) {
      const remaining = agents.filter((a) => a.id !== agentId);
      if (remaining.length > 0) {
        handleSelectAgent(remaining[0].id);
      } else {
        setUserSelectedId(null);
      }
    }
  }

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden relative selection:bg-primary/20">
      {/* Global Grain Overlay */}
      <div className="fixed inset-0 z-0 pointer-events-none bg-noise opacity-[0.03]" />

      <div className="relative z-10 flex w-full h-full">
        <div className="w-64 hidden md:flex flex-col border-r border-border bg-sidebar/50 backdrop-blur-xl">
          {/* Tab Switcher */}
          <div className="flex border-b border-border">
            <button
              className={cn(
                "flex-1 px-3 py-2 text-xs font-medium uppercase tracking-wider transition-colors",
                activeView === "chat"
                  ? "text-foreground border-b-2 border-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
              onClick={() => onViewChange("chat")}
            >
              Chat
            </button>
            <button
              className={cn(
                "flex-1 px-3 py-2 text-xs font-medium uppercase tracking-wider transition-colors",
                activeView === "control"
                  ? "text-foreground border-b-2 border-primary"
                  : "text-muted-foreground hover:text-foreground"
              )}
              onClick={() => onViewChange("control")}
            >
              Control
            </button>
          </div>

          {activeView === "chat" ? (
            <>
              {/* Agent List */}
              <ScrollArea className="flex-1 px-3 py-2">
                <div className="space-y-1">
                  {agents.map((agent) => (
                    <div key={agent.id} className="group flex items-center">
                      <Button
                        variant="ghost"
                        className={cn(
                          "flex-1 justify-start gap-2 font-normal truncate transition-all h-auto py-1.5",
                          currentAgentId === agent.id
                            ? "bg-accent text-accent-foreground"
                            : "text-muted-foreground hover:text-foreground hover:bg-accent/50",
                        )}
                        onClick={() => handleSelectAgent(agent.id)}
                      >
                        <Bot className="h-4 w-4 flex-shrink-0 opacity-70" />
                        <div className="flex flex-col items-start min-w-0">
                          <span className="truncate w-full text-left">{agentDisplayName(agent)}</span>
                          {agent.model && (
                            <span className="text-[10px] text-muted-foreground/60 truncate w-full text-left">
                              {agent.model.split("/").pop()?.replace(/-v\d+:\d+$/, "") || agent.model}
                            </span>
                          )}
                        </div>
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-8 w-8 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
                        onClick={() => handleDeleteAgent(agent.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>
              </ScrollArea>
            </>
          ) : (
            <ControlSidebar activePanel={activePanel} onPanelChange={onPanelChange} />
          )}

          <div className="p-4 border-t border-border text-[10px] text-muted-foreground/40 text-center uppercase tracking-widest font-mono">
            Isol8 v0.1
          </div>
        </div>

        <main className="flex-1 min-h-0 flex flex-col relative bg-background/20">
          <header className="h-14 border-b border-border flex items-center justify-end gap-2 px-4 backdrop-blur-sm bg-background/20 absolute top-0 right-0 left-0 z-20">
            <UserButton
              appearance={{
                elements: {
                  avatarBox: "h-8 w-8",
                },
              }}
            />
          </header>

          <div className="flex-1 min-h-0 pt-14 flex flex-col overflow-y-auto">
            <ProvisioningStepper>{children}</ProvisioningStepper>
          </div>
        </main>
      </div>
    </div>
  );
}
```

**Step 3: Build to verify**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 4: Commit**

```bash
cd frontend
git add src/components/chat/ChatLayout.tsx
git commit -m "feat: replace SubscriptionGate + ContainerGate + AgentCreateDialog with ProvisioningStepper"
```

---

### Task 7: Run full test suites and verify

**Files:**
- No new files

**Step 1: Run backend tests**

Run: `cd backend && python -m pytest tests/ -v`
Expected: ALL PASS (the substatus column is nullable, so existing tests are unaffected)

**Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: PASS

**Step 3: Run frontend tests**

Run: `cd frontend && npm test`
Expected: PASS (AgentCreateDialog tests may need to be removed or updated if they fail — the component still exists as a file, it's just no longer imported in ChatLayout)

**Step 4: Check for unused imports/files**

The following files are now unused and can be deleted if desired:
- `frontend/src/components/chat/SubscriptionGate.tsx` — replaced by ProvisioningStepper
- `frontend/src/components/chat/ContainerGate.tsx` — replaced by ProvisioningStepper
- `frontend/src/components/chat/AgentCreateDialog.tsx` — removed from flow

However, do NOT delete them yet — they can serve as reference and be cleaned up in a future PR.

**Step 5: Commit any test fixes**

```bash
cd backend && git add -A && git commit -m "chore: fix any test adjustments for provisioning stepper" || true
cd ../frontend && git add -A && git commit -m "chore: fix any test adjustments for provisioning stepper" || true
```

---

### Task 8: Push both repos

**Step 1: Push backend**

```bash
cd backend && git push origin main
```

**Step 2: Push frontend**

```bash
cd frontend && git push origin main
```

**Step 3: Verify CI passes**

```bash
gh run list --repo Isol8AI/backend --limit 1
gh run list --repo Isol8AI/frontend --limit 1
```

Wait for both to pass. If CI fails, fix and push again.
