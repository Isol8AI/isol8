# Isol8 CDK Migration Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate isol8 infrastructure from Terraform to CDK (TypeScript), replace Supabase with RDS PostgreSQL, and deploy dev + prod environments.

**Architecture:** 7 CDK stacks (Network, Database, Auth, DNS, Compute, Container, API) following the same `lib/app.ts` + `lib/stacks/` pattern as goosetown. EC2 ASG for backend compute, ECS Fargate for per-user containers, dual API Gateways (HTTP + WebSocket).

**Tech Stack:** AWS CDK 2.x (TypeScript), RDS PostgreSQL, EC2 ASG, ECS Fargate, API Gateway v2, EFS, Lambda, Route53, ACM, Secrets Manager, KMS

**Spec:** `docs/superpowers/specs/2026-03-19-isol8-cdk-migration-design.md`

---

## File Structure

```
apps/infra/
  lib/
    app.ts                           ← CDK entry point, stack orchestration, OIDC role
    stacks/
      network-stack.ts               ← VPC, subnets, NAT
      database-stack.ts              ← RDS PostgreSQL, security group
      auth-stack.ts                  ← Secrets Manager secrets, KMS key
      dns-stack.ts                   ← ACM wildcard cert, Route53 lookup
      compute-stack.ts               ← EC2 ASG, ALB, launch template, ECR, IAM
      container-stack.ts             ← ECS Fargate cluster, Cloud Map, EFS
      api-stack.ts                   ← HTTP + WebSocket API GW, VPC Links, NLB, Lambda authorizer
    user-data.sh                     ← EC2 bootstrap script (ported from terraform)
  lambda/
    websocket-authorizer/
      index.py                       ← Lambda authorizer (ported from terraform)
      requirements.txt
  cdk.json
  package.json
  tsconfig.json

.github/workflows/
  infra.yml                          ← Replace terraform.yml with CDK workflow
  backend.yml                        ← Update deploy steps for prod stage
```

---

## Phase 1: Create CDK Project

### Task 1: Initialize CDK project

**Files:**
- Create: `apps/infra/package.json`, `apps/infra/tsconfig.json`, `apps/infra/cdk.json`

- [ ] **Step 1: Create infra directory and initialize**

```bash
cd ~/Desktop/isol8.nosync
mkdir -p apps/infra
cd apps/infra
npx cdk init app --language typescript
```

- [ ] **Step 2: Update package.json name**

Set `"name": "@isol8/infra"` in `apps/infra/package.json`.

- [ ] **Step 3: Install additional CDK dependencies**

```bash
npm install cdk-nag
```

- [ ] **Step 4: Update cdk.json app entry point**

Change `"app"` from `"npx ts-node --prefer-ts-exts bin/infra.ts"` to `"npx ts-node --prefer-ts-exts lib/app.ts"`.

- [ ] **Step 5: Remove bin/ directory**

```bash
rm -rf bin/
mkdir -p lib/stacks
```

- [ ] **Step 6: Verify project compiles**

```bash
npx cdk synth 2>&1 | head -5
```

- [ ] **Step 7: Commit**

```bash
git add apps/infra/
git commit -m "chore: initialize CDK project for isol8"
```

---

### Task 2: NetworkStack

**Files:**
- Create: `apps/infra/lib/stacks/network-stack.ts`

- [ ] **Step 1: Write NetworkStack**

```typescript
// VPC with public + private subnets, NAT gateway
// 2 AZs for dev, 3 for prod
// Parameterized by environment context
```

Reference: GooseTown's `network-stack.ts` for pattern. Key difference: isol8 dev uses CIDR `10.0.0.0/16`, prod uses `10.2.0.0/16`.

- [ ] **Step 2: Verify synth**

```bash
npx cdk synth -c env=dev 2>&1 | grep "Successfully"
```

- [ ] **Step 3: Commit**

```bash
git add apps/infra/lib/stacks/network-stack.ts
git commit -m "feat: add NetworkStack (VPC, subnets, NAT)"
```

---

### Task 3: AuthStack

**Files:**
- Create: `apps/infra/lib/stacks/auth-stack.ts`

- [ ] **Step 1: Write AuthStack**

Create Secrets Manager secrets (empty placeholders — values set out-of-band):
- `isol8/{env}/clerk_secret_key`
- `isol8/{env}/clerk_webhook_secret`
- `isol8/{env}/stripe_secret_key`
- `isol8/{env}/stripe_webhook_secret`
- `isol8/{env}/huggingface_token`
- `isol8/{env}/perplexity_api_key`
- `isol8/{env}/encryption_key`

Create KMS key for encryption (EBS, EFS, RDS).

Export `secrets` interface and `kmsKey`.

- [ ] **Step 2: Verify synth**

- [ ] **Step 3: Commit**

```bash
git add apps/infra/lib/stacks/auth-stack.ts
git commit -m "feat: add AuthStack (Secrets Manager, KMS)"
```

---

### Task 4: DnsStack

**Files:**
- Create: `apps/infra/lib/stacks/dns-stack.ts`

- [ ] **Step 1: Write DnsStack**

- Lookup existing `isol8.co` hosted zone via `HostedZone.fromLookup`
- Create ACM wildcard certificate for `*.isol8.co` with DNS validation
- Export `certificate` and `hostedZone`
- No A records here (created by other stacks to avoid circular deps)

Reference: GooseTown's `dns-stack.ts` — same pattern.

- [ ] **Step 2: Verify synth**

- [ ] **Step 3: Commit**

```bash
git add apps/infra/lib/stacks/dns-stack.ts
git commit -m "feat: add DnsStack (ACM wildcard cert, Route53)"
```

---

### Task 5: DatabaseStack

**Files:**
- Create: `apps/infra/lib/stacks/database-stack.ts`

- [ ] **Step 1: Write DatabaseStack**

- RDS PostgreSQL instance:
  - Engine: PostgreSQL 15
  - Instance: `db.t3.small` (dev) / `db.t3.medium` (prod)
  - Multi-AZ: false (dev) / true (prod)
  - Private subnet placement
  - Encrypted storage via KMS key from AuthStack
  - Automated backups (7 day retention dev, 30 day prod)
  - Auto-generated credentials in Secrets Manager
- Security group: allow port 5432 from EC2 and ECS security groups
- Export `dbInstance`, `dbSecurityGroup`, `dbSecret`

- [ ] **Step 2: Verify synth**

- [ ] **Step 3: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts
git commit -m "feat: add DatabaseStack (RDS PostgreSQL)"
```

---

### Task 6: ContainerStack

**Files:**
- Create: `apps/infra/lib/stacks/container-stack.ts`

- [ ] **Step 1: Write ContainerStack**

- ECS Fargate cluster in private subnets
- Cloud Map namespace: `isol8-{env}.local`
- Cloud Map service for container discovery
- EFS filesystem:
  - Encrypted via KMS
  - Mount targets in each private subnet
  - Lifecycle policy (transition to IA after 30 days)
  - Security group: allow NFS (port 2049) from EC2 and Fargate
- ECS task execution role (ECR pull, CloudWatch logs, Secrets Manager read)
- ECS task role (Bedrock invoke, EFS, CloudWatch)
- Export `cluster`, `cloudMapNamespace`, `cloudMapService`, `efsFileSystem`, `efsSecurityGroup`, `taskExecutionRole`, `containerSecurityGroup`

Reference: Current terraform `modules/ecs/`, `modules/efs/` and `main.tf` ECS/EFS sections. Also reference goosetown's container patterns but note isol8 uses Cloud Map service discovery (not just a cluster).

- [ ] **Step 2: Verify synth**

- [ ] **Step 3: Commit**

```bash
git add apps/infra/lib/stacks/container-stack.ts
git commit -m "feat: add ContainerStack (ECS Fargate, Cloud Map, EFS)"
```

---

### Task 7: ComputeStack

**Files:**
- Create: `apps/infra/lib/stacks/compute-stack.ts`
- Create: `apps/infra/lib/user-data.sh`

- [ ] **Step 1: Port user_data.sh from terraform**

Copy `apps/terraform/modules/ec2/user_data.sh` to `apps/infra/lib/user-data.sh`. Update:
- Replace terraform template variables (`${variable}`) with CDK `Fn.sub` or shell variables set by launch template
- Remove `S3_CONFIG_BUCKET` (dead code)
- Keep: Docker install, ECR login, secrets fetch, EFS mount, systemd service, env file creation

- [ ] **Step 2: Write ComputeStack**

- ECR repository: `isol8-{env}-backend`
- EC2 Auto Scaling Group:
  - Launch template with Amazon Linux 2023 AMI
  - Instance type: `t3.large` (parameterized)
  - User data script from `user-data.sh`
  - IAM instance profile with permissions:
    - ECR: pull images
    - ECS: RunTask, StopTask, DescribeTasks, RegisterTaskDefinition
    - EFS: mount via security group
    - Secrets Manager: GetSecretValue for all isol8 secrets + RDS credentials
    - Bedrock: InvokeModel
    - CloudWatch: logs, metrics
    - Cloud Map: RegisterInstance, DeregisterInstance, DiscoverInstances
    - KMS: Decrypt
  - EBS encrypted via KMS
  - Security group: allow ALB on port 8000, allow EFS on port 2049
  - Min/desired/max: 1/1/2 (dev), 1/1/3 (prod)
- ALB (internal):
  - HTTPS listener with ACM cert
  - HTTP → HTTPS redirect
  - Idle timeout: 300s (for SSE)
  - Sticky sessions
  - Health check: `/health`, interval 30s, 2 healthy / 3 unhealthy
  - Target group: port 8000
- Export `alb`, `asg`, `repository`, `ec2SecurityGroup`

- [ ] **Step 3: Verify synth**

- [ ] **Step 4: Commit**

```bash
git add apps/infra/lib/stacks/compute-stack.ts apps/infra/lib/user-data.sh
git commit -m "feat: add ComputeStack (EC2 ASG, ALB, ECR)"
```

---

### Task 8: ApiStack

**Files:**
- Create: `apps/infra/lib/stacks/api-stack.ts`
- Create: `apps/infra/lambda/websocket-authorizer/index.py`
- Create: `apps/infra/lambda/websocket-authorizer/requirements.txt`

- [ ] **Step 1: Port Lambda authorizer from terraform**

Copy `apps/terraform/lambda/websocket-authorizer/index.py` and `requirements.txt` to `apps/infra/lambda/websocket-authorizer/`. The authorizer validates Clerk JWTs on WebSocket `$connect`. No changes needed to the logic.

- [ ] **Step 2: Write ApiStack**

- HTTP API Gateway (APIGatewayV2):
  - Custom domain: `api-{env}.isol8.co` (or `api.isol8.co` for prod) with ACM cert
  - API Gateway domain name mapping
  - Default route → VPC Link v2 → ALB (internal)
  - Rate limiting: 100 rps burst, 50 rps sustained (dev), higher for prod
  - Route53 A record for custom domain
- WebSocket API Gateway:
  - Custom domain: `ws-{env}.isol8.co` (or `ws.isol8.co` for prod)
  - `$connect` route with Lambda authorizer
  - `$disconnect` route with Lambda (removes from connections table — or can be handled by backend)
  - `$default` route → VPC Link v1 → NLB → ALB → EC2
  - DynamoDB connections table for `connectionId` → `userId` mapping
  - API Gateway domain name mapping
  - Route53 CNAME record for custom domain
- NLB in private subnets (required for WebSocket VPC Link v1)
  - Target group pointing to ALB on port 8000
- Lambda authorizer:
  - Python 3.11 runtime
  - Bundled with `pyjwt[crypto]`, `requests`
  - Environment: `CLERK_ISSUER`, `CLERK_JWKS_URL` from secrets
- Management API endpoint output (for EC2 backend to push via `@connections`)
- IAM grant for EC2 instance role to call Management API
- Export `httpApiUrl`, `webSocketUrl`, `managementApiUrl`

Reference: GooseTown's `api-stack.ts` for WebSocket patterns. Isol8's terraform `modules/websocket-api/` and `main.tf` API Gateway sections for exact config.

- [ ] **Step 3: Verify synth**

- [ ] **Step 4: Commit**

```bash
git add apps/infra/lib/stacks/api-stack.ts apps/infra/lambda/
git commit -m "feat: add ApiStack (HTTP + WebSocket API GW, Lambda authorizer)"
```

---

### Task 9: app.ts — Stack Orchestration

**Files:**
- Create: `apps/infra/lib/app.ts`

- [ ] **Step 1: Write app.ts**

Wire all 7 stacks with dependencies:

```typescript
// Foundation (no deps)
const network = new NetworkStack(...)
const auth = new AuthStack(...)
const dns = new DnsStack(...)

// Data layer
const database = new DatabaseStack(..., { vpc: network.vpc, kmsKey: auth.kmsKey })
const container = new ContainerStack(..., { vpc: network.vpc, kmsKey: auth.kmsKey })

// Compute (depends on everything above)
const compute = new ComputeStack(..., {
  vpc: network.vpc, database, auth, dns, container
})

// API (depends on compute for ALB)
const api = new ApiStack(..., {
  vpc: network.vpc, alb: compute.alb, auth, dns,
  ec2SecurityGroup: compute.ec2SecurityGroup
})
```

Add:
- GitHub OIDC role (inline, with AdministratorAccess for now)
- CDK Nag `AwsSolutionsChecks`
- Tags: `Project=isol8`, `Environment={env}`

Environment config: read `env` from context, set sizing accordingly.

- [ ] **Step 2: Verify full synth**

```bash
AWS_PROFILE=isol8-admin npx cdk synth -c env=dev 2>&1 | grep "Successfully"
```

Expected: `Successfully synthesized to .../cdk.out` with all 7 stacks listed.

- [ ] **Step 3: Commit**

```bash
git add apps/infra/lib/app.ts
git commit -m "feat: wire all CDK stacks in app.ts"
```

---

## Phase 2: Deploy CDK Dev

### Task 10: Deploy all stacks to dev

- [ ] **Step 1: Deploy DNS stack first** (cert needs time to validate)

```bash
AWS_PROFILE=isol8-admin npx cdk deploy isol8-dev-dns -c env=dev --require-approval never
```

- [ ] **Step 2: Deploy all stacks**

```bash
AWS_PROFILE=isol8-admin npx cdk deploy --all -c env=dev --require-approval never
```

- [ ] **Step 3: Record outputs**

Note: ALB DNS, ECR repo URI, RDS endpoint, WebSocket URL, Management API URL, EFS ID, ECS cluster ARN, Cloud Map namespace/service IDs.

- [ ] **Step 4: Populate secrets**

Copy secret values from existing terraform-managed secrets to new CDK-managed secrets:
```bash
# For each secret, copy from isol8/dev/* to new isol8-cdk/dev/* (or reuse same secret names)
```

- [ ] **Step 5: Initialize RDS database schema**

```bash
# Connect to RDS and run init_db.py
# The RDS credentials are in Secrets Manager (auto-generated by CDK)
```

- [ ] **Step 6: Build and push Docker image to new ECR**

```bash
cd apps/backend
docker build --platform linux/amd64 -t isol8-backend .
# Tag and push to new ECR repo
```

- [ ] **Step 7: Trigger ASG instance refresh**

```bash
AWS_PROFILE=isol8-admin aws autoscaling start-instance-refresh \
  --auto-scaling-group-name isol8-dev-asg \
  --preferences '{"MinHealthyPercentage": 50, "InstanceWarmup": 60}'
```

- [ ] **Step 8: Verify health check**

```bash
curl -sk https://<ALB-DNS>/health
# Expected: {"status":"healthy","database":"connected"}
```

- [ ] **Step 9: Commit any adjustments**

---

## Phase 3: Cut Over DNS + CI/CD

### Task 11: Update CI/CD workflows

**Files:**
- Create: `.github/workflows/infra.yml` (replace terraform workflow with CDK)
- Modify: `.github/workflows/backend.yml` (add prod deploy, update ASG names)

- [ ] **Step 1: Write new infra.yml**

CDK-based workflow:
- PR: `cdk diff -c env=dev` posted as comment
- Merge to main: `cdk deploy --all -c env=dev` (auto)
- Prod: `cdk deploy --all -c env=prod` (gated on `prod` environment)

- [ ] **Step 2: Update backend.yml**

- Update ASG name references to match CDK-created ASG
- Add prod deploy job (gated on `prod` environment)
- Remove terraform path trigger
- Add `workflow_run` trigger from infra workflow

- [ ] **Step 3: Create `prod` GitHub environment**

```bash
gh api repos/Isol8AI/isol8/environments/prod -X PUT \
  --field 'reviewers[][type]=User' \
  --field 'reviewers[][id]=<your-user-id>'
```

- [ ] **Step 4: Commit and push**

```bash
git add .github/workflows/
git commit -m "ci: replace terraform with CDK workflow, add prod deploy"
```

---

### Task 12: DNS cutover

- [ ] **Step 1: Verify CDK-managed DNS records exist**

The ApiStack should have created:
- `api-dev.isol8.co` → HTTP API Gateway custom domain
- `ws-dev.isol8.co` → WebSocket API Gateway custom domain

```bash
AWS_PROFILE=isol8-admin aws route53 list-resource-record-sets \
  --hosted-zone-id Z09248243AOUC775CDUI4 \
  --query "ResourceRecordSets[?contains(Name, 'isol8.co')].{Name:Name,Type:Type}" \
  --output table
```

- [ ] **Step 2: Verify endpoints work**

```bash
curl https://api-dev.isol8.co/health
# Expected: {"status":"healthy","database":"connected"}
```

- [ ] **Step 3: Update Vercel env vars**

Set Preview/Development env vars to CDK-managed backend URLs:
- `NEXT_PUBLIC_API_URL` = `https://api-dev.isol8.co/api/v1`
- WebSocket URL if applicable

---

## Phase 4: Tear Down Terraform

### Task 13: Remove terraform

- [ ] **Step 1: Terraform destroy dev**

```bash
cd apps/terraform
AWS_PROFILE=isol8-admin terraform init -backend-config=environments/dev/backend.hcl
AWS_PROFILE=isol8-admin terraform destroy \
  -var-file=environments/dev/terraform.tfvars \
  -var="supabase_connection_string=x" \
  -var="huggingface_token=x" \
  -var="clerk_secret_key=x" \
  -var="clerk_webhook_secret=x" \
  -var="perplexity_api_key=x" \
  -var="encryption_key=x" \
  -var="stripe_secret_key=x" \
  -var="stripe_webhook_secret=x"
```

**IMPORTANT:** Verify CDK dev is fully working BEFORE running destroy. This is irreversible.

- [ ] **Step 2: Delete terraform directory**

```bash
rm -rf apps/terraform/
```

- [ ] **Step 3: Delete old terraform workflow**

```bash
rm .github/workflows/terraform.yml
```

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove terraform, fully migrated to CDK"
git push
```

---

## Phase 5: Deploy Prod

### Task 14: Deploy prod infrastructure

- [ ] **Step 1: Deploy all CDK stacks to prod**

```bash
AWS_PROFILE=isol8-admin npx cdk deploy --all -c env=prod --require-approval never
```

- [ ] **Step 2: Populate prod secrets**

Set production values in Secrets Manager for:
- Clerk prod keys
- Stripe live keys (or test keys initially)
- Huggingface token
- Perplexity API key
- Encryption key

- [ ] **Step 3: Initialize prod RDS schema**

Run `init_db.py` against the prod RDS instance.

- [ ] **Step 4: Build and push Docker image**

Same image as dev — push to prod ECR repo.

- [ ] **Step 5: Trigger prod ASG instance refresh**

- [ ] **Step 6: Verify prod health**

```bash
curl https://api.isol8.co/health
```

---

### Task 15: Set up Vercel production

- [ ] **Step 1: Add production domain**

Add `isol8.co` to the Vercel project as the production domain.

- [ ] **Step 2: Create Route53 A record**

Point `isol8.co` to Vercel (76.76.21.21).

- [ ] **Step 3: Set production env vars**

In Vercel project, set `Production` environment:
- `NEXT_PUBLIC_API_URL` = `https://api.isol8.co/api/v1`

Set `Preview` + `Development` environments:
- `NEXT_PUBLIC_API_URL` = `https://api-dev.isol8.co/api/v1`

- [ ] **Step 4: Trigger production deploy**

```bash
npx vercel deploy --prod --yes
```

- [ ] **Step 5: End-to-end verification**

```bash
# Backend
curl https://api.isol8.co/health
curl https://api-dev.isol8.co/health

# Frontend
curl -s https://isol8.co | grep "<title>"

# WebSocket
wscat -c "wss://ws.isol8.co?token=<test-jwt>"
wscat -c "wss://ws-dev.isol8.co?token=<test-jwt>"
```

- [ ] **Step 6: Commit any final adjustments**

```bash
git add -A
git commit -m "feat: isol8 CDK migration complete, dev + prod deployed"
git push
```
