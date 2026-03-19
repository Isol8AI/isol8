# Isol8 / GooseTown Monorepo Split Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `Isol8AI/isol8` into two in
dependent monorepos — Isol8 (Terraform/EC2) and GooseTown (CDK/Fargate/DynamoDB) — each with dev + prod environments.

**Architecture:** GooseTown becomes a platform-agnostic game server with its own CDK infrastructure, DynamoDB database, and Fargate compute. Isol8 keeps its current Terraform/EC2 architecture with town code removed. Both share only Clerk auth.

**Tech Stack:** Python/FastAPI, TypeScript/CDK, DynamoDB, ECS Fargate, API Gateway, Turborepo, pnpm, GitHub Actions

**Spec:** `docs/superpowers/specs/2026-03-17-monorepo-split-design.md`

---

## Chunk 1: Restructure GooseTown Repo Into Monorepo

**Context:** The `Isol8AI/goosetown` repo already exists at `~/Desktop/goosetown` as a standalone Vite+React frontend (old pre-monorepo structure). It has the frontend code at the repo root with `npm` (not pnpm). We need to restructure it into a Turborepo monorepo with `apps/frontend/`, `apps/backend/`, `apps/infra/`.

### Task 1: Restructure existing GooseTown repo into Turborepo monorepo

**Files:**
- Move: all existing frontend files into `apps/frontend/`
- Create: root `package.json`, `pnpm-workspace.yaml`, `turbo.json`
- Delete: root-level frontend config files (moved into `apps/frontend/`)

- [ ] **Step 1: Create apps directory and move frontend code**

Move all existing source code, configs, and assets into `apps/frontend/`:
```bash
cd ~/Desktop/goosetown
mkdir -p apps/frontend
# Move all frontend files (src/, public/, assets/, data/, etc.) into apps/frontend/
# Keep .git at root
```

Files to move into `apps/frontend/`:
- `src/`, `public/`, `assets/`, `data/`, `generated_tilesets/`, `pixellab-sprites/`, `scripts/`, `fly/`, `docs/`
- `package.json`, `tsconfig.json`, `tsconfig.check.json`, `vite.config.ts`, `tailwind.config.js`, `postcss.config.js`, `jest.config.ts`, `index.html`, `vercel.json`, `Dockerfile`, `docker-compose.yml`
- `.eslintrc.cjs`, `.eslintignore`, `.prettierrc`, `.vercelignore`, `.dockerignore`, `.vscode/`
- `town-v2-tileset.xml`, `pixellab-characters.md`, `ARCHITECTURE.md`, `README.md`, `LICENSE`

- [ ] **Step 2: Update apps/frontend/package.json**

Change `"name"` from `"ai-town"` to `"@goosetown/frontend"`.

- [ ] **Step 3: Create root package.json for Turborepo**

```json
{
  "name": "goosetown",
  "private": true,
  "devDependencies": {
    "turbo": "^2"
  },
  "packageManager": "pnpm@10.28.2"
}
```

- [ ] **Step 4: Create pnpm-workspace.yaml**

```yaml
packages:
  - apps/*
  - packages/*
```

- [ ] **Step 5: Create turbo.json**

```json
{
  "$schema": "https://turbo.build/schema.json",
  "tasks": {
    "build": {
      "dependsOn": ["^build"],
      "outputs": ["dist/**"]
    },
    "dev": {
      "cache": false,
      "persistent": true
    },
    "test": {
      "cache": true
    },
    "lint": {
      "cache": true
    }
  }
}
```

- [ ] **Step 6: Update root .gitignore**

Keep existing `.gitignore` entries, add:
```
cdk.out/
.turbo/
node_modules/
```

- [ ] **Step 7: Create apps/frontend/.env.example**

```bash
VITE_BACKEND_URL=https://api-dev.goosetown.isol8.co/api/v1
VITE_WS_URL=wss://ws-dev.goosetown.isol8.co
VITE_CLERK_PUBLISHABLE_KEY=pk_test_...
```

- [ ] **Step 8: Convert from npm to pnpm and install**

```bash
cd ~/Desktop/goosetown
rm -f package-lock.json  # remove npm lockfile from root (old one)
pnpm install
```

- [ ] **Step 9: Verify frontend builds**

```bash
pnpm --filter @goosetown/frontend run lint
pnpm --filter @goosetown/frontend run build
```

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "chore: restructure into Turborepo monorepo, move frontend to apps/frontend/"
git push
```

---

## Chunk 2: Extract GooseTown Backend

### Task 3: Scaffold the GooseTown FastAPI backend

**Files:**
- Create: `apps/backend/pyproject.toml`, `apps/backend/main.py`, `apps/backend/Dockerfile`

- [ ] **Step 1: Create backend directory and pyproject.toml**

```bash
mkdir -p ~/Desktop/goosetown/apps/backend
```

Create `apps/backend/pyproject.toml`:
```toml
[project]
name = "goosetown-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "boto3>=1.35",
    "pyjwt[crypto]>=2.9",
    "httpx>=0.28",
    "python-dotenv>=1.0",
    "requests>=2.32",
]

[tool.ruff]
line-length = 120
target-version = "py312"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create package.json shim for Turborepo**

Create `apps/backend/package.json`:
```json
{
  "name": "@goosetown/backend",
  "private": true,
  "scripts": {
    "dev": "uv run uvicorn main:app --reload --port 8001",
    "lint": "uv run ruff check . && uv run ruff format --check .",
    "test": "uv run pytest tests/ -v"
  }
}
```

- [ ] **Step 3: Initialize uv and install deps**

```bash
cd ~/Desktop/goosetown/apps/backend
uv sync
```

- [ ] **Step 4: Create minimal main.py**

```python
from dotenv import load_dotenv
load_dotenv()

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GooseTown backend starting")
    yield
    logger.info("GooseTown backend stopping")

app = FastAPI(title="GooseTown API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

- [ ] **Step 5: Verify it runs**

```bash
cd ~/Desktop/goosetown/apps/backend
uv run uvicorn main:app --port 8001
# In another terminal: curl http://localhost:8001/health
```

- [ ] **Step 6: Commit**

```bash
cd ~/Desktop/goosetown
git add apps/backend/
git commit -m "feat: scaffold GooseTown FastAPI backend"
git push
```

### Task 4: Create DynamoDB data layer

**Files:**
- Create: `apps/backend/core/dynamo.py`, `apps/backend/core/config.py`
- Create: `apps/backend/tests/unit/test_dynamo.py`

- [ ] **Step 1: Create core/config.py**

```python
"""GooseTown backend configuration."""
import os

class Settings:
    AWS_REGION: str = os.getenv("AWS_REGION", "us-east-1")
    DYNAMODB_TABLE_PREFIX: str = os.getenv("DYNAMODB_TABLE_PREFIX", "goosetown")
    CLERK_ISSUER: str = os.getenv("CLERK_ISSUER", "https://clerk.isol8.co")
    TOWN_TOKEN_SECRET: str = os.getenv("TOWN_TOKEN_SECRET", "")
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:5173")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "dev")
    PIXELLAB_API_KEY: str = os.getenv("PIXELLAB_API_KEY", "")
    SPRITE_S3_BUCKET: str = os.getenv("SPRITE_S3_BUCKET", "")
    SPRITE_CDN_URL: str = os.getenv("SPRITE_CDN_URL", "")

settings = Settings()
```

- [ ] **Step 2: Create core/dynamo.py — DynamoDB client + table helpers**

```python
"""DynamoDB client and table operations for GooseTown."""
import boto3
from core.config import settings

_client = None

def get_client():
    global _client
    if _client is None:
        _client = boto3.resource("dynamodb", region_name=settings.AWS_REGION)
    return _client

def table_name(name: str) -> str:
    return f"{settings.DYNAMODB_TABLE_PREFIX}-{name}"

def agents_table():
    return get_client().Table(table_name("agents"))

def instances_table():
    return get_client().Table(table_name("instances"))

def relationships_table():
    return get_client().Table(table_name("relationships"))

def conversations_table():
    return get_client().Table(table_name("conversations"))

def connections_table():
    return get_client().Table(table_name("connections"))
```

- [ ] **Step 3: Write tests for dynamo helpers**

Create `apps/backend/tests/__init__.py` and `apps/backend/tests/unit/__init__.py` (empty).

Create `apps/backend/tests/unit/test_dynamo.py`:
```python
from core.dynamo import table_name

def test_table_name_prefix():
    assert table_name("agents") == "goosetown-agents"
```

- [ ] **Step 4: Run test**

```bash
cd ~/Desktop/goosetown/apps/backend
uv run pytest tests/unit/test_dynamo.py -v
```

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/ apps/backend/tests/
git commit -m "feat: add DynamoDB client and config"
```

### Task 5: Port town service to DynamoDB

**Files:**
- Create: `apps/backend/core/services/town_service.py`
- Create: `apps/backend/tests/unit/services/test_town_service.py`
- Reference: `isol8/apps/backend/core/services/town_service.py`

This is the largest task — rewriting all SQLAlchemy queries to DynamoDB boto3 calls. The service methods stay the same but the data access changes.

- [ ] **Step 1: Create the town service with agent CRUD methods**

Create `apps/backend/core/__init__.py`, `apps/backend/core/services/__init__.py` (empty).

Create `apps/backend/core/services/town_service.py`. Port each method from the Isol8 version, replacing SQLAlchemy queries with DynamoDB operations:

Key method mappings:
- `get_active_agents()` → Query `isActive-joinedAt-index` GSI where `isActive = true`
- `get_town_state()` → Same GSI query, filter `spriteReady = true`, no join needed (agent+state merged)
- `_get_town_agent(user_id, agent_name)` → Query `userId-agentName-index` GSI
- `get_town_agent_by_id(agent_id)` → `agents_table().get_item(Key={"id": agent_id})`
- `update_agent_state(agent_id, **kwargs)` → `agents_table().update_item()` with expression builder
- `opt_in()` → `agents_table().put_item()` (agent + state fields merged)
- `get_instance_by_token(token)` → Query `townToken-index` GSI
- `get_active_instance(user_id)` → Query `userId-index` GSI, filter `isActive = true`
- `create_instance()` → `instances_table().put_item()`
- `get_or_create_relationship(a, b)` → `relationships_table().get_item()` with sorted keys, `put_item()` if not found
- `store_conversation()` → `conversations_table().put_item()` with sorted participant IDs
- `get_recent_conversations(limit)` → Query `status-startedAt-index` GSI, `ScanIndexForward=False`, `Limit=limit`

- [ ] **Step 2: Write tests using moto (DynamoDB mock)**

Add `moto[dynamodb]` to pyproject.toml dev dependencies.

Create `apps/backend/tests/conftest.py` with a pytest fixture that creates mock DynamoDB tables with the correct GSIs.

Create `apps/backend/tests/unit/services/test_town_service.py` with tests for:
- `test_opt_in_creates_agent`
- `test_opt_in_idempotent`
- `test_get_active_agents`
- `test_get_town_state`
- `test_create_instance`
- `test_get_or_create_relationship`
- `test_store_conversation`
- `test_get_recent_conversations`

- [ ] **Step 3: Run tests**

```bash
cd ~/Desktop/goosetown/apps/backend
uv run pytest tests/unit/services/test_town_service.py -v
```

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/services/ apps/backend/tests/
git commit -m "feat: port town service to DynamoDB"
```

### Task 6: Port remaining services

**Files:**
- Create: `apps/backend/core/services/town_simulation.py`
- Create: `apps/backend/core/services/town_mood_engine.py`
- Create: `apps/backend/core/services/town_pathfinding.py`
- Create: `apps/backend/core/services/town_agent_ws.py`
- Create: `apps/backend/core/services/pixellab_service.py`
- Create: `apps/backend/core/services/sprite_storage.py`
- Create: `apps/backend/core/town_constants.py`, `core/apartment_constants.py`, `core/town_token.py`
- Create: `apps/backend/data/` (map files)
- Reference: Corresponding files in `isol8/apps/backend/`

- [ ] **Step 1: Copy constants and data files**

These are unchanged — copy directly from Isol8:
```bash
cp ~/Desktop/isol8/apps/backend/core/town_constants.py ~/Desktop/goosetown/apps/backend/core/
cp ~/Desktop/isol8/apps/backend/core/apartment_constants.py ~/Desktop/goosetown/apps/backend/core/
cp ~/Desktop/isol8/apps/backend/core/town_token.py ~/Desktop/goosetown/apps/backend/core/
cp -r ~/Desktop/isol8/apps/backend/data/ ~/Desktop/goosetown/apps/backend/data/
```

- [ ] **Step 2: Copy mood engine and pathfinding (no DB dependency)**

These are pure logic — copy directly:
```bash
cp ~/Desktop/isol8/apps/backend/core/services/town_mood_engine.py ~/Desktop/goosetown/apps/backend/core/services/
cp ~/Desktop/isol8/apps/backend/core/services/town_pathfinding.py ~/Desktop/goosetown/apps/backend/core/services/
cp ~/Desktop/isol8/apps/backend/core/services/town_agent_ws.py ~/Desktop/goosetown/apps/backend/core/services/
```

- [ ] **Step 3: Port town_simulation.py**

Copy from Isol8 and modify:
- Replace `async with self._db_factory() as db: service = TownService(db)` with `service = TownService()` (no DB session — DynamoDB client is global)
- Remove ManagementApiClient dependency — replace with direct WebSocket push via `town_agent_ws` manager (GooseTown manages its own connections)
- Keep all simulation logic (movement, proximity, mood, pathfinding) unchanged

- [ ] **Step 4: Port pixellab_service.py and sprite_storage.py**

Copy from Isol8 and update S3 bucket references to use `settings.SPRITE_S3_BUCKET` and `settings.SPRITE_CDN_URL`.

- [ ] **Step 5: Copy and run existing tests for pure-logic services**

```bash
cp ~/Desktop/isol8/apps/backend/tests/unit/services/test_town_mood_engine.py ~/Desktop/goosetown/apps/backend/tests/unit/services/
cp ~/Desktop/isol8/apps/backend/tests/unit/services/test_town_pathfinding.py ~/Desktop/goosetown/apps/backend/tests/unit/services/
cp ~/Desktop/isol8/apps/backend/tests/unit/test_town_constants.py ~/Desktop/goosetown/apps/backend/tests/unit/
```

```bash
uv run pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add apps/backend/
git commit -m "feat: port simulation, mood engine, pathfinding, sprite services"
```

### Task 7: Port town router and wire up FastAPI app

**Files:**
- Create: `apps/backend/routers/town.py`
- Create: `apps/backend/core/auth.py`
- Modify: `apps/backend/main.py`

- [ ] **Step 1: Create auth.py (Clerk JWT validation)**

Port `core/auth.py` from Isol8, keeping only the JWT validation logic (PyJWT + JWKS). Remove any SQLAlchemy/user-model dependencies.

- [ ] **Step 2: Port routers/town.py**

Copy from Isol8 `routers/town.py` and modify:
- Replace `db: AsyncSession = Depends(get_db)` with direct `TownService()` instantiation
- Replace SQLAlchemy model references with dict returns from DynamoDB
- Keep all endpoint signatures and response schemas

- [ ] **Step 3: Port WebSocket message handling**

Extract town WebSocket handlers from Isol8's `websocket_chat.py` (lines 239-1041) into a new `routers/town_ws.py` in the GooseTown backend. This handles:
- `town_subscribe` / `town_unsubscribe` (viewer connections)
- `town_agent_connect` (agent registration)
- `town_agent_act` (agent actions)
- `town_agent_sleep` (agent sleep)

- [ ] **Step 4: Wire up main.py**

Update `apps/backend/main.py`:
- Import and include town router
- Start TownSimulation in lifespan hook
- Configure CORS from settings

- [ ] **Step 5: Run full test suite**

```bash
cd ~/Desktop/goosetown/apps/backend
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add apps/backend/
git commit -m "feat: wire up town router and FastAPI app with auth"
```

---

## Chunk 3: GooseTown CDK Infrastructure

### Task 8: Initialize CDK project

**Files:**
- Create: `apps/infra/` (CDK TypeScript project)

- [ ] **Step 1: Initialize CDK**

```bash
cd ~/Desktop/goosetown
mkdir apps/infra && cd apps/infra
npx cdk init app --language typescript
```

- [ ] **Step 2: Update package.json name**

Set `"name": "@goosetown/infra"` in `apps/infra/package.json`.

- [ ] **Step 3: Add CDK dependencies**

```bash
cd ~/Desktop/goosetown/apps/infra
npm install @aws-cdk/aws-apigatewayv2-alpha @aws-cdk/aws-apigatewayv2-integrations-alpha aws-cdk-lib constructs
```

- [ ] **Step 4: Add Turborepo shim scripts to package.json**

```json
{
  "scripts": {
    "build": "tsc",
    "lint": "tsc --noEmit",
    "test": "jest",
    "diff": "cdk diff",
    "deploy": "cdk deploy --all"
  }
}
```

- [ ] **Step 5: Commit**

```bash
cd ~/Desktop/goosetown
git add apps/infra/
git commit -m "chore: initialize CDK project"
```

### Task 9: Create CDK stacks

**Files:**
- Create: `apps/infra/lib/network-stack.ts`
- Create: `apps/infra/lib/database-stack.ts`
- Create: `apps/infra/lib/compute-stack.ts`
- Create: `apps/infra/lib/api-stack.ts`
- Create: `apps/infra/lib/storage-stack.ts`
- Create: `apps/infra/lib/auth-stack.ts`
- Create: `apps/infra/lib/dns-stack.ts`
- Modify: `apps/infra/bin/infra.ts` (entry point)

- [ ] **Step 1: Create NetworkStack**

VPC with 2 AZs, public + private subnets, NAT gateway.

- [ ] **Step 2: Create DatabaseStack**

4 DynamoDB tables with GSIs per the spec:
- `goosetown-{env}-agents` (3 GSIs)
- `goosetown-{env}-instances` (2 GSIs)
- `goosetown-{env}-relationships` (no GSI)
- `goosetown-{env}-conversations` (3 GSIs)
- `goosetown-{env}-connections` (connection state for WebSocket)

All tables use on-demand billing (`BillingMode.PAY_PER_REQUEST`).

- [ ] **Step 3: Create ComputeStack**

ECS Fargate service:
- Cluster in private subnets
- Task definition: 0.5 vCPU, 1 GB memory (dev), configurable for prod
- ALB in public subnets with WebSocket support (stickiness enabled, 300s idle timeout)
- ECR repository for backend Docker images
- Health check on `/health`

- [ ] **Step 4: Create ApiStack**

HTTP API Gateway for REST endpoints:
- Routes to ALB via VPC Link

WebSocket API Gateway:
- `$connect` route with Lambda authorizer (validates Clerk JWT or town token)
- `$disconnect` route with Lambda (cleans up connections table)
- `$default` route via VPC Link to ALB -> Fargate
- DynamoDB connections table for connectionId mapping
- Management API endpoint output for Fargate to push messages

- [ ] **Step 5: Create StorageStack**

S3 bucket + CloudFront distribution for sprites:
- Origin access identity
- CORS headers for cross-origin access
- Output CDN URL

- [ ] **Step 6: Create AuthStack**

Secrets Manager secrets:
- `goosetown/{env}/clerk_issuer`
- `goosetown/{env}/clerk_secret_key`
- `goosetown/{env}/town_token_secret`
- `goosetown/{env}/pixellab_api_key`

- [ ] **Step 7: Create DnsStack**

Route53 records + ACM certificates:
- `api-{env}.goosetown.isol8.co` -> ALB
- `ws-{env}.goosetown.isol8.co` -> WebSocket API Gateway
- `assets-{env}.goosetown.isol8.co` -> CloudFront

- [ ] **Step 8: Wire up entry point**

Update `apps/infra/bin/infra.ts` to instantiate all stacks with environment context:
```typescript
const env = app.node.tryGetContext("env") || "dev";
```

- [ ] **Step 9: Verify synthesis**

```bash
cd ~/Desktop/goosetown/apps/infra
npx cdk synth -c env=dev
```

- [ ] **Step 10: Commit**

```bash
cd ~/Desktop/goosetown
git add apps/infra/
git commit -m "feat: add CDK stacks for GooseTown infrastructure"
```

---

## Chunk 4: GooseTown CI/CD

### Task 10: Create GitHub Actions workflows

**Files:**
- Create: `.github/workflows/backend.yml`
- Create: `.github/workflows/frontend-ci.yml`
- Create: `.github/workflows/infra.yml`

- [ ] **Step 1: Create backend workflow**

`.github/workflows/backend.yml` — mirrors Isol8 backend workflow:
- Trigger: push to main + PR on `apps/backend/**`
- Jobs: test (ruff + pytest) -> build Docker -> push ECR -> Fargate deploy
- Fargate deploy: `aws ecs update-service --force-new-deployment`

- [ ] **Step 2: Create frontend CI workflow**

`.github/workflows/frontend-ci.yml`:
- Trigger: PR on `apps/frontend/**`
- Jobs: lint + typecheck + build
- Production deploy via Vercel auto-deploy (no GH Action needed)

- [ ] **Step 3: Create infra workflow**

`.github/workflows/infra.yml`:
- Trigger: push to main + PR on `apps/infra/**`
- PR job: `cdk diff -c env=dev`, post as PR comment
- Merge job: `cdk deploy --all -c env=dev --require-approval never`
- Infra changes also trigger backend redeploy (add `apps/infra/**` to backend workflow paths)

- [ ] **Step 4: Set up GitHub secrets**

```bash
gh secret set AWS_ACCOUNT_ID --repo Isol8AI/goosetown --body "877352799272"
gh secret set CLERK_PUBLISHABLE_KEY --repo Isol8AI/goosetown --body "<value>"
gh secret set CLERK_SECRET_KEY --repo Isol8AI/goosetown --body "<value>"
gh secret set TOWN_TOKEN_SECRET --repo Isol8AI/goosetown --body "<value>"
gh secret set PIXELLAB_API_KEY --repo Isol8AI/goosetown --body "<value>"
gh secret set VITE_CLERK_PUBLISHABLE_KEY --repo Isol8AI/goosetown --body "<value>"
```

- [ ] **Step 5: Commit and push**

```bash
cd ~/Desktop/goosetown
git add .github/
git commit -m "ci: add GitHub Actions workflows for backend, frontend, and infra"
git push
```

---

## Chunk 5: Deploy GooseTown Dev

### Task 11: Bootstrap CDK and deploy dev

- [ ] **Step 1: Bootstrap CDK in the AWS account**

```bash
cd ~/Desktop/goosetown/apps/infra
npx cdk bootstrap aws://877352799272/us-east-1
```

- [ ] **Step 2: Deploy all stacks to dev**

```bash
npx cdk deploy --all -c env=dev --require-approval never
```

- [ ] **Step 3: Note the outputs**

Record: ALB URL, API Gateway endpoints, ECR repo URI, WebSocket Management API URL, S3 bucket name, CloudFront URL.

- [ ] **Step 4: Build and push backend Docker image**

```bash
cd ~/Desktop/goosetown/apps/backend
docker build -t goosetown-backend .
# Tag and push to ECR (use outputs from step 3)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ecr-repo>
docker tag goosetown-backend:latest <ecr-repo>:latest
docker push <ecr-repo>:latest
```

- [ ] **Step 5: Force Fargate deployment**

```bash
aws ecs update-service --cluster goosetown-dev --service goosetown-dev-backend --force-new-deployment
```

- [ ] **Step 6: Verify health check**

```bash
curl https://api-dev.goosetown.isol8.co/health
# Expected: {"status": "healthy"}
```

### Task 12: Verification checklist

- [ ] **Step 1: Verify DynamoDB tables exist**

```bash
aws dynamodb list-tables --region us-east-1 | grep goosetown
```

- [ ] **Step 2: Verify WebSocket connectivity**

Use `wscat` to test viewer connection:
```bash
wscat -c "wss://ws-dev.goosetown.isol8.co?token=<clerk-jwt>"
```

- [ ] **Step 3: Verify sprite CDN**

```bash
curl -I https://assets-dev.goosetown.isol8.co/
```

- [ ] **Step 4: Set up Vercel project for frontend**

Connect `Isol8AI/goosetown` repo to Vercel, set root directory to `apps/frontend`, set environment variables for dev.

- [ ] **Step 5: Verify frontend loads**

Visit `https://dev.goosetown.isol8.co` and confirm the Godot game loads.

---

## Chunk 6: Clean Isol8 Repo

### Task 13: Remove GooseTown code from Isol8 backend

**Files:**
- Delete: `apps/backend/routers/town.py`
- Delete: `apps/backend/core/services/town_simulation.py`
- Delete: `apps/backend/core/services/town_service.py`
- Delete: `apps/backend/core/services/town_agent_ws.py`
- Delete: `apps/backend/core/services/town_mood_engine.py`
- Delete: `apps/backend/core/services/town_pathfinding.py`
- Delete: `apps/backend/core/services/pixellab_service.py`
- Delete: `apps/backend/core/services/sprite_storage.py`
- Delete: `apps/backend/core/town_constants.py`
- Delete: `apps/backend/core/apartment_constants.py`
- Delete: `apps/backend/core/town_token.py`
- Delete: `apps/backend/models/town.py`
- Delete: `apps/backend/schemas/town.py`
- Delete: `apps/backend/data/city_map.json`, `data/gentle_map.json`, `data/town-map.tmj`, `data/town-v2-map.tmj`, `data/goosetown/`, `data/goosetown-skill/`
- Delete: All town test files (9 files under `tests/unit/`)
- Modify: `apps/backend/main.py` (remove town imports, lifespan hook, router, OpenAPI tag)
- Modify: `apps/backend/routers/websocket_chat.py` (remove town handlers)
- Modify: `apps/backend/models/__init__.py` (remove town model exports)
- Modify: `apps/backend/tests/conftest.py` (remove town model imports and cleanup)
- Modify: `apps/backend/init_db.py` (remove town migration logic)

- [ ] **Step 1: Delete town-specific files**

```bash
cd ~/Desktop/isol8
rm apps/backend/routers/town.py
rm apps/backend/core/services/town_simulation.py
rm apps/backend/core/services/town_service.py
rm apps/backend/core/services/town_agent_ws.py
rm apps/backend/core/services/town_mood_engine.py
rm apps/backend/core/services/town_pathfinding.py
rm apps/backend/core/services/pixellab_service.py
rm apps/backend/core/services/sprite_storage.py
rm apps/backend/core/town_constants.py
rm apps/backend/core/apartment_constants.py
rm apps/backend/core/town_token.py
rm apps/backend/models/town.py
rm apps/backend/schemas/town.py
rm -rf apps/backend/data/goosetown-skill/
rm -rf apps/backend/data/goosetown/
rm apps/backend/data/city_map.json apps/backend/data/gentle_map.json
rm apps/backend/data/town-map.tmj apps/backend/data/town-v2-map.tmj
```

- [ ] **Step 2: Delete town test files**

```bash
rm apps/backend/tests/unit/routers/test_town.py
rm apps/backend/tests/unit/routers/test_town_ws_conversation.py
rm apps/backend/tests/unit/models/test_town.py
rm apps/backend/tests/unit/services/test_town_service.py
rm apps/backend/tests/unit/services/test_town_simulation.py
rm apps/backend/tests/unit/services/test_town_agent_ws.py
rm apps/backend/tests/unit/services/test_town_pathfinding.py
rm apps/backend/tests/unit/services/test_town_mood_engine.py
rm apps/backend/tests/unit/test_town_constants.py
```

- [ ] **Step 3: Clean main.py**

Remove:
- `from core.services.town_simulation import TownSimulation` (line 22)
- `town` from router imports (line 33)
- `_town_simulation` variable (line 41)
- TownSimulation startup block in lifespan (lines 54-62)
- TownSimulation shutdown block (lines 75-76)
- Town OpenAPI tag (lines 95-96)
- `app.include_router(town.router, ...)` (line 224)

- [ ] **Step 4: Clean websocket_chat.py**

Remove:
- Town imports (lines 27-28)
- Town viewer cleanup on disconnect (lines 155-161)
- Town agent cleanup on disconnect (lines 163-190)
- `town_subscribe` handler (lines 239-243)
- `town_unsubscribe` handler (lines 245-248)
- `town_agent_connect` handler (lines 317-437)
- `town_agent_act` handler (lines 438-986)
- `town_agent_sleep` handler (lines 987-1041)

- [ ] **Step 5: Clean models/__init__.py**

Remove TownAgent, TownState, TownConversation, TownRelationship exports (line 8).

- [ ] **Step 6: Clean tests/conftest.py**

Remove town model imports (line 24) and town table cleanup (lines 82-83).

- [ ] **Step 7: Clean init_db.py**

Remove town state migration logic (lines 62-70).

- [ ] **Step 8: Run tests to verify nothing is broken**

```bash
cd ~/Desktop/isol8/apps/backend
uv run ruff check . && uv run ruff format --check .
uv run pytest tests/ -v
```

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor: remove all GooseTown code from Isol8 backend"
```

### Task 14: Remove GooseTown frontend and infra from Isol8

**Files:**
- Delete: `apps/goosetown/` (entire directory)
- Delete: `.github/workflows/goosetown-ci.yml`
- Modify: `apps/terraform/main.tf` (remove sprite S3/CloudFront resources)
- Modify: `CLAUDE.md` (remove GooseTown references)

- [ ] **Step 1: Delete goosetown frontend**

```bash
rm -rf apps/goosetown/
rm .github/workflows/goosetown-ci.yml
```

- [ ] **Step 2: Remove town-specific Terraform resources**

From `apps/terraform/main.tf`, remove:
- `aws_s3_bucket.town_sprites`
- `aws_cloudfront_distribution.town_sprites`
- `aws_cloudfront_response_headers_policy.town_sprites_cors`
- `aws_cloudfront_origin_access_identity.town_sprites`
- `aws_s3_bucket_policy.town_sprites`
- `aws_route53_record.town_sprites_cdn`
- Town-related variables from tfvars (`town_frontend_url`, `town_assets_cert_arn`)
- Town-related secrets from the secrets module (`town_token_secret`, `pixellab_api_key`)

- [ ] **Step 3: Update CLAUDE.md**

Remove all GooseTown sections: GooseTown overview, backend files, frontend files, architecture diagram references.

- [ ] **Step 4: Run full lint and tests**

```bash
cd ~/Desktop/isol8
turbo run lint
turbo run test
```

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove GooseTown frontend, CI, and terraform resources"
```

---

## Chunk 7: Productionize Isol8

### Task 15: Add prod environment to Isol8

**Files:**
- Create: `apps/terraform/environments/prod/terraform.tfvars`
- Create: `apps/terraform/environments/prod/backend.hcl`
- Modify: `.github/workflows/terraform.yml` (add prod plan/apply jobs)
- Modify: `.github/workflows/backend.yml` (enable prod deploy job)

- [ ] **Step 1: Create prod tfvars**

Create `apps/terraform/environments/prod/terraform.tfvars` based on dev, with:
- `environment = "prod"`
- `domain_name = "api.isol8.co"`
- `frontend_url = "https://isol8.co"`
- EC2 instance type: keep `r5.xlarge` for prod initially, evaluate after load testing
- Production Stripe price IDs (to be created when going live)

- [ ] **Step 2: Create prod backend.hcl**

```hcl
bucket  = "isol8-prod-terraform-state"
key     = "terraform.tfstate"
region  = "us-east-1"
encrypt = true
```

- [ ] **Step 3: Add prod plan/apply to terraform workflow**

Add `plan-prod` and `apply-prod` jobs to `.github/workflows/terraform.yml`, gated on the `prod` GitHub environment for approval.

- [ ] **Step 4: Enable prod deploy in backend workflow**

Update `.github/workflows/backend.yml` — change the prod deploy job from `if: false` to trigger on `workflow_dispatch` with environment approval.

- [ ] **Step 5: Remove staging references**

Remove staging plan/apply jobs and staging tfvars if they exist.

- [ ] **Step 6: Set up Vercel production domain**

Configure `isol8.co` domain in the Vercel frontend project settings.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "feat: add production environment, remove staging"
```

---

## Chunk 8: Productionize GooseTown

### Task 16: Add prod environment to GooseTown CDK

**Files:**
- Modify: `apps/infra/bin/infra.ts` (add prod context)
- Modify: `.github/workflows/infra.yml` (add prod deploy)
- Modify: `.github/workflows/backend.yml` (add prod deploy)

- [ ] **Step 1: Add prod configuration to CDK**

The CDK stacks are already parameterized by `env` context. Add prod-specific sizing:
- Fargate: 1 vCPU, 2 GB (prod) vs 0.5 vCPU, 1 GB (dev)
- DynamoDB: same on-demand billing (scales automatically)

- [ ] **Step 2: Add prod deploy to infra workflow**

Add `cdk deploy --all -c env=prod` job gated on `prod` environment approval.

- [ ] **Step 3: Add prod deploy to backend workflow**

Add Fargate deploy job for prod cluster, gated on environment approval.

- [ ] **Step 4: Deploy prod infrastructure**

```bash
cd ~/Desktop/goosetown/apps/infra
npx cdk deploy --all -c env=prod
```

- [ ] **Step 5: Set up Vercel production domain**

Configure `goosetown.isol8.co` domain in the Vercel frontend project settings.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat: add production environment for GooseTown"
```

---

## Chunk 9: DNS Cutover

### Task 17: Configure DNS for all new domains

- [ ] **Step 1: Verify Route53 records created by CDK**

```bash
aws route53 list-resource-record-sets --hosted-zone-id <zone-id> | grep goosetown
```

Expected records:
- `api-dev.goosetown.isol8.co` -> ALB
- `api.goosetown.isol8.co` -> ALB (prod)
- `ws-dev.goosetown.isol8.co` -> WebSocket API Gateway
- `ws.goosetown.isol8.co` -> WebSocket API Gateway (prod)
- `assets-dev.goosetown.isol8.co` -> CloudFront
- `assets.goosetown.isol8.co` -> CloudFront (prod)

- [ ] **Step 2: Verify Vercel domains**

- `dev.goosetown.isol8.co` -> Vercel preview
- `goosetown.isol8.co` -> Vercel production

- [ ] **Step 3: Verify Isol8 domains unchanged**

- `dev.isol8.co`, `isol8.co` -> Vercel
- `api-dev.isol8.co`, `api.isol8.co` -> ALB
- `ws-dev.isol8.co`, `ws.isol8.co` -> WebSocket API Gateway

- [ ] **Step 4: End-to-end verification**

Test both platforms:
```bash
# Isol8
curl https://api-dev.isol8.co/health
curl https://api.isol8.co/health

# GooseTown
curl https://api-dev.goosetown.isol8.co/health
curl https://api.goosetown.isol8.co/health
```

Visit both frontends and verify functionality.

- [ ] **Step 5: Drop town tables from Supabase**

After confirming GooseTown is fully operational on DynamoDB:
```sql
DROP TABLE IF EXISTS town_state CASCADE;
DROP TABLE IF EXISTS town_conversations CASCADE;
DROP TABLE IF EXISTS town_relationships CASCADE;
DROP TABLE IF EXISTS town_agents CASCADE;
DROP TABLE IF EXISTS town_instances CASCADE;
```
