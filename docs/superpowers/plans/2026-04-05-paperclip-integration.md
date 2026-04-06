# Paperclip Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Paperclip (AI agent team orchestration) as an ECS sidecar for Pro/Enterprise users with a full custom UI at `/teams`.

**Architecture:** Paperclip runs as a second container in each pro/enterprise user's ECS Fargate task, sharing the network namespace with OpenClaw. The Isol8 backend proxies Paperclip's REST API for the frontend. The frontend adapts Paperclip's open-source React/shadcn UI to Isol8's design system. Paperclip connects to OpenClaw via `ws://localhost:18789` (sidecar networking).

**Tech Stack:** CDK (TypeScript), FastAPI (Python), Next.js 16 App Router (React 19), Tailwind CSS v4, shadcn/ui, SWR, httpx, Clerk auth.

**Spec:** `docs/superpowers/specs/2026-04-05-paperclip-integration-design.md`

---

## File Map

### Backend (Python)

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `apps/backend/core/config.py` | Add `PAPERCLIP_IMAGE`, `PAPERCLIP_PORT`, `BETTER_AUTH_SECRET`, `paperclip_enabled` to tier config |
| Modify | `apps/backend/core/repositories/container_repo.py` | No schema change needed — `update_fields` accepts arbitrary dict |
| Modify | `apps/backend/core/containers/ecs_manager.py` | Sidecar-aware task def registration, Paperclip enable/disable, board API key provisioning |
| Create | `apps/backend/routers/paperclip_api.py` | Status, enable, disable, proxy endpoints |
| Modify | `apps/backend/main.py` | Register paperclip router |

### Infrastructure (CDK)

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `apps/infra/lib/stacks/container-stack.ts` | Pro task definition with Paperclip sidecar, log group, security group rule |

### Frontend (TypeScript/React)

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `apps/frontend/src/app/teams/layout.tsx` | Teams page layout with sidebar |
| Create | `apps/frontend/src/app/teams/page.tsx` | Dashboard (redirects or renders default) |
| Create | `apps/frontend/src/app/teams/[...slug]/page.tsx` | Catch-all route for all teams sub-pages |
| Modify | `apps/frontend/src/middleware.ts` | Protect `/teams(.*)` route |
| Create | `apps/frontend/src/hooks/usePaperclip.ts` | SWR hooks for Paperclip API proxy |
| Create | `apps/frontend/src/components/teams/TeamsSidebar.tsx` | Sidebar nav for teams pages |
| Create | `apps/frontend/src/components/teams/TeamsRouter.tsx` | Route slug to panel component |
| Create | `apps/frontend/src/components/teams/PaperclipGuard.tsx` | Tier gate + enable CTA |
| Create | `apps/frontend/src/components/teams/panels/DashboardPanel.tsx` | Metric cards + charts |
| Create | `apps/frontend/src/components/teams/panels/AgentsPanel.tsx` | Agent list + detail |
| Create | `apps/frontend/src/components/teams/panels/AgentDetailPanel.tsx` | Agent detail tabs |
| Create | `apps/frontend/src/components/teams/panels/IssuesPanel.tsx` | Issue list + kanban |
| Create | `apps/frontend/src/components/teams/panels/IssueDetailPanel.tsx` | Issue detail |
| Create | `apps/frontend/src/components/teams/panels/GoalsPanel.tsx` | Goal tree |
| Create | `apps/frontend/src/components/teams/panels/RoutinesPanel.tsx` | Routine list + schedules |
| Create | `apps/frontend/src/components/teams/panels/ProjectsPanel.tsx` | Project list + detail |
| Create | `apps/frontend/src/components/teams/panels/CostsPanel.tsx` | Cost analytics |
| Create | `apps/frontend/src/components/teams/panels/ActivityPanel.tsx` | Activity feed |
| Create | `apps/frontend/src/components/teams/panels/OrgChartPanel.tsx` | SVG org chart |
| Create | `apps/frontend/src/components/teams/panels/InboxPanel.tsx` | Inbox with tabs |
| Create | `apps/frontend/src/components/teams/panels/ApprovalsPanel.tsx` | Approval cards |
| Create | `apps/frontend/src/components/teams/panels/SkillsPanel.tsx` | Skill browser |
| Create | `apps/frontend/src/components/teams/panels/SettingsPanel.tsx` | Company settings |
| Modify | `apps/frontend/src/components/control/panels/OverviewPanel.tsx` | Add "Teams" card linking to `/teams` |

---

## Task 1: Backend Config

**Files:**
- Modify: `apps/backend/core/config.py`

- [ ] **Step 1: Add Paperclip settings to Settings class**

In `apps/backend/core/config.py`, add after `OPENCLAW_IMAGE` (line 64):

```python
PAPERCLIP_IMAGE: str = os.getenv("PAPERCLIP_IMAGE", "ghcr.io/paperclipai/paperclip:latest")
PAPERCLIP_PORT: int = int(os.getenv("PAPERCLIP_PORT", "3100"))
BETTER_AUTH_SECRET: str = os.getenv("BETTER_AUTH_SECRET", "")
```

- [ ] **Step 2: Add `paperclip_enabled` to TIER_CONFIG**

Add `"paperclip_enabled": False` to `free` and `starter` dicts, `"paperclip_enabled": True` to `pro` and `enterprise` dicts. For example in the `free` tier (after `"scale_to_zero": True`):

```python
"paperclip_enabled": False,
```

And in the `pro` tier (after `"scale_to_zero": False`):

```python
"paperclip_enabled": True,
```

Same for `enterprise`.

- [ ] **Step 3: Verify config loads**

Run: `cd apps/backend && python -c "from core.config import settings, TIER_CONFIG; print(settings.PAPERCLIP_PORT); print(TIER_CONFIG['pro']['paperclip_enabled'])"`

Expected: `3100` and `True`

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/config.py
git commit -m "feat(paperclip): add Paperclip config settings and tier gating"
```

---

## Task 2: CDK — Pro Task Definition with Sidecar

**Files:**
- Modify: `apps/infra/lib/stacks/container-stack.ts`

- [ ] **Step 1: Add Paperclip log group**

After the `openclawLogGroup` definition (line 174), add:

```typescript
const paperclipLogGroup = new cdk.aws_logs.LogGroup(this, "PaperclipLogGroup", {
  logGroupName: `/isol8/${env}/paperclip`,
  retention: cdk.aws_logs.RetentionDays.TWO_WEEKS,
  removalPolicy: cdk.RemovalPolicy.DESTROY,
});
```

- [ ] **Step 2: Create pro task definition**

After the existing `openclawTaskDef` block (after line 238), add a second task definition:

```typescript
// Pro/Enterprise task definition — OpenClaw + Paperclip sidecar
// CPU/memory are set to pro-tier defaults; the backend's _register_task_definition
// adjusts these per-user when cloning for actual container provisioning.
const proTaskDef = new ecs.FargateTaskDefinition(this, "ProTaskDef", {
  family: `isol8-${env}-openclaw-pro`,
  cpu: 1536,
  memoryLimitMiB: 3072,
  taskRole: this.taskRole,
  executionRole: this.taskExecutionRole,
});

// Add the same OpenClaw container to the pro task def
const proOpenclawContainer = proTaskDef.addContainer("openclaw", {
  image: ecs.ContainerImage.fromRegistry("alpine/openclaw:2026.3.24"),
  essential: true,
  command: ["sh", "-c", startupCommand],
  user: "0:0",
  workingDirectory: "/home/node",
  environment: {
    HOME: "/home/node",
    CHOKIDAR_USEPOLLING: "true",
  },
  portMappings: [{ containerPort: 18789, protocol: ecs.Protocol.TCP }],
  logging: ecs.LogDrivers.awsLogs({
    logGroup: openclawLogGroup,
    streamPrefix: "openclaw",
  }),
});

proOpenclawContainer.addMountPoints({
  containerPath: "/home/node/.openclaw",
  sourceVolume: "openclaw-workspace",
  readOnly: false,
});

// Paperclip sidecar container
proTaskDef.addContainer("paperclip", {
  image: ecs.ContainerImage.fromRegistry("ghcr.io/paperclipai/paperclip:latest"),
  essential: false,
  cpu: 512,
  memoryLimitMiB: 1024,
  environment: {
    PAPERCLIP_DEPLOYMENT_MODE: "authenticated",
    PAPERCLIP_DEPLOYMENT_EXPOSURE: "private",
    HOST: "0.0.0.0",
    PORT: "3100",
  },
  secrets: {
    BETTER_AUTH_SECRET: ecs.Secret.fromSecretsManager(
      cdk.aws_secretsmanager.Secret.fromSecretNameV2(
        this, "BetterAuthSecret", `isol8/${env}/better-auth-secret`
      )
    ),
  },
  portMappings: [{ containerPort: 3100, protocol: ecs.Protocol.TCP }],
  logging: ecs.LogDrivers.awsLogs({
    logGroup: paperclipLogGroup,
    streamPrefix: "paperclip",
  }),
});

// Shared EFS volume for pro task def
proTaskDef.addVolume({
  name: "openclaw-workspace",
  efsVolumeConfiguration: {
    fileSystemId: this.efsFileSystem.fileSystemId,
    transitEncryption: "ENABLED",
    authorizationConfig: { iam: "ENABLED" },
  },
});
```

- [ ] **Step 3: Add security group rule for port 3100**

After the existing security group ingress rules for port 18789, add:

```typescript
this.containerSecurityGroup.addIngressRule(
  backendSecurityGroup,
  ec2.Port.tcp(3100),
  "Allow backend to reach Paperclip sidecar",
);
```

Note: identify how `backendSecurityGroup` is referenced in the stack — it may be passed as a prop or imported. Follow the existing pattern for the port 18789 rule.

- [ ] **Step 4: Export pro task definition ARN**

Ensure the pro task definition ARN is accessible. Add a CfnOutput or expose via stack props following the existing pattern for `openclawTaskDef`.

- [ ] **Step 5: Create the Secrets Manager secret**

Either via CDK or manually create `isol8/${env}/better-auth-secret` in Secrets Manager with a random string value. This is a one-time setup.

- [ ] **Step 6: Verify CDK synth**

Run: `cd apps/infra && npx cdk synth --no-staging 2>&1 | head -20`

Expected: successful synthesis with no errors.

- [ ] **Step 7: Commit**

```bash
git add apps/infra/lib/stacks/container-stack.ts
git commit -m "feat(paperclip): add pro task definition with Paperclip sidecar"
```

---

## Task 3: EcsManager — Sidecar-Aware Provisioning

**Files:**
- Modify: `apps/backend/core/containers/ecs_manager.py`
- Modify: `apps/backend/core/config.py` (add `ECS_PRO_TASK_DEFINITION` setting)

- [ ] **Step 1: Add pro task definition setting**

In `apps/backend/core/config.py`, add to `Settings`:

```python
ECS_PRO_TASK_DEFINITION: str = os.getenv("ECS_PRO_TASK_DEFINITION", "")
```

- [ ] **Step 2: Add `_register_task_definition_with_sidecar` method**

In `apps/backend/core/containers/ecs_manager.py`, add a new method after `_register_task_definition` (line 188). This clones from the pro base task definition instead of the standard one:

```python
def _register_task_definition_with_sidecar(self, access_point_id: str) -> str:
    """Clone the pro (sidecar) base task definition with a per-user EFS access point.

    Same as _register_task_definition but uses the pro task definition family
    which includes the Paperclip sidecar container.
    """
    pro_task_def = settings.ECS_PRO_TASK_DEFINITION
    if not pro_task_def:
        raise EcsManagerError("ECS_PRO_TASK_DEFINITION not configured", user_id="")
    try:
        desc_resp = self._ecs.describe_task_definition(taskDefinition=pro_task_def)
        base = desc_resp["taskDefinition"]

        volumes = []
        for vol in base.get("volumes", []):
            vol_copy = dict(vol)
            efs_config = vol_copy.get("efsVolumeConfiguration")
            if efs_config:
                efs_copy = dict(efs_config)
                auth_config = dict(efs_copy.get("authorizationConfig", {}))
                auth_config["accessPointId"] = access_point_id
                efs_copy["authorizationConfig"] = auth_config
                vol_copy["efsVolumeConfiguration"] = efs_copy
            volumes.append(vol_copy)

        reg_kwargs = dict(
            family=base["family"],
            taskRoleArn=base.get("taskRoleArn", ""),
            executionRoleArn=base.get("executionRoleArn", ""),
            networkMode=base.get("networkMode", "awsvpc"),
            containerDefinitions=base["containerDefinitions"],
            volumes=volumes,
            requiresCompatibilities=base.get("requiresCompatibilities", ["FARGATE"]),
            cpu=base.get("cpu", "1536"),
            memory=base.get("memory", "3072"),
        )
        if base.get("runtimePlatform"):
            reg_kwargs["runtimePlatform"] = base["runtimePlatform"]

        reg_resp = self._ecs.register_task_definition(**reg_kwargs)
        task_def_arn = reg_resp["taskDefinition"]["taskDefinitionArn"]
        logger.info("Registered pro (sidecar) task definition %s", task_def_arn)
        return task_def_arn
    except Exception as e:
        raise EcsManagerError(
            f"Failed to register pro task definition: {e}",
            user_id="",
        )
```

- [ ] **Step 3: Add Paperclip enable/disable methods**

Add these methods to `EcsManager`:

```python
async def enable_paperclip(self, owner_id: str) -> dict:
    """Enable Paperclip sidecar for a user by swapping to the pro task definition.

    1. Get existing container record
    2. Register new task def from pro family with user's access point
    3. Update ECS service with new task def + force new deployment
    4. Wait for Paperclip to be healthy
    5. Create board API key via Paperclip API
    6. Store board API key in DynamoDB
    """
    from core.repositories import container_repo

    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise EcsManagerError("No container found", user_id=owner_id)

    access_point_id = container.get("access_point_id")
    if not access_point_id:
        raise EcsManagerError("No access point found", user_id=owner_id)

    # Register pro task def with sidecar
    task_def_arn = self._register_task_definition_with_sidecar(access_point_id)

    # Update service with new task def
    self._ecs.update_service(
        cluster=self._cluster,
        service=container["service_name"],
        taskDefinition=task_def_arn,
        forceNewDeployment=True,
    )

    # Update container record
    await container_repo.update_fields(owner_id, {
        "task_definition_arn": task_def_arn,
        "paperclip_enabled": True,
    })

    # Wait for Paperclip healthy + create board API key (async, may take time)
    # The caller should poll /paperclip/status for readiness
    return {"status": "enabling", "task_definition_arn": task_def_arn}


async def disable_paperclip(self, owner_id: str) -> dict:
    """Disable Paperclip by swapping back to the standard task definition."""
    from core.repositories import container_repo

    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise EcsManagerError("No container found", user_id=owner_id)

    access_point_id = container.get("access_point_id")
    if not access_point_id:
        raise EcsManagerError("No access point found", user_id=owner_id)

    # Register standard task def (no sidecar)
    task_def_arn = self._register_task_definition(access_point_id)

    self._ecs.update_service(
        cluster=self._cluster,
        service=container["service_name"],
        taskDefinition=task_def_arn,
        forceNewDeployment=True,
    )

    await container_repo.update_fields(owner_id, {
        "task_definition_arn": task_def_arn,
        "paperclip_enabled": False,
        "paperclip_board_key": None,
    })

    return {"status": "disabling", "task_definition_arn": task_def_arn}
```

- [ ] **Step 4: Add Paperclip board key provisioning method**

```python
async def provision_paperclip_board_key(self, owner_id: str) -> str:
    """Create a board API key in Paperclip and store it.

    Called after Paperclip sidecar is healthy. Uses Paperclip's
    bootstrap flow to create the initial admin user and API key.
    """
    import httpx
    from core.repositories import container_repo

    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise EcsManagerError("No container found", user_id=owner_id)

    ip = await self.discover_ip(owner_id)
    if not ip:
        raise EcsManagerError("Cannot resolve container IP", user_id=owner_id)

    paperclip_url = f"http://{ip}:{settings.PAPERCLIP_PORT}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Step 1: Check health
        health_resp = await client.get(f"{paperclip_url}/api/health")
        health_resp.raise_for_status()

        # Step 2: Sign up the board user (first user becomes admin via bootstrap)
        signup_resp = await client.post(
            f"{paperclip_url}/api/auth/sign-up/email",
            json={
                "name": "Isol8 Board",
                "email": f"{owner_id}@isol8.local",
                "password": settings.BETTER_AUTH_SECRET,
            },
        )
        signup_resp.raise_for_status()

        # Step 3: Sign in to get session cookie
        signin_resp = await client.post(
            f"{paperclip_url}/api/auth/sign-in/email",
            json={
                "email": f"{owner_id}@isol8.local",
                "password": settings.BETTER_AUTH_SECRET,
            },
        )
        signin_resp.raise_for_status()

        # Step 4: Create a CLI auth challenge to get a board API key
        # The challenge flow creates a pcp_board_* token
        challenge_resp = await client.post(
            f"{paperclip_url}/api/auth/cli/challenge",
            cookies=signin_resp.cookies,
        )
        challenge_resp.raise_for_status()
        challenge = challenge_resp.json()

        # Step 5: Approve the challenge
        approve_resp = await client.post(
            f"{paperclip_url}/api/auth/cli/approve/{challenge['id']}",
            cookies=signin_resp.cookies,
        )
        approve_resp.raise_for_status()
        board_key = approve_resp.json().get("token", "")

    # Store the board key
    await container_repo.update_fields(owner_id, {
        "paperclip_board_key": board_key,
    })

    logger.info("Provisioned Paperclip board key for %s", owner_id)
    return board_key
```

Note: The exact Paperclip API endpoints for CLI auth challenge/approve may differ. Verify against Paperclip's `server/src/services/board-auth.ts` and `server/src/app.ts` route definitions. The pattern above follows what the research found, but the exact paths need confirmation during implementation.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/config.py apps/backend/core/containers/ecs_manager.py
git commit -m "feat(paperclip): sidecar-aware task def + enable/disable + board key provisioning"
```

---

## Task 4: Paperclip API Proxy Router

**Files:**
- Create: `apps/backend/routers/paperclip_api.py`

- [ ] **Step 1: Create the router file**

```python
"""
Paperclip API proxy router.

Provides status, enable/disable, and proxy endpoints for the Paperclip
sidecar. All requests are authenticated via Clerk and tier-gated to
pro/enterprise users.

The proxy forwards requests to the user's Paperclip container at
http://{container_ip}:3100/api/{path} using the stored Board API Key.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from core.auth import AuthContext, get_current_user, resolve_owner_id
from core.config import settings, TIER_CONFIG
from core.containers import get_ecs_manager
from core.repositories import container_repo

logger = logging.getLogger(__name__)

router = APIRouter()

_PROXY_TIMEOUT = 30.0


def _check_tier_eligible(tier: str) -> None:
    """Raise 403 if the user's tier doesn't support Paperclip."""
    if not TIER_CONFIG.get(tier, {}).get("paperclip_enabled", False):
        raise HTTPException(status_code=403, detail="Paperclip requires Pro or Enterprise tier")


async def _get_owner_and_tier(auth: AuthContext = Depends(get_current_user)):
    """Resolve owner_id and tier from auth context."""
    owner_id = resolve_owner_id(auth)
    container = await container_repo.get_by_owner_id(owner_id)
    tier = container.get("tier", "free") if container else "free"
    return owner_id, tier, container


@router.get("/status")
async def paperclip_status(
    auth: AuthContext = Depends(get_current_user),
):
    """Check if Paperclip is enabled and healthy for the current user."""
    owner_id = resolve_owner_id(auth)
    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        return {"enabled": False, "healthy": False, "eligible": False}

    tier = container.get("tier", "free")
    eligible = TIER_CONFIG.get(tier, {}).get("paperclip_enabled", False)
    enabled = container.get("paperclip_enabled", False)

    if not enabled:
        return {"enabled": False, "healthy": False, "eligible": eligible}

    # Check Paperclip health
    healthy = False
    try:
        ecs = get_ecs_manager()
        ip = await ecs.discover_ip(owner_id)
        if ip:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"http://{ip}:{settings.PAPERCLIP_PORT}/api/health")
                healthy = resp.status_code == 200
    except Exception:
        pass

    return {"enabled": True, "healthy": healthy, "eligible": eligible}


@router.post("/enable")
async def enable_paperclip(
    auth: AuthContext = Depends(get_current_user),
):
    """Enable Paperclip sidecar for the current user."""
    owner_id = resolve_owner_id(auth)
    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")

    tier = container.get("tier", "free")
    _check_tier_eligible(tier)

    if container.get("paperclip_enabled"):
        return {"status": "already_enabled"}

    ecs = get_ecs_manager()
    result = await ecs.enable_paperclip(owner_id)
    return result


@router.post("/disable")
async def disable_paperclip(
    auth: AuthContext = Depends(get_current_user),
):
    """Disable Paperclip sidecar for the current user."""
    owner_id = resolve_owner_id(auth)
    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")

    if not container.get("paperclip_enabled"):
        return {"status": "already_disabled"}

    ecs = get_ecs_manager()
    result = await ecs.disable_paperclip(owner_id)
    return result


@router.api_route("/proxy/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_to_paperclip(
    path: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
):
    """Proxy requests to the user's Paperclip container.

    Forwards to http://{container_ip}:3100/api/{path} with the
    stored Board API Key in the Authorization header.
    """
    owner_id = resolve_owner_id(auth)
    container = await container_repo.get_by_owner_id(owner_id)
    if not container:
        raise HTTPException(status_code=404, detail="No container found")
    if not container.get("paperclip_enabled"):
        raise HTTPException(status_code=400, detail="Paperclip is not enabled")

    board_key = container.get("paperclip_board_key")
    if not board_key:
        raise HTTPException(status_code=503, detail="Paperclip board key not provisioned yet")

    ecs = get_ecs_manager()
    ip = await ecs.discover_ip(owner_id)
    if not ip:
        raise HTTPException(status_code=502, detail="Cannot resolve container IP")

    upstream_url = f"http://{ip}:{settings.PAPERCLIP_PORT}/api/{path}"

    # Read request body
    body = await request.body()

    # Forward headers (filter out host and auth — we inject our own auth)
    forward_headers = {}
    if body:
        content_type = request.headers.get("content-type")
        if content_type:
            forward_headers["content-type"] = content_type

    forward_headers["authorization"] = f"Bearer {board_key}"

    async with httpx.AsyncClient(timeout=_PROXY_TIMEOUT) as client:
        try:
            resp = await client.request(
                method=request.method,
                url=upstream_url,
                content=body if body else None,
                headers=forward_headers,
            )
        except httpx.ConnectError:
            raise HTTPException(status_code=502, detail="Paperclip sidecar not reachable")
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Paperclip sidecar timeout")

    # Return Paperclip's response
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type=resp.headers.get("content-type", "application/json"),
    )
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/routers/paperclip_api.py
git commit -m "feat(paperclip): add Paperclip API proxy router"
```

---

## Task 5: Register Router

**Files:**
- Modify: `apps/backend/main.py`

- [ ] **Step 1: Import and register the router**

Add with the other router imports (around line 189):

```python
from routers import paperclip_api
```

Add with the other `include_router` calls:

```python
app.include_router(paperclip_api.router, prefix="/api/v1/paperclip", tags=["paperclip"])
```

- [ ] **Step 2: Verify the app starts**

Run: `cd apps/backend && python -c "from main import app; print([r.path for r in app.routes if 'paperclip' in str(r.path)])"`

Expected: Routes containing `/api/v1/paperclip`

- [ ] **Step 3: Commit**

```bash
git add apps/backend/main.py
git commit -m "feat(paperclip): register Paperclip router"
```

---

## Task 6: Frontend — Middleware + Route Setup

**Files:**
- Modify: `apps/frontend/src/middleware.ts`
- Create: `apps/frontend/src/app/teams/layout.tsx`
- Create: `apps/frontend/src/app/teams/page.tsx`
- Create: `apps/frontend/src/app/teams/[...slug]/page.tsx`

- [ ] **Step 1: Protect `/teams` route**

In `apps/frontend/src/middleware.ts`, add `/teams(.*)` to the route matcher:

```typescript
const isProtectedRoute = createRouteMatcher(["/chat(.*)", "/onboarding", "/settings(.*)", "/teams(.*)"]);
```

- [ ] **Step 2: Create teams layout**

```typescript
// apps/frontend/src/app/teams/layout.tsx
"use client";

import { TeamsSidebar } from "@/components/teams/TeamsSidebar";
import { PaperclipGuard } from "@/components/teams/PaperclipGuard";

export default function TeamsLayout({ children }: { children: React.ReactNode }) {
  return (
    <PaperclipGuard>
      <div className="flex h-screen bg-[#f5f3ee]">
        <aside className="w-60 flex-shrink-0 border-r border-[#e5e0d5] bg-[#faf8f4] flex flex-col">
          <TeamsSidebar />
        </aside>
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </PaperclipGuard>
  );
}
```

- [ ] **Step 3: Create teams index page**

```typescript
// apps/frontend/src/app/teams/page.tsx
import { TeamsRouter } from "@/components/teams/TeamsRouter";

export default function TeamsPage() {
  return <TeamsRouter slug={[]} />;
}
```

- [ ] **Step 4: Create catch-all route**

```typescript
// apps/frontend/src/app/teams/[...slug]/page.tsx
import { TeamsRouter } from "@/components/teams/TeamsRouter";

export default function TeamsSlugPage({ params }: { params: Promise<{ slug: string[] }> }) {
  // Next.js 16 async params
  return <TeamsSlugInner paramsPromise={params} />;
}

import { use } from "react";

function TeamsSlugInner({ paramsPromise }: { paramsPromise: Promise<{ slug: string[] }> }) {
  const { slug } = use(paramsPromise);
  return <TeamsRouter slug={slug} />;
}
```

- [ ] **Step 5: Commit**

```bash
git add apps/frontend/src/middleware.ts apps/frontend/src/app/teams/
git commit -m "feat(paperclip): add /teams route with layout and catch-all"
```

---

## Task 7: Frontend — usePaperclip Hook

**Files:**
- Create: `apps/frontend/src/hooks/usePaperclip.ts`

- [ ] **Step 1: Create the hook file**

```typescript
// apps/frontend/src/hooks/usePaperclip.ts
"use client";

import useSWR from "swr";
import { useApi } from "@/lib/api";
import { useCallback, useMemo } from "react";

interface PaperclipStatus {
  enabled: boolean;
  healthy: boolean;
  eligible: boolean;
}

export function usePaperclipStatus() {
  const api = useApi();
  const { data, error, isLoading, mutate } = useSWR<PaperclipStatus>(
    "/paperclip/status",
    () => api.get("/paperclip/status"),
    { dedupingInterval: 10_000 },
  );
  return {
    status: data ?? { enabled: false, healthy: false, eligible: false },
    isLoading,
    error,
    refresh: mutate,
  };
}

export function usePaperclipApi<T = unknown>(path: string | null) {
  const api = useApi();
  const { data, error, isLoading, mutate } = useSWR<T>(
    path ? `/paperclip/proxy/${path}` : null,
    () => api.get(`/paperclip/proxy/${path}`),
    { dedupingInterval: 5_000 },
  );
  return { data, error, isLoading, refresh: mutate };
}

export function usePaperclipMutation() {
  const api = useApi();

  const post = useCallback(
    async <T = unknown>(path: string, body?: unknown): Promise<T> => {
      return api.post(`/paperclip/proxy/${path}`, body) as Promise<T>;
    },
    [api],
  );

  const put = useCallback(
    async <T = unknown>(path: string, body?: unknown): Promise<T> => {
      return api.put(`/paperclip/proxy/${path}`, body) as Promise<T>;
    },
    [api],
  );

  const patch = useCallback(
    async <T = unknown>(path: string, body?: unknown): Promise<T> => {
      // Use post with method override or add patch to useApi
      const resp = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/paperclip/proxy/${path}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: body ? JSON.stringify(body) : undefined,
        },
      );
      return resp.json();
    },
    [],
  );

  const del = useCallback(
    async <T = unknown>(path: string): Promise<T> => {
      return api.del(`/paperclip/proxy/${path}`) as Promise<T>;
    },
    [api],
  );

  return useMemo(() => ({ post, put, patch, del }), [post, put, patch, del]);
}

export function usePaperclipEnable() {
  const api = useApi();
  const { refresh } = usePaperclipStatus();

  const enable = useCallback(async () => {
    const result = await api.post("/paperclip/enable");
    await refresh();
    return result;
  }, [api, refresh]);

  const disable = useCallback(async () => {
    const result = await api.post("/paperclip/disable");
    await refresh();
    return result;
  }, [api, refresh]);

  return { enable, disable };
}
```

Note: The `patch` method above is a workaround since `useApi` may not have a `patch` method. During implementation, check if `useApi` supports PATCH — if so, use it directly. If not, either add it to `api.ts` or use the authenticated fetch approach shown above.

- [ ] **Step 2: Commit**

```bash
git add apps/frontend/src/hooks/usePaperclip.ts
git commit -m "feat(paperclip): add usePaperclip SWR hooks"
```

---

## Task 8: Frontend — PaperclipGuard + TeamsSidebar + TeamsRouter

**Files:**
- Create: `apps/frontend/src/components/teams/PaperclipGuard.tsx`
- Create: `apps/frontend/src/components/teams/TeamsSidebar.tsx`
- Create: `apps/frontend/src/components/teams/TeamsRouter.tsx`

- [ ] **Step 1: Create PaperclipGuard**

This component gates the `/teams` page by tier and Paperclip enabled status:

```typescript
// apps/frontend/src/components/teams/PaperclipGuard.tsx
"use client";

import { usePaperclipStatus, usePaperclipEnable } from "@/hooks/usePaperclip";
import { useBilling } from "@/hooks/useBilling";
import { Button } from "@/components/ui/button";
import { Users, ArrowRight, Loader2 } from "lucide-react";
import { useState } from "react";
import Link from "next/link";

export function PaperclipGuard({ children }: { children: React.ReactNode }) {
  const { status, isLoading: statusLoading } = usePaperclipStatus();
  const { planTier, isLoading: billingLoading } = useBilling();
  const { enable } = usePaperclipEnable();
  const [enabling, setEnabling] = useState(false);

  if (statusLoading || billingLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#f5f3ee]">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  // Not eligible (free/starter)
  if (!status.eligible) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#f5f3ee]">
        <div className="max-w-md text-center space-y-4">
          <Users className="h-12 w-12 mx-auto text-[#8a8578]" />
          <h2 className="text-xl font-semibold text-[#1a1a1a]">Teams</h2>
          <p className="text-[#8a8578]">
            Orchestrate teams of AI agents with org charts, task management,
            scheduled execution, and budgets. Available on Pro and Enterprise plans.
          </p>
          <Link href="/chat">
            <Button variant="outline">
              <ArrowRight className="h-4 w-4 mr-2" />
              Back to Chat
            </Button>
          </Link>
        </div>
      </div>
    );
  }

  // Eligible but not enabled
  if (!status.enabled) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#f5f3ee]">
        <div className="max-w-md text-center space-y-4">
          <Users className="h-12 w-12 mx-auto text-[#8a8578]" />
          <h2 className="text-xl font-semibold text-[#1a1a1a]">Enable Teams</h2>
          <p className="text-[#8a8578]">
            Add Paperclip to your container to orchestrate teams of AI agents.
            This will restart your container with the Paperclip sidecar.
          </p>
          <Button
            onClick={async () => {
              setEnabling(true);
              try {
                await enable();
              } finally {
                setEnabling(false);
              }
            }}
            disabled={enabling}
          >
            {enabling ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Users className="h-4 w-4 mr-2" />
            )}
            Enable Teams
          </Button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
```

- [ ] **Step 2: Create TeamsSidebar**

Reference Paperclip's `ui/src/components/Sidebar.tsx` for the structure. Adapt to Isol8 styling:

```typescript
// apps/frontend/src/components/teams/TeamsSidebar.tsx
"use client";

import {
  LayoutDashboard,
  Inbox,
  CircleDot,
  Repeat,
  Target,
  FolderOpen,
  Bot,
  Network,
  Boxes,
  DollarSign,
  History,
  Settings,
  ArrowLeft,
  CheckCircle2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";

const NAV_SECTIONS = [
  {
    items: [
      { key: "", label: "Dashboard", icon: LayoutDashboard },
      { key: "inbox", label: "Inbox", icon: Inbox },
    ],
  },
  {
    label: "Work",
    items: [
      { key: "issues", label: "Issues", icon: CircleDot },
      { key: "routines", label: "Routines", icon: Repeat },
      { key: "goals", label: "Goals", icon: Target },
    ],
  },
  {
    label: "Manage",
    items: [
      { key: "projects", label: "Projects", icon: FolderOpen },
      { key: "agents", label: "Agents", icon: Bot },
      { key: "approvals", label: "Approvals", icon: CheckCircle2 },
    ],
  },
  {
    label: "Company",
    items: [
      { key: "org", label: "Org Chart", icon: Network },
      { key: "skills", label: "Skills", icon: Boxes },
      { key: "costs", label: "Costs", icon: DollarSign },
      { key: "activity", label: "Activity", icon: History },
      { key: "settings", label: "Settings", icon: Settings },
    ],
  },
];

export function TeamsSidebar() {
  const pathname = usePathname();
  const router = useRouter();

  const activeKey = pathname === "/teams" ? "" : pathname.replace("/teams/", "").split("/")[0];

  return (
    <>
      <div className="p-3 border-b border-[#e5e0d5]">
        <Link href="/chat">
          <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-[#8a8578] hover:text-[#1a1a1a]">
            <ArrowLeft className="h-4 w-4" />
            Back to Chat
          </Button>
        </Link>
      </div>
      <ScrollArea className="flex-1 px-3 py-2">
        {NAV_SECTIONS.map((section, si) => (
          <div key={si} className="mb-3">
            {section.label && (
              <div className="px-2 py-1.5 text-xs font-medium text-[#b0a99a] uppercase tracking-wider">
                {section.label}
              </div>
            )}
            <div className="space-y-0.5">
              {section.items.map(({ key, label, icon: Icon }) => (
                <Button
                  key={key}
                  variant="ghost"
                  className={cn(
                    "w-full justify-start gap-2 font-normal h-auto py-1.5 text-[13px]",
                    activeKey === key
                      ? "bg-white text-[#1a1a1a] shadow-sm"
                      : "text-[#8a8578] hover:text-[#1a1a1a] hover:bg-white/60",
                  )}
                  onClick={() => router.push(key ? `/teams/${key}` : "/teams")}
                >
                  <Icon className="h-4 w-4 flex-shrink-0 opacity-70" />
                  <span className="truncate">{label}</span>
                </Button>
              ))}
            </div>
          </div>
        ))}
      </ScrollArea>
    </>
  );
}
```

- [ ] **Step 3: Create TeamsRouter**

```typescript
// apps/frontend/src/components/teams/TeamsRouter.tsx
"use client";

import { DashboardPanel } from "./panels/DashboardPanel";
import { InboxPanel } from "./panels/InboxPanel";
import { IssuesPanel } from "./panels/IssuesPanel";
import { IssueDetailPanel } from "./panels/IssueDetailPanel";
import { RoutinesPanel } from "./panels/RoutinesPanel";
import { GoalsPanel } from "./panels/GoalsPanel";
import { ProjectsPanel } from "./panels/ProjectsPanel";
import { AgentsPanel } from "./panels/AgentsPanel";
import { AgentDetailPanel } from "./panels/AgentDetailPanel";
import { ApprovalsPanel } from "./panels/ApprovalsPanel";
import { OrgChartPanel } from "./panels/OrgChartPanel";
import { SkillsPanel } from "./panels/SkillsPanel";
import { CostsPanel } from "./panels/CostsPanel";
import { ActivityPanel } from "./panels/ActivityPanel";
import { SettingsPanel } from "./panels/SettingsPanel";

interface TeamsRouterProps {
  slug: string[];
}

export function TeamsRouter({ slug }: TeamsRouterProps) {
  const [root, ...rest] = slug;

  if (!root) return <DashboardPanel />;

  switch (root) {
    case "inbox":
      return <InboxPanel />;
    case "issues":
      return rest[0] ? <IssueDetailPanel issueId={rest[0]} /> : <IssuesPanel />;
    case "routines":
      return <RoutinesPanel routineId={rest[0]} />;
    case "goals":
      return <GoalsPanel goalId={rest[0]} />;
    case "projects":
      return <ProjectsPanel projectId={rest[0]} />;
    case "agents":
      if (rest[0] === "new") return <AgentDetailPanel isNew />;
      return rest[0] ? <AgentDetailPanel agentId={rest[0]} tab={rest[1]} runId={rest[2] === "runs" ? rest[3] : undefined} /> : <AgentsPanel />;
    case "approvals":
      return <ApprovalsPanel approvalId={rest[0]} />;
    case "org":
      return <OrgChartPanel />;
    case "skills":
      return <SkillsPanel />;
    case "costs":
      return <CostsPanel />;
    case "activity":
      return <ActivityPanel />;
    case "settings":
      return <SettingsPanel />;
    default:
      return <DashboardPanel />;
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add apps/frontend/src/components/teams/
git commit -m "feat(paperclip): add PaperclipGuard, TeamsSidebar, TeamsRouter"
```

---

## Task 9: Frontend — Dashboard Panel

**Files:**
- Create: `apps/frontend/src/components/teams/panels/DashboardPanel.tsx`

- [ ] **Step 1: Create DashboardPanel**

Reference Paperclip's `ui/src/pages/Dashboard.tsx`. The dashboard shows 4 metric cards and recent activity. All data comes through the proxy:

```typescript
// apps/frontend/src/components/teams/panels/DashboardPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { LayoutDashboard, Bot, CircleDot, DollarSign, CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";

interface DashboardData {
  agents: { total: number; active: number };
  issues: { inProgress: number; total: number };
  costs: { monthSpendCents: number };
  approvals: { pending: number };
  recentActivity: Array<{
    id: string;
    type: string;
    description: string;
    createdAt: string;
  }>;
}

function MetricCard({
  label,
  value,
  subValue,
  icon: Icon,
  href,
}: {
  label: string;
  value: string | number;
  subValue?: string;
  icon: React.ComponentType<{ className?: string }>;
  href: string;
}) {
  return (
    <Link href={href}>
      <div className="rounded-lg border border-[#e5e0d5] bg-white p-4 hover:shadow-sm transition-shadow">
        <div className="flex items-center gap-3">
          <Icon className="h-5 w-5 text-[#8a8578]" />
          <div>
            <div className="text-2xl font-semibold text-[#1a1a1a]">{value}</div>
            <div className="text-sm text-[#8a8578]">{label}</div>
            {subValue && <div className="text-xs text-[#b0a99a]">{subValue}</div>}
          </div>
        </div>
      </div>
    </Link>
  );
}

export function DashboardPanel() {
  const { data, isLoading } = usePaperclipApi<DashboardData>("dashboard");

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Dashboard</h1>

      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <MetricCard
          label="Agents"
          value={data?.agents?.total ?? 0}
          subValue={`${data?.agents?.active ?? 0} active`}
          icon={Bot}
          href="/teams/agents"
        />
        <MetricCard
          label="Tasks In Progress"
          value={data?.issues?.inProgress ?? 0}
          icon={CircleDot}
          href="/teams/issues"
        />
        <MetricCard
          label="Month Spend"
          value={`$${((data?.costs?.monthSpendCents ?? 0) / 100).toFixed(2)}`}
          icon={DollarSign}
          href="/teams/costs"
        />
        <MetricCard
          label="Pending Approvals"
          value={data?.approvals?.pending ?? 0}
          icon={CheckCircle2}
          href="/teams/approvals"
        />
      </div>

      <div className="rounded-lg border border-[#e5e0d5] bg-white">
        <div className="p-4 border-b border-[#e5e0d5]">
          <h2 className="text-sm font-medium text-[#1a1a1a]">Recent Activity</h2>
        </div>
        <div className="divide-y divide-[#e5e0d5]">
          {data?.recentActivity?.length ? (
            data.recentActivity.slice(0, 10).map((item) => (
              <div key={item.id} className="px-4 py-3 text-sm">
                <span className="text-[#1a1a1a]">{item.description}</span>
                <span className="ml-2 text-xs text-[#b0a99a]">
                  {new Date(item.createdAt).toLocaleString()}
                </span>
              </div>
            ))
          ) : (
            <div className="px-4 py-8 text-center text-sm text-[#8a8578]">
              No activity yet. Hire an agent to get started.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
```

Note: The exact shape of Paperclip's `/api/dashboard` response may differ. During implementation, check the actual response and adjust the types accordingly.

- [ ] **Step 2: Commit**

```bash
git add apps/frontend/src/components/teams/panels/DashboardPanel.tsx
git commit -m "feat(paperclip): add Teams dashboard panel"
```

---

## Task 10: Frontend — Agents Panel + Detail

**Files:**
- Create: `apps/frontend/src/components/teams/panels/AgentsPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/AgentDetailPanel.tsx`

- [ ] **Step 1: Create AgentsPanel**

Reference Paperclip's `ui/src/pages/Agents.tsx`. List of agents with status, filter tabs:

```typescript
// apps/frontend/src/components/teams/panels/AgentsPanel.tsx
"use client";

import { usePaperclipApi, usePaperclipMutation } from "@/hooks/usePaperclip";
import { Button } from "@/components/ui/button";
import { Bot, Plus, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { cn } from "@/lib/utils";

interface Agent {
  id: string;
  name: string;
  role: string;
  title: string;
  status: string;
  adapterType: string;
  lastHeartbeatAt: string | null;
}

const STATUS_COLORS: Record<string, string> = {
  active: "bg-green-500",
  running: "bg-cyan-500",
  paused: "bg-yellow-500",
  error: "bg-red-500",
  terminated: "bg-gray-400",
};

const FILTER_TABS = ["all", "active", "paused", "error"] as const;

export function AgentsPanel() {
  const { data: agents, isLoading } = usePaperclipApi<Agent[]>("agents");
  const router = useRouter();
  const [filter, setFilter] = useState<string>("all");

  const filtered = agents?.filter((a) => filter === "all" || a.status === filter) ?? [];

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-[#1a1a1a]">Agents</h1>
        <Button size="sm" onClick={() => router.push("/teams/agents/new")}>
          <Plus className="h-4 w-4 mr-1" />
          New Agent
        </Button>
      </div>

      <div className="flex gap-1 border-b border-[#e5e0d5]">
        {FILTER_TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setFilter(tab)}
            className={cn(
              "px-3 py-2 text-sm capitalize border-b-2 -mb-px transition-colors",
              filter === tab
                ? "border-[#1a1a1a] text-[#1a1a1a]"
                : "border-transparent text-[#8a8578] hover:text-[#1a1a1a]",
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
        </div>
      ) : filtered.length === 0 ? (
        <div className="py-12 text-center">
          <Bot className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">No agents yet. Hire one to get started.</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {filtered.map((agent) => (
            <button
              key={agent.id}
              onClick={() => router.push(`/teams/agents/${agent.id}`)}
              className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-[#faf8f4] transition-colors"
            >
              <span className={cn("h-2 w-2 rounded-full flex-shrink-0", STATUS_COLORS[agent.status] ?? "bg-gray-400")} />
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-[#1a1a1a] truncate">{agent.name}</div>
                <div className="text-xs text-[#8a8578] truncate">{agent.role || agent.title}</div>
              </div>
              <div className="text-xs text-[#b0a99a]">{agent.adapterType}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create AgentDetailPanel**

```typescript
// apps/frontend/src/components/teams/panels/AgentDetailPanel.tsx
"use client";

import { usePaperclipApi, usePaperclipMutation } from "@/hooks/usePaperclip";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";
import { useState } from "react";

interface AgentDetail {
  id: string;
  name: string;
  role: string;
  title: string;
  status: string;
  adapterType: string;
  adapterConfig: Record<string, unknown>;
  budgetMonthlyCents: number | null;
  capabilities: string[];
  lastHeartbeatAt: string | null;
  reportsTo: string | null;
}

interface AgentRun {
  id: string;
  status: string;
  startedAt: string;
  completedAt: string | null;
  costUsd: number;
  model: string;
}

const TABS = ["overview", "runs", "configuration", "budget"] as const;

export function AgentDetailPanel({
  agentId,
  isNew,
  tab,
  runId,
}: {
  agentId?: string;
  isNew?: boolean;
  tab?: string;
  runId?: string;
}) {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState(tab || "overview");
  const { data: agent, isLoading } = usePaperclipApi<AgentDetail>(
    agentId ? `agents/${agentId}` : null,
  );
  const { data: runs } = usePaperclipApi<AgentRun[]>(
    agentId && activeTab === "runs" ? `agents/${agentId}/runs` : null,
  );

  if (isNew) {
    return <NewAgentForm />;
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  if (!agent) {
    return <div className="p-6 text-[#8a8578]">Agent not found.</div>;
  }

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.push("/teams/agents")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <h1 className="text-lg font-semibold text-[#1a1a1a]">{agent.name}</h1>
          <p className="text-sm text-[#8a8578]">{agent.role || agent.title}</p>
        </div>
      </div>

      <div className="flex gap-1 border-b border-[#e5e0d5]">
        {TABS.map((t) => (
          <button
            key={t}
            onClick={() => setActiveTab(t)}
            className={cn(
              "px-3 py-2 text-sm capitalize border-b-2 -mb-px transition-colors",
              activeTab === t
                ? "border-[#1a1a1a] text-[#1a1a1a]"
                : "border-transparent text-[#8a8578] hover:text-[#1a1a1a]",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {activeTab === "overview" && (
        <div className="space-y-3">
          <InfoRow label="Status" value={agent.status} />
          <InfoRow label="Adapter" value={agent.adapterType} />
          <InfoRow label="Capabilities" value={agent.capabilities?.join(", ") || "None"} />
          <InfoRow
            label="Last Heartbeat"
            value={agent.lastHeartbeatAt ? new Date(agent.lastHeartbeatAt).toLocaleString() : "Never"}
          />
        </div>
      )}

      {activeTab === "runs" && (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {runs?.length ? (
            runs.map((run) => (
              <div key={run.id} className="px-4 py-3 flex items-center justify-between text-sm">
                <div>
                  <span className="text-[#1a1a1a]">{run.status}</span>
                  <span className="ml-2 text-xs text-[#b0a99a]">
                    {new Date(run.startedAt).toLocaleString()}
                  </span>
                </div>
                <div className="text-xs text-[#8a8578]">
                  ${run.costUsd?.toFixed(4)} · {run.model}
                </div>
              </div>
            ))
          ) : (
            <div className="px-4 py-8 text-center text-sm text-[#8a8578]">No runs yet.</div>
          )}
        </div>
      )}

      {activeTab === "configuration" && (
        <pre className="rounded-lg border border-[#e5e0d5] bg-white p-4 text-xs overflow-auto">
          {JSON.stringify(agent.adapterConfig, null, 2)}
        </pre>
      )}

      {activeTab === "budget" && (
        <div className="space-y-3">
          <InfoRow
            label="Monthly Budget"
            value={
              agent.budgetMonthlyCents != null
                ? `$${(agent.budgetMonthlyCents / 100).toFixed(2)}`
                : "Unlimited"
            }
          />
        </div>
      )}
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between py-2 border-b border-[#e5e0d5] last:border-0">
      <span className="text-sm text-[#8a8578]">{label}</span>
      <span className="text-sm text-[#1a1a1a]">{value}</span>
    </div>
  );
}

function NewAgentForm() {
  const router = useRouter();
  const { post } = usePaperclipMutation();
  const [name, setName] = useState("");
  const [role, setRole] = useState("");
  const [creating, setCreating] = useState(false);

  const handleCreate = async () => {
    setCreating(true);
    try {
      // Auto-fill OpenClaw gateway adapter config
      await post("agents", {
        name,
        role,
        adapterType: "openclaw_gateway",
        adapterConfig: {
          url: "ws://localhost:18789",
        },
      });
      router.push("/teams/agents");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="p-6 space-y-4 max-w-lg">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.push("/teams/agents")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-lg font-semibold text-[#1a1a1a]">New Agent</h1>
      </div>

      <div className="space-y-3">
        <div>
          <label className="text-sm text-[#8a8578] block mb-1">Name</label>
          <input
            className="w-full rounded-md border border-[#e5e0d5] px-3 py-2 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Agent name"
          />
        </div>
        <div>
          <label className="text-sm text-[#8a8578] block mb-1">Role</label>
          <input
            className="w-full rounded-md border border-[#e5e0d5] px-3 py-2 text-sm"
            value={role}
            onChange={(e) => setRole(e.target.value)}
            placeholder="e.g. Frontend Engineer"
          />
        </div>
        <p className="text-xs text-[#b0a99a]">
          The agent will be configured with the OpenClaw gateway adapter automatically.
        </p>
        <Button onClick={handleCreate} disabled={!name || creating}>
          {creating && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
          Hire Agent
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/teams/panels/AgentsPanel.tsx apps/frontend/src/components/teams/panels/AgentDetailPanel.tsx
git commit -m "feat(paperclip): add Agents panel and detail view"
```

---

## Task 11: Frontend — Issues Panel + Detail

**Files:**
- Create: `apps/frontend/src/components/teams/panels/IssuesPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/IssueDetailPanel.tsx`

- [ ] **Step 1: Create IssuesPanel**

Reference Paperclip's `ui/src/pages/Issues.tsx`. Issue list with status icons:

```typescript
// apps/frontend/src/components/teams/panels/IssuesPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { CircleDot, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/utils";

interface Issue {
  id: string;
  identifier: string;
  title: string;
  status: string;
  assigneeId: string | null;
  assigneeName: string | null;
  priority: string;
  createdAt: string;
}

const STATUS_ICONS: Record<string, string> = {
  backlog: "text-gray-400",
  todo: "text-blue-400",
  in_progress: "text-yellow-500",
  in_review: "text-purple-500",
  done: "text-green-500",
  cancelled: "text-gray-300",
  blocked: "text-red-500",
};

export function IssuesPanel() {
  const { data: issues, isLoading } = usePaperclipApi<Issue[]>("issues");
  const router = useRouter();

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Issues</h1>

      {!issues?.length ? (
        <div className="py-12 text-center">
          <CircleDot className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">No issues yet.</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {issues.map((issue) => (
            <button
              key={issue.id}
              onClick={() => router.push(`/teams/issues/${issue.id}`)}
              className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-[#faf8f4] transition-colors"
            >
              <CircleDot className={cn("h-4 w-4 flex-shrink-0", STATUS_ICONS[issue.status] ?? "text-gray-400")} />
              <span className="text-xs text-[#b0a99a] w-16 flex-shrink-0">{issue.identifier}</span>
              <span className="text-sm text-[#1a1a1a] flex-1 truncate">{issue.title}</span>
              {issue.assigneeName && (
                <span className="text-xs text-[#8a8578]">{issue.assigneeName}</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Create IssueDetailPanel**

```typescript
// apps/frontend/src/components/teams/panels/IssueDetailPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { Button } from "@/components/ui/button";
import { ArrowLeft, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";

interface IssueDetail {
  id: string;
  identifier: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  assigneeId: string | null;
  assigneeName: string | null;
  labels: string[];
  createdAt: string;
  updatedAt: string;
  comments: Array<{
    id: string;
    body: string;
    authorName: string;
    createdAt: string;
  }>;
}

export function IssueDetailPanel({ issueId }: { issueId: string }) {
  const router = useRouter();
  const { data: issue, isLoading } = usePaperclipApi<IssueDetail>(`issues/${issueId}`);

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  if (!issue) return <div className="p-6 text-[#8a8578]">Issue not found.</div>;

  return (
    <div className="p-6 space-y-4">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="sm" onClick={() => router.push("/teams/issues")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <div>
          <span className="text-xs text-[#b0a99a]">{issue.identifier}</span>
          <h1 className="text-lg font-semibold text-[#1a1a1a]">{issue.title}</h1>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 text-sm">
        <div>
          <span className="text-[#8a8578]">Status:</span>{" "}
          <span className="text-[#1a1a1a] capitalize">{issue.status.replace("_", " ")}</span>
        </div>
        <div>
          <span className="text-[#8a8578]">Priority:</span>{" "}
          <span className="text-[#1a1a1a] capitalize">{issue.priority}</span>
        </div>
        <div>
          <span className="text-[#8a8578]">Assignee:</span>{" "}
          <span className="text-[#1a1a1a]">{issue.assigneeName || "Unassigned"}</span>
        </div>
      </div>

      {issue.description && (
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-4">
          <p className="text-sm text-[#1a1a1a] whitespace-pre-wrap">{issue.description}</p>
        </div>
      )}

      <div>
        <h2 className="text-sm font-medium text-[#1a1a1a] mb-3">Comments</h2>
        <div className="space-y-3">
          {issue.comments?.length ? (
            issue.comments.map((c) => (
              <div key={c.id} className="rounded-lg border border-[#e5e0d5] bg-white p-3">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-[#1a1a1a]">{c.authorName}</span>
                  <span className="text-xs text-[#b0a99a]">{new Date(c.createdAt).toLocaleString()}</span>
                </div>
                <p className="text-sm text-[#8a8578] whitespace-pre-wrap">{c.body}</p>
              </div>
            ))
          ) : (
            <p className="text-sm text-[#8a8578]">No comments.</p>
          )}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add apps/frontend/src/components/teams/panels/IssuesPanel.tsx apps/frontend/src/components/teams/panels/IssueDetailPanel.tsx
git commit -m "feat(paperclip): add Issues panel and detail view"
```

---

## Task 12: Frontend — Remaining Panels (Batch)

All remaining panels follow the same pattern: fetch from Paperclip API via `usePaperclipApi`, render in Isol8's style. Each is a focused component.

**Files:**
- Create: `apps/frontend/src/components/teams/panels/GoalsPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/RoutinesPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/ProjectsPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/CostsPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/ActivityPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/OrgChartPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/InboxPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/ApprovalsPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/SkillsPanel.tsx`
- Create: `apps/frontend/src/components/teams/panels/SettingsPanel.tsx`

- [ ] **Step 1: Create GoalsPanel**

```typescript
// apps/frontend/src/components/teams/panels/GoalsPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { Target, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";

interface Goal {
  id: string;
  title: string;
  description: string;
  parentId: string | null;
  status: string;
}

export function GoalsPanel({ goalId }: { goalId?: string }) {
  const { data: goals, isLoading } = usePaperclipApi<Goal[]>("goals");
  const router = useRouter();

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  // If goalId is provided, show detail
  if (goalId) {
    const goal = goals?.find((g) => g.id === goalId);
    if (!goal) return <div className="p-6 text-[#8a8578]">Goal not found.</div>;
    return (
      <div className="p-6 space-y-4">
        <h1 className="text-lg font-semibold text-[#1a1a1a]">{goal.title}</h1>
        <p className="text-sm text-[#8a8578]">{goal.description}</p>
      </div>
    );
  }

  const roots = goals?.filter((g) => !g.parentId) ?? [];

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Goals</h1>
      {!roots.length ? (
        <div className="py-12 text-center">
          <Target className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">No goals defined yet.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {roots.map((goal) => (
            <GoalNode key={goal.id} goal={goal} allGoals={goals ?? []} router={router} depth={0} />
          ))}
        </div>
      )}
    </div>
  );
}

function GoalNode({
  goal,
  allGoals,
  router,
  depth,
}: {
  goal: Goal;
  allGoals: Goal[];
  router: ReturnType<typeof useRouter>;
  depth: number;
}) {
  const children = allGoals.filter((g) => g.parentId === goal.id);
  return (
    <div style={{ paddingLeft: depth * 20 }}>
      <button
        onClick={() => router.push(`/teams/goals/${goal.id}`)}
        className="w-full text-left px-3 py-2 rounded-md hover:bg-white/60 transition-colors"
      >
        <div className="text-sm font-medium text-[#1a1a1a]">{goal.title}</div>
        {goal.description && <div className="text-xs text-[#8a8578] truncate">{goal.description}</div>}
      </button>
      {children.map((child) => (
        <GoalNode key={child.id} goal={child} allGoals={allGoals} router={router} depth={depth + 1} />
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Create RoutinesPanel**

```typescript
// apps/frontend/src/components/teams/panels/RoutinesPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { Repeat, Loader2 } from "lucide-react";

interface Routine {
  id: string;
  title: string;
  cronExpression: string;
  timezone: string;
  assigneeName: string | null;
  enabled: boolean;
  lastRunAt: string | null;
}

export function RoutinesPanel({ routineId }: { routineId?: string }) {
  const { data: routines, isLoading } = usePaperclipApi<Routine[]>("routines");

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Routines</h1>
      {!routines?.length ? (
        <div className="py-12 text-center">
          <Repeat className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">No routines configured.</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {routines.map((r) => (
            <div key={r.id} className="px-4 py-3 flex items-center justify-between">
              <div>
                <div className="text-sm font-medium text-[#1a1a1a]">{r.title}</div>
                <div className="text-xs text-[#8a8578]">
                  {r.cronExpression} ({r.timezone})
                </div>
              </div>
              <div className="text-xs text-[#b0a99a]">
                {r.enabled ? "Active" : "Paused"}
                {r.assigneeName && ` · ${r.assigneeName}`}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create ProjectsPanel**

```typescript
// apps/frontend/src/components/teams/panels/ProjectsPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { FolderOpen, Loader2 } from "lucide-react";
import { useRouter } from "next/navigation";

interface Project {
  id: string;
  name: string;
  description: string;
  status: string;
}

export function ProjectsPanel({ projectId }: { projectId?: string }) {
  const { data: projects, isLoading } = usePaperclipApi<Project[]>("projects");
  const router = useRouter();

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  if (projectId) {
    const project = projects?.find((p) => p.id === projectId);
    if (!project) return <div className="p-6 text-[#8a8578]">Project not found.</div>;
    return (
      <div className="p-6 space-y-4">
        <h1 className="text-lg font-semibold text-[#1a1a1a]">{project.name}</h1>
        <p className="text-sm text-[#8a8578]">{project.description}</p>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Projects</h1>
      {!projects?.length ? (
        <div className="py-12 text-center">
          <FolderOpen className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">No projects yet.</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {projects.map((p) => (
            <button
              key={p.id}
              onClick={() => router.push(`/teams/projects/${p.id}`)}
              className="w-full px-4 py-3 text-left hover:bg-[#faf8f4] transition-colors"
            >
              <div className="text-sm font-medium text-[#1a1a1a]">{p.name}</div>
              <div className="text-xs text-[#8a8578] truncate">{p.description}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Create CostsPanel**

```typescript
// apps/frontend/src/components/teams/panels/CostsPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { DollarSign, Loader2 } from "lucide-react";

interface CostData {
  totalSpendCents: number;
  monthSpendCents: number;
  byAgent: Array<{
    agentId: string;
    agentName: string;
    totalCents: number;
    runs: number;
  }>;
}

export function CostsPanel() {
  const { data: costs, isLoading } = usePaperclipApi<CostData>("costs");

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Costs</h1>

      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-4">
          <div className="text-2xl font-semibold text-[#1a1a1a]">
            ${((costs?.monthSpendCents ?? 0) / 100).toFixed(2)}
          </div>
          <div className="text-sm text-[#8a8578]">This Month</div>
        </div>
        <div className="rounded-lg border border-[#e5e0d5] bg-white p-4">
          <div className="text-2xl font-semibold text-[#1a1a1a]">
            ${((costs?.totalSpendCents ?? 0) / 100).toFixed(2)}
          </div>
          <div className="text-sm text-[#8a8578]">All Time</div>
        </div>
      </div>

      <h2 className="text-sm font-medium text-[#1a1a1a]">By Agent</h2>
      {costs?.byAgent?.length ? (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {costs.byAgent.map((a) => (
            <div key={a.agentId} className="px-4 py-3 flex items-center justify-between text-sm">
              <span className="text-[#1a1a1a]">{a.agentName}</span>
              <div className="text-[#8a8578]">
                ${(a.totalCents / 100).toFixed(2)} · {a.runs} runs
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="py-8 text-center">
          <DollarSign className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">No cost data yet.</p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Create ActivityPanel**

```typescript
// apps/frontend/src/components/teams/panels/ActivityPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { History, Loader2 } from "lucide-react";

interface ActivityItem {
  id: string;
  type: string;
  description: string;
  entityType: string;
  createdAt: string;
}

export function ActivityPanel() {
  const { data: activity, isLoading } = usePaperclipApi<ActivityItem[]>("activity");

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Activity</h1>
      {!activity?.length ? (
        <div className="py-12 text-center">
          <History className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">No activity yet.</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {activity.map((item) => (
            <div key={item.id} className="px-4 py-3 text-sm">
              <span className="text-[#1a1a1a]">{item.description}</span>
              <span className="ml-2 text-xs text-[#b0a99a]">
                {new Date(item.createdAt).toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Create OrgChartPanel**

```typescript
// apps/frontend/src/components/teams/panels/OrgChartPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { Network, Loader2 } from "lucide-react";

interface OrgAgent {
  id: string;
  name: string;
  role: string;
  title: string;
  status: string;
  reportsTo: string | null;
}

export function OrgChartPanel() {
  const { data: agents, isLoading } = usePaperclipApi<OrgAgent[]>("agents");

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  if (!agents?.length) {
    return (
      <div className="p-6">
        <h1 className="text-lg font-semibold text-[#1a1a1a] mb-4">Org Chart</h1>
        <div className="py-12 text-center">
          <Network className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">Hire agents to see the org chart.</p>
        </div>
      </div>
    );
  }

  // Simple tree rendering — for MVP, use indented list rather than full SVG canvas.
  // Can be upgraded to SVG canvas later (reference Paperclip's ui/src/pages/OrgChart.tsx).
  const roots = agents.filter((a) => !a.reportsTo);

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Org Chart</h1>
      <div className="rounded-lg border border-[#e5e0d5] bg-white p-4">
        {roots.map((agent) => (
          <OrgNode key={agent.id} agent={agent} allAgents={agents} depth={0} />
        ))}
      </div>
    </div>
  );
}

function OrgNode({ agent, allAgents, depth }: { agent: OrgAgent; allAgents: OrgAgent[]; depth: number }) {
  const reports = allAgents.filter((a) => a.reportsTo === agent.id);
  const statusColor = agent.status === "active" ? "bg-green-500" : agent.status === "error" ? "bg-red-500" : "bg-gray-400";

  return (
    <div style={{ paddingLeft: depth * 24 }} className="py-1">
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 rounded-full ${statusColor}`} />
        <span className="text-sm font-medium text-[#1a1a1a]">{agent.name}</span>
        <span className="text-xs text-[#8a8578]">{agent.role || agent.title}</span>
      </div>
      {reports.map((r) => (
        <OrgNode key={r.id} agent={r} allAgents={allAgents} depth={depth + 1} />
      ))}
    </div>
  );
}
```

- [ ] **Step 7: Create InboxPanel**

```typescript
// apps/frontend/src/components/teams/panels/InboxPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { Inbox, Loader2 } from "lucide-react";

interface InboxItem {
  id: string;
  type: string;
  title: string;
  body: string;
  read: boolean;
  createdAt: string;
}

export function InboxPanel() {
  const { data: items, isLoading } = usePaperclipApi<InboxItem[]>("inbox");

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Inbox</h1>
      {!items?.length ? (
        <div className="py-12 text-center">
          <Inbox className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">All clear.</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {items.map((item) => (
            <div key={item.id} className="px-4 py-3">
              <div className="flex items-center gap-2">
                {!item.read && <span className="h-2 w-2 rounded-full bg-blue-500 flex-shrink-0" />}
                <span className="text-sm font-medium text-[#1a1a1a]">{item.title}</span>
                <span className="ml-auto text-xs text-[#b0a99a]">
                  {new Date(item.createdAt).toLocaleString()}
                </span>
              </div>
              {item.body && <p className="text-xs text-[#8a8578] mt-1 truncate">{item.body}</p>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 8: Create ApprovalsPanel**

```typescript
// apps/frontend/src/components/teams/panels/ApprovalsPanel.tsx
"use client";

import { usePaperclipApi, usePaperclipMutation } from "@/hooks/usePaperclip";
import { Button } from "@/components/ui/button";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";

interface Approval {
  id: string;
  type: string;
  description: string;
  status: string;
  requestedBy: string;
  createdAt: string;
}

export function ApprovalsPanel({ approvalId }: { approvalId?: string }) {
  const { data: approvals, isLoading, refresh } = usePaperclipApi<Approval[]>("approvals");
  const { post } = usePaperclipMutation();

  const handleAction = async (id: string, action: "approve" | "reject") => {
    await post(`approvals/${id}/${action}`);
    refresh();
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  const pending = approvals?.filter((a) => a.status === "pending") ?? [];

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Approvals</h1>
      {!pending.length ? (
        <div className="py-12 text-center">
          <CheckCircle2 className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">No pending approvals.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {pending.map((a) => (
            <div key={a.id} className="rounded-lg border border-[#e5e0d5] bg-white p-4">
              <div className="text-sm font-medium text-[#1a1a1a]">{a.description}</div>
              <div className="text-xs text-[#8a8578] mt-1">
                Requested by {a.requestedBy} · {new Date(a.createdAt).toLocaleString()}
              </div>
              <div className="flex gap-2 mt-3">
                <Button size="sm" variant="outline" onClick={() => handleAction(a.id, "approve")}>
                  <CheckCircle2 className="h-3 w-3 mr-1" /> Approve
                </Button>
                <Button size="sm" variant="outline" onClick={() => handleAction(a.id, "reject")}>
                  <XCircle className="h-3 w-3 mr-1" /> Reject
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 9: Create SkillsPanel**

```typescript
// apps/frontend/src/components/teams/panels/SkillsPanel.tsx
"use client";

import { usePaperclipApi } from "@/hooks/usePaperclip";
import { Boxes, Loader2 } from "lucide-react";

interface Skill {
  id: string;
  name: string;
  description: string;
}

export function SkillsPanel() {
  const { data: skills, isLoading } = usePaperclipApi<Skill[]>("skills");

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-4">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Skills</h1>
      {!skills?.length ? (
        <div className="py-12 text-center">
          <Boxes className="h-10 w-10 mx-auto mb-3 text-[#b0a99a]" />
          <p className="text-sm text-[#8a8578]">No skills configured.</p>
        </div>
      ) : (
        <div className="rounded-lg border border-[#e5e0d5] bg-white divide-y divide-[#e5e0d5]">
          {skills.map((s) => (
            <div key={s.id} className="px-4 py-3">
              <div className="text-sm font-medium text-[#1a1a1a]">{s.name}</div>
              <div className="text-xs text-[#8a8578]">{s.description}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 10: Create SettingsPanel**

```typescript
// apps/frontend/src/components/teams/panels/SettingsPanel.tsx
"use client";

import { usePaperclipApi, usePaperclipMutation } from "@/hooks/usePaperclip";
import { usePaperclipEnable } from "@/hooks/usePaperclip";
import { Button } from "@/components/ui/button";
import { Settings, Loader2 } from "lucide-react";
import { useState } from "react";

interface Company {
  id: string;
  name: string;
  description: string;
  issuePrefix: string;
  budgetMonthlyCents: number | null;
}

export function SettingsPanel() {
  const { data: companies, isLoading } = usePaperclipApi<Company[]>("companies");
  const { patch } = usePaperclipMutation();
  const { disable } = usePaperclipEnable();
  const [disabling, setDisabling] = useState(false);

  const company = companies?.[0];

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-[#8a8578]" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-lg">
      <h1 className="text-lg font-semibold text-[#1a1a1a]">Settings</h1>

      {company && (
        <div className="space-y-3">
          <div>
            <label className="text-sm text-[#8a8578] block mb-1">Company Name</label>
            <div className="text-sm text-[#1a1a1a]">{company.name}</div>
          </div>
          <div>
            <label className="text-sm text-[#8a8578] block mb-1">Issue Prefix</label>
            <div className="text-sm text-[#1a1a1a]">{company.issuePrefix}</div>
          </div>
          <div>
            <label className="text-sm text-[#8a8578] block mb-1">Monthly Budget</label>
            <div className="text-sm text-[#1a1a1a]">
              {company.budgetMonthlyCents != null
                ? `$${(company.budgetMonthlyCents / 100).toFixed(2)}`
                : "Unlimited"}
            </div>
          </div>
        </div>
      )}

      <div className="border-t border-[#e5e0d5] pt-6">
        <h2 className="text-sm font-medium text-red-600 mb-2">Danger Zone</h2>
        <p className="text-xs text-[#8a8578] mb-3">
          Disabling Teams will remove the Paperclip sidecar from your container.
          Your data will be preserved on disk and restored if you re-enable.
        </p>
        <Button
          variant="outline"
          size="sm"
          className="text-red-600 border-red-200 hover:bg-red-50"
          onClick={async () => {
            setDisabling(true);
            try {
              await disable();
              window.location.href = "/chat";
            } finally {
              setDisabling(false);
            }
          }}
          disabled={disabling}
        >
          {disabling && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
          Disable Teams
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 11: Commit all remaining panels**

```bash
git add apps/frontend/src/components/teams/panels/
git commit -m "feat(paperclip): add remaining Teams panels (goals, routines, projects, costs, activity, org, inbox, approvals, skills, settings)"
```

---

## Task 13: Frontend — Control Dashboard Link

**Files:**
- Modify: `apps/frontend/src/components/control/panels/OverviewPanel.tsx`

- [ ] **Step 1: Add Teams card to Overview panel**

In the OverviewPanel, add a card that links to `/teams`. Find the existing card grid and add:

```typescript
import { Users } from "lucide-react";
import Link from "next/link";
import { useBilling } from "@/hooks/useBilling";

// Inside the component, after the existing cards:
const { planTier } = useBilling();
const showTeams = planTier === "pro" || planTier === "enterprise";

// In the JSX, add a card:
{showTeams && (
  <Link href="/teams">
    <div className="rounded-lg border border-[#e5e0d5] bg-white p-4 hover:shadow-sm transition-shadow cursor-pointer">
      <div className="flex items-center gap-3">
        <Users className="h-5 w-5 text-[#8a8578]" />
        <div>
          <div className="text-sm font-medium text-[#1a1a1a]">Teams</div>
          <div className="text-xs text-[#8a8578]">Manage AI agent teams with Paperclip</div>
        </div>
      </div>
    </div>
  </Link>
)}
```

Note: The exact insertion point depends on the current OverviewPanel layout. Read the file during implementation and place the card in the appropriate grid section.

- [ ] **Step 2: Commit**

```bash
git add apps/frontend/src/components/control/panels/OverviewPanel.tsx
git commit -m "feat(paperclip): add Teams card to control dashboard overview"
```

---

## Task 14: Integration — Tier Downgrade Handling

**Files:**
- Modify: `apps/backend/core/services/config_patcher.py` (or wherever tier change logic lives)

- [ ] **Step 1: Find the tier change handler**

Search for where tier changes are processed in the backend. Look for Stripe webhook handlers or billing service methods that handle subscription updates. The tier change should trigger Paperclip disable if downgrading from pro/enterprise to starter/free.

- [ ] **Step 2: Add Paperclip disable on downgrade**

In the tier change handler, after the existing logic:

```python
# If downgrading from a Paperclip-eligible tier, disable Paperclip
old_paperclip = TIER_CONFIG.get(old_tier, {}).get("paperclip_enabled", False)
new_paperclip = TIER_CONFIG.get(new_tier, {}).get("paperclip_enabled", False)

if old_paperclip and not new_paperclip:
    container = await container_repo.get_by_owner_id(owner_id)
    if container and container.get("paperclip_enabled"):
        ecs = get_ecs_manager()
        await ecs.disable_paperclip(owner_id)
        logger.info("Disabled Paperclip for %s due to tier downgrade", owner_id)
```

- [ ] **Step 3: Commit**

```bash
git add apps/backend/
git commit -m "feat(paperclip): auto-disable Paperclip on tier downgrade"
```

---

## Task 15: Company Auto-Creation

**Files:**
- Modify: `apps/backend/routers/paperclip_api.py`

- [ ] **Step 1: Add company auto-creation to the enable flow**

After the board API key is provisioned, automatically create a company in Paperclip so the user doesn't see an empty state on first visit. Add to the `provision_paperclip_board_key` method in `ecs_manager.py` (or as a separate step in the enable flow):

```python
# After board key is created, create default company
async with httpx.AsyncClient(timeout=15.0) as client:
    await client.post(
        f"{paperclip_url}/api/companies",
        json={
            "name": "My Company",
            "issuePrefix": "ISL",
        },
        headers={"Authorization": f"Bearer {board_key}"},
    )
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/core/containers/ecs_manager.py
git commit -m "feat(paperclip): auto-create default company on Paperclip enable"
```

---

## Summary

| Task | Description | Estimated Complexity |
|------|-------------|---------------------|
| 1 | Backend config | Small |
| 2 | CDK pro task definition | Medium |
| 3 | EcsManager sidecar provisioning | Large |
| 4 | Paperclip API proxy router | Medium |
| 5 | Register router | Small |
| 6 | Frontend routes + middleware | Small |
| 7 | usePaperclip hook | Small |
| 8 | Guard + Sidebar + Router | Medium |
| 9 | Dashboard panel | Medium |
| 10 | Agents panel + detail | Medium |
| 11 | Issues panel + detail | Medium |
| 12 | Remaining panels (batch) | Large (10 files) |
| 13 | Control dashboard link | Small |
| 14 | Tier downgrade handling | Small |
| 15 | Company auto-creation | Small |

**Key implementation notes:**
- Paperclip API response shapes are inferred from research. During implementation, verify against actual Paperclip API responses and adjust TypeScript interfaces accordingly.
- The board API key provisioning flow (Task 3, Step 4) needs verification against Paperclip's actual CLI auth endpoints. Test against a local Paperclip instance.
- The OrgChart panel uses a simple indented tree for MVP. Can be upgraded to full SVG canvas later by referencing Paperclip's `OrgChart.tsx`.
