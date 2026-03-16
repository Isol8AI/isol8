# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Isol8 is an AI agent platform powered by [OpenClaw](https://github.com/openclaw/openclaw) (reference copy in `openclaw_reference/`). Users subscribe, get a per-user ECS Fargate container running the OpenClaw Docker image, and interact with their agents via a WebSocket-based chat UI. The platform uses a Next.js 16 frontend (Vercel), FastAPI backend (EC2), Clerk for authentication, Supabase PostgreSQL for metadata, AWS Bedrock for LLM inference, Stripe for billing, and EFS for per-user agent workspaces.

Each user gets their own isolated OpenClaw container, with a persistent WebSocket connection pool on the backend proxying RPC calls and streaming events back to the frontend.

## Critical Rules

**NEVER modify production servers directly.** All changes to backend, frontend, or infrastructure MUST:
1. Be version controlled in the appropriate repository
2. Go through CI/CD pipelines for deployment

This includes environment variables -- use Terraform, GitHub secrets, and AWS Secrets Manager.

**Always watch your runs after you make a push to a repository.**

**NEVER overwrite any environment or docker files, or git repos without permission.**

**If the tests are not passing, your change is likely the culprit, even if the error is not in a file you touched. These are all dependent systems.**

**NEVER use `sleep` or `tail` commands in bash.** Use proper tool-based approaches:
- Instead of `sleep`: use `gh run watch` for CI/CD, or tool-based polling
- Instead of `tail`: use the Read tool to read files, or run commands without piping through tail

### Individual Services

**Database:** Local Docker PostgreSQL (`pgvector/pgvector:pg15`, port 5432, database `securechat`). Production uses Supabase PostgreSQL.

**Backend:**
```bash
cd backend
source env/bin/activate       # Python 3.12 virtualenv
python init_db.py --reset     # Drop and recreate all tables
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm run dev                   # localhost:3000
npm run build                 # Production build
npm run lint                  # ESLint
```

### Running Tests

```bash
./run_tests.sh                        # All tests
./run_tests.sh --backend-only         # Backend only (pytest)
./run_tests.sh --frontend-only        # Frontend only (Vitest + Playwright)
```

Backend: `cd backend && python -m pytest tests/ -v`
Frontend unit: `cd frontend && npm test`
Frontend E2E: `cd frontend && npm run test:e2e`

### Container Re-provisioning (Dev)

When you change `openclaw.json` config, existing containers keep the old config on EFS. Re-provision:

```javascript
// Browser console (any Isol8 page with Clerk loaded):
// PATCH -- rewrites openclaw.json + redeploys (preserves container)
await fetch('https://api-dev.isol8.co/api/v1/debug/provision', {method:'PATCH', headers:{Authorization:'Bearer '+await Clerk.session.getToken()}}).then(r=>r.json())

// Full reprovision -- DELETE then POST
await fetch('https://api-dev.isol8.co/api/v1/debug/provision', {method:'DELETE', headers:{Authorization:'Bearer '+await Clerk.session.getToken()}}).then(r=>r.json())
await fetch('https://api-dev.isol8.co/api/v1/debug/provision', {method:'POST', headers:{Authorization:'Bearer '+await Clerk.session.getToken()}}).then(r=>r.json())
```

Debug endpoints return 403 in production.

### CI/CD Monitoring

```bash
gh run watch <run-id> --repo Isol8AI/<repo> --exit-status
gh run view <run-id> --repo Isol8AI/<repo> --json status,jobs
```

---

## Architecture

### High-Level Data Flow

```
Client --> wss://ws-dev.isol8.co --> API Gateway --> Lambda Auth --> VPC Link V1 --> NLB --> ALB
  --> FastAPI /ws/message --> Cloud Map discovery (?) --> per-user OpenClaw container (ECS Fargate)
  <-- FastAPI pushes streaming chunks via Management API
                                                    |
                                        EFS /mnt/efs/users/{user_id}/
                                        agents/{agent_uuid}/
```

### Production Infrastructure

```
freebird/                    # Parent folder (not a git repo)
+-- frontend/                # Git repo - Next.js 16 (Vercel)
+-- backend/                 # Git repo - FastAPI (AWS EC2)
+-- goosetown/               # Git repo - GooseTown simulation (Vercel)
+-- goosetown-skill/         # OpenClaw skill plugin for GooseTown
+-- desktop/                 # Electron desktop app (isol8:// deep links)
+-- terraform/               # Git repo - Infrastructure as Code (AWS)
+-- openclaw_reference/      # Reference copy of OpenClaw repo
+-- scripts/                 # GooseTown map/asset generation utilities
+-- docs/plans/              # Design documents
```

```
+---------------+     +----------------------------------------------------+
|   Vercel      |     |                      AWS                            |
|  (Frontend)   |     |                                                    |
|               |---->|  WebSocket API GW --> VPC Link V1 --> NLB --> ALB   |
|               |<----|       | Management API                              |
|               |     |       Lambda Authorizer (Clerk JWT)                 |
|               |     |       DynamoDB (connection state)                   |
|               |     |                                                    |
|  REST API     |---->|  ALB -----------------------------> EC2             |
|               |     |                                      |             |
|               |     |                          +-----------+-------+     |
|               |     |                          | FastAPI backend    |     |
|               |     |                          | (connection pool   |     |
|               |     |                          |  to user containers)|    |
|               |     |                          +-------------------+     |
|               |     |                                                    |
|               |     |  ECS Fargate (per-user OpenClaw containers)        |
|               |     |  EFS (per-user workspaces at /mnt/efs/users/)     |
|               |     |  Cloud Map (service discovery)                     |
|               |     |  Supabase PostgreSQL    Secrets Manager            |
|               |     |  S3 (config + sprites)  CloudFront (assets CDN)   |
+---------------+     +----------------------------------------------------+
```

### AWS Configuration

| Setting | Value |
|---------|-------|
| Account ID | `877352799272` |
| Deploy Region | `us-east-1` |
| SSO Start URL | `https://isol8.awsapps.com/start` |
| CLI Profile | `isol8-admin` |

---

## Backend (FastAPI + SQLAlchemy)

**Entry point:** `main.py` -- FastAPI app with lifespan handler that starts the UsagePoller + GooseTown simulation. 13 routers registered under `/api/v1`. CORS middleware, custom OpenAPI schema with BearerAuth.

### Core (`core/`)

| File | Purpose |
|------|---------|
| `config.py` | Pydantic settings: ECS/EFS/CloudMap, Stripe billing, Bedrock, CORS, plan budgets ($2/$25/$75), S3 buckets, encryption key. |
| `auth.py` | Clerk JWT validation via PyJWT. `get_current_user` dependency returns `AuthContext`. JWKS cache with 1-hour TTL. |
| `database.py` | Async SQLAlchemy with NullPool (pgbouncer-compatible). `get_session_factory()` for streaming. |
| `constants.py` | `SYSTEM_ACTOR_ID = "__system__"` for audit logs. |

### Container Orchestration (`core/containers/`)

| File | Purpose |
|------|---------|
| `__init__.py` | Singletons: `get_ecs_manager()`, `get_workspace()`, `get_gateway_pool()`. Usage recording callback. |
| `ecs_manager.py` | Per-user ECS Fargate lifecycle. Cloud Map discovery. Per-user EFS access points. Service naming: `openclaw-{user_id}-{hash}`. |
| `config.py` | `write_openclaw_config()`: generates `openclaw.json` with Bedrock provider, search proxy, memory plugin. `write_mcporter_config()` for MCP servers. |
| `workspace.py` | EFS file I/O at `/mnt/efs/users/{user_id}/`. |
| `config_store.py` | Container metadata persistence (DB-backed Container model). |

### Gateway (`core/gateway/`)

| File | Purpose |
|------|---------|
| `connection_pool.py` | `GatewayConnectionPool`: persistent WebSocket connections to per-user OpenClaw containers. OpenClaw protocol 3.0 handshake, RPC proxy, event forwarding (agent streaming, tool_start/tool_end, chat final/error/aborted). Usage callback. Grace period idle cleanup. |

### Services (`core/services/`)

| File | Purpose |
|------|---------|
| `billing_service.py` | Stripe: customers, checkout, portal, subscription lifecycle. |
| `usage_service.py` | Usage tracking: `record_usage()` writes UsageEvent + UsageDaily rollup + Stripe Meters. |
| `usage_poller.py` | Background task polling OpenClaw gateway for session usage, writes to billing. |
| `connection_service.py` | DynamoDB WebSocket connection state (connectionId -> user_id). |
| `management_api_client.py` | Pushes messages to frontend via API Gateway Management API. |
| `bedrock_discovery.py` | Discover available models via Bedrock APIs. 1-hour cache. |
| `bedrock_client.py` | AWS Bedrock LLM inference wrapper. |
| `clerk_sync_service.py` | Clerk webhook sync for user lifecycle. |
| `key_service.py` | BYOK API key encryption/decryption (Fernet). |
| `pixellab_service.py` | PixelLab sprite generation for GooseTown agents. |
| `sprite_storage.py` | S3 + CloudFront storage for generated sprites. |
| `town_simulation.py` | GooseTown background simulation loop. |
| `town_service.py` | Town CRUD operations and state queries. |
| `town_agent_ws.py` | WebSocket manager for town agent connections. |
| `town_mood_engine.py` | Agent mood/emotion state machine. |
| `town_pathfinding.py` | A* pathfinding for town movement. |

### Routers (`routers/`)

| File | Prefix | Purpose |
|------|--------|---------|
| `users.py` | `/users` | `POST /sync` -- idempotent user creation from Clerk auth |
| `webhooks.py` | `/webhooks` | `POST /clerk` -- user.created/updated/deleted |
| `websocket_chat.py` | `/ws` | `POST /connect`, `/disconnect`, `/message` -- API Gateway WS integration. Handles ping/pong, town events, agent_chat, RPC forwarding. |
| `billing.py` | `/billing` | `GET /account`, `/usage`; `POST /checkout`, `/portal`, `/webhooks/stripe` |
| `container_rpc.py` | `/container` | `GET /health`; `POST /rpc` -- generic RPC proxy to user's OpenClaw gateway |
| `control_ui_proxy.py` | `/control-ui` | Proxy for OpenClaw built-in control UI SPA |
| `proxy.py` | `/proxy` | Proxy for external tool APIs (Perplexity search, etc.) |
| `channels.py` | `/channels` | Messaging channel management (Telegram, Discord, WhatsApp) |
| `settings_keys.py` | `/settings/keys` | BYOK API key CRUD (encrypted) |
| `integrations.py` | `/` | MCP server integration management (mcporter) |
| `debug.py` | `/debug` | Dev-only container provisioning (403 in prod) |
| `town.py` | `/town` | GooseTown: status, state, descriptions, join, move, chat |

### Models (`models/`)

| File | Tables |
|------|--------|
| `user.py` | `users` (Clerk user ID as PK) |
| `container.py` | `containers` (user_id unique, service_name, task_arn, access_point_id, gateway_token, status) |
| `billing.py` | `model_pricing`, `tool_pricing`, `billing_account`, `usage_event`, `usage_daily` |
| `audit_log.py` | `audit_logs` |
| `user_api_key.py` | `user_api_keys` (encrypted BYOK keys) |
| `town.py` | `town_agents`, `town_state`, `town_conversations`, `town_relationships` |

---

## Frontend (Next.js 16 App Router)

React 19, Tailwind CSS v4, Clerk auth, Framer Motion, SWR, lucide-react icons.

### Pages (`src/app/`)

| Path | Purpose |
|------|---------|
| `/` | Landing page (Navbar, Hero, Features, Pricing, Footer) |
| `/chat` | Main app: chat + control panel (requires auth) |
| `/sign-in`, `/sign-up` | Clerk auth pages |
| `/auth/desktop-callback` | Desktop app OAuth callback |
| `/settings` | Settings layout |

### Components (`src/components/`)

**Chat (`chat/`):**
| Component | Purpose |
|-----------|---------|
| `ChatLayout.tsx` | Main layout: sidebar + chat/control tabs + header with UserButton |
| `AgentChatWindow.tsx` | Chat UI: connection bar, messages, input, file upload, bootstrap suggestion |
| `ChatInput.tsx` | Text input + file upload + stop button + suggested message (Tab to accept) |
| `MessageList.tsx` | Message rendering: markdown, syntax highlighting, thinking blocks, tool use indicators |
| `Sidebar.tsx` | Agent list with create/delete/select |
| `ProvisioningStepper.tsx` | Onboarding flow: billing -> container -> gateway -> channels -> ready |
| `ChannelSetupStep.tsx` | Channel config UI (Telegram, Discord, WhatsApp) |
| `ConnectionStatusBar.tsx` | WebSocket connection indicator |
| `ModelSelector.tsx` | Model dropdown |

**Control Panel (`control/`):**
| Component | Purpose |
|-----------|---------|
| `ControlPanelRouter.tsx` | Routes to active panel |
| `ControlSidebar.tsx` | Navigation for control panels |
| `panels/OverviewPanel.tsx` | Dashboard: health, uptime, agents, sessions, billing, usage |
| `panels/ChannelsPanel.tsx` | Channel configuration |
| `panels/SessionsPanel.tsx` | Session management |
| `panels/UsagePanel.tsx` | Usage analytics |
| `panels/AgentsPanel.tsx` | Agent CRUD |
| `panels/SkillsPanel.tsx` | Skill/tool management |
| `panels/McpServersTab.tsx` | MCP server list |
| `panels/ConfigPanel.tsx` | Raw config editor |
| `panels/LogsPanel.tsx` | Log viewer |
| `panels/DebugPanel.tsx` | Debug utilities |

**Landing (`landing/`):** Navbar, Hero, Features, Pricing, Footer

**UI (`ui/`):** shadcn/ui (button, alert-dialog, dropdown-menu, checkbox, input, popover, scroll-area)

### Hooks (`src/hooks/`)

| Hook | Purpose |
|------|---------|
| `useGateway.tsx` | WebSocket provider for gateway RPC + chat. Reconnection (max 10), ping/pong, event pub-sub, RPC request/response matching. |
| `useAgentChat.ts` | Agent chat via useGateway. Message cache, bootstrap flag, tool use tracking, cancel via `chat.abort`, thinking blocks. |
| `useGatewayRpc.ts` | SWR-wrapped RPC calls via WebSocket. `useGatewayRpc<T>()` (read) + `useGatewayRpcMutation()` (write). |
| `useAgents.ts` | Agent CRUD via RPC: `agents.list`, `agents.create`, `agents.delete`, `agents.update`. |
| `useBilling.ts` | Billing account + checkout via REST API. |
| `useContainerStatus.ts` | Container status polling via REST. |
| `useScrollToBottom.ts` | Auto-scroll hook. |

### Utilities (`src/lib/`)

| File | Purpose |
|------|---------|
| `api.ts` | `useApi()` hook: authenticated REST methods (`get`, `post`, `put`, `del`, `syncUser`, `uploadFiles`). |
| `utils.ts` | Tailwind `cn()` class merging. |
| `tar.ts` | Tar utilities. |

### Middleware

`src/middleware.ts` -- Clerk protection for `/chat(.*)` and `/auth/desktop-callback`.

---

## Agent Message Flow

```
Client          API Gateway WS      FastAPI              OpenClaw (ECS Fargate)
  |                  |                  |                       |
  | WS message       |                  |                       |
  | {type:"agent_chat|  $default route  |                       |
  |  agent_id,       |  POST /ws/message|                       |
  |  message}        |  (VPC Link/NLB)  |                       |
  |----------------->|----------------->|                       |
  |                  |                  | Cloud Map discovery   |
  |                  |                  | -> user container IP  |
  |                  |                  | WebSocket RPC pool    |
  |                  |                  | chat.send {message}   |
  |                  |                  |---------------------->|
  |                  |                  |                       | Bedrock (IAM)
  |                  |                  |  agent events:        |
  |                  |                  |  stream: "assistant"  |
  |                  |  Management API  |  stream: "tool"       |
  | WS push          |  (HTTPS POST    |  chat: "final"        |
  | {type:"chunk"}   |   @connections)  |<----------------------|
  | {type:"tool_start"}                 |                       |
  | {type:"tool_end"}                   |                       |
  | {type:"done"}    |                  |                       |
  |<-----------------|<-----------------|                       |
```

**Event transformation** (`connection_pool.py:_transform_agent_event`):
- `stream: "assistant"` with text -> `{type: "chunk", content: text}`
- `stream: "tool"`, `phase: "start"` -> `{type: "tool_start", tool: name}`
- `stream: "tool"`, `phase: "result"` -> `{type: "tool_end", tool: name}`
- `chat` state `"final"` -> `{type: "done"}`
- `chat` state `"error"` -> `{type: "error", message: ...}`
- `chat` state `"aborted"` -> `{type: "error", message: "Agent run was cancelled"}`

---

## WebSocket Architecture

**Why WebSocket?** API Gateway HTTP API buffers SSE responses, breaking streaming. WebSocket API Gateway supports true real-time bidirectional communication.

**Key design decisions:**
1. VPC Link V1 (WebSocket API requires it, only supports NLB)
2. NLB -> ALB -> EC2 chain (Layer 4 -> Layer 7)
3. Management API for responses (HTTPS POST to `@connections/{id}`)
4. Lambda Authorizer validates Clerk JWT
5. DynamoDB stores connectionId -> user_id mapping

---

## Billing System

### Plan Tiers

| Tier | Monthly Budget | Stripe Fixed Price | Stripe Metered Price |
|------|---------------|-------------------|---------------------|
| `free` | $2 | None | None |
| `starter` | $25 | Yes | Yes |
| `pro` | $75 | Yes | Yes |

### Usage Flow

1. Agent chat completes -> `UsagePoller` polls gateway for session usage
2. `UsageService.record_usage()` looks up `ModelPricing`, falls back to defaults
3. Calculates cost, applies markup (default 1.4x)
4. Writes `UsageEvent` (immutable) + upserts `UsageDaily` rollup
5. Reports to Stripe Meters API (non-blocking)

---

## Environment Variables

### Backend (.env)

| Variable | Purpose | Default |
|----------|---------|---------|
| `DATABASE_URL` | PostgreSQL async connection string | `postgresql+asyncpg://...localhost:5432/securechat` |
| `CLERK_ISSUER` | Clerk domain for JWT validation | Required |
| `CLERK_SECRET_KEY` | Clerk secret key | Optional |
| `CLERK_WEBHOOK_SECRET` | Clerk webhook verification | Optional |
| `AWS_REGION` | AWS region | `us-east-1` |
| `BEDROCK_ENABLED` | Enable Bedrock model discovery | `true` |
| `ENVIRONMENT` | Environment name (dev/staging/prod) | Empty |
| `ECS_CLUSTER_ARN` | ECS Fargate cluster | Required for containers |
| `ECS_TASK_DEFINITION` | ECS task definition | Required |
| `ECS_SUBNETS` | Comma-separated subnet IDs | Required |
| `ECS_SECURITY_GROUP_ID` | Security group for containers | Required |
| `CLOUD_MAP_NAMESPACE_ID` | Cloud Map namespace | Required |
| `CLOUD_MAP_SERVICE_ID` | Cloud Map service | Required |
| `EFS_MOUNT_PATH` | EFS mount root | `/mnt/efs/users` |
| `EFS_FILE_SYSTEM_ID` | EFS filesystem | Required |
| `S3_CONFIG_BUCKET` | Config bucket | Required |
| `OPENCLAW_IMAGE` | Container image | `ghcr.io/openclaw/openclaw:latest` |
| `WS_MANAGEMENT_API_URL` | Management API endpoint | Set by Terraform |
| `WS_CONNECTIONS_TABLE` | DynamoDB table | `isol8-websocket-connections` |
| `STRIPE_SECRET_KEY` | Stripe API key | Empty |
| `STRIPE_WEBHOOK_SECRET` | Stripe webhook verification | Empty |
| `STRIPE_METER_ID` | Stripe usage meter ID | Empty |
| `BILLING_MARKUP` | Markup multiplier | `1.4` |
| `ENCRYPTION_KEY` | Fernet key for BYOK | Required for key management |
| `PERPLEXITY_API_KEY` | For search proxy | Optional |
| `CORS_ORIGINS` | Comma-separated origins | `http://localhost:3000` |

### Frontend (.env.local)

| Variable | Purpose |
|----------|---------|
| `NEXT_PUBLIC_API_URL` | Backend REST API URL **including `/api/v1`** |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk publishable key |
| `CLERK_SECRET_KEY` | Clerk secret key (server-side) |

**API URL by environment:**
- Local: `http://localhost:8000/api/v1`
- Dev: `https://api-dev.isol8.co/api/v1`
- Staging: `https://api-staging.isol8.co/api/v1`
- Production: `https://api.isol8.co/api/v1`

---

## Terraform Modules

Located in `terraform/`:

| Module | Purpose |
|--------|---------|
| `modules/vpc/` | VPC with public/private subnets, NAT gateway |
| `modules/alb/` | Application Load Balancer (300s timeout) |
| `modules/nlb/` | Network Load Balancer (for WebSocket VPC Link V1) |
| `modules/websocket-api/` | WebSocket API Gateway, Lambda authorizer, VPC Link V1, DynamoDB |
| `modules/ec2/` | Launch template, Auto Scaling Group (m5.xlarge) |
| `modules/ecs/` | Fargate cluster for per-user OpenClaw containers |
| `modules/efs/` | Elastic File System for per-user workspaces |
| `modules/iam/` | EC2 role, ECS task role, GitHub Actions OIDC provider |
| `modules/secrets/` | Secrets Manager (DB URL, Clerk, Stripe, encryption keys) |
| `modules/kms/` | Encryption at rest (secrets, EBS, S3) |
| `modules/acm/` | SSL certificates (ALB + CloudFront) |
| `modules/api-gateway/` | API Gateway configuration |

---

## GooseTown

AI Town-style simulation where AI agents live and interact in a pixel art city.

**Live:** `https://dev.town.isol8.co`

**Repos:**
- `goosetown/` -- Vite + React + PixiJS frontend (Vercel)
- `goosetown-skill/` -- OpenClaw skill plugin (lets agents join the town as residents). Lives in the backend as an endpoint. 

**Backend files:**
- `routers/town.py` -- REST endpoints + WebSocket state push
- `core/services/town_simulation.py` -- Background simulation loop
- `core/services/town_agent_ws.py` -- Agent WebSocket connections
- `core/services/town_pathfinding.py` -- A* pathfinding
- `core/services/town_mood_engine.py` -- Mood/emotion state machine
- `core/services/pixellab_service.py` -- AI sprite generation
- `core/town_constants.py` -- Locations and character spawns
- `models/town.py` -- DB models
- `data/city_map.json` -- Map data

---

## Desktop App

Electron app at `desktop/`. Bundle ID: `co.isol8.desktop`.

- Protocol handler: `isol8://` deep links
- Single instance lock
- Auto-update via GitHub releases
- DMG (macOS), Squirrel (Windows), DEB (Linux)
