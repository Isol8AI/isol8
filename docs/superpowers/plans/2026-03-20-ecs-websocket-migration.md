# ECS Fargate + Lambda WebSocket Migration Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace EC2 ASG with ECS Fargate for the backend, replace NLB + VPC Link v1 WebSocket with Lambda-based WebSocket handlers, and eliminate the circular dependency between compute and API stacks.

**Architecture:** Move ALB into NetworkStack (breaking circular dependency). Replace ComputeStack (EC2 ASG) with ServiceStack (Fargate service). Replace L1 WebSocket constructs in ApiStack with L2 `WebSocketApi` + Lambda integrations. No backend application code changes.

**Tech Stack:** AWS CDK 2.x (TypeScript), ECS Fargate, Lambda (Python), API Gateway v2 WebSocket, DynamoDB, ALB

**Spec:** `docs/superpowers/specs/2026-03-20-ecs-websocket-migration-design.md`

---

## File Structure

```
apps/infra/
  lib/
    stacks/
      network-stack.ts         ← MODIFY: add ALB, target group, listeners
      service-stack.ts         ← CREATE: Fargate service (replaces compute-stack.ts)
      api-stack.ts             ← REWRITE: L2 WebSocket + Lambda, simplified HTTP API
      compute-stack.ts         ← DELETE (replaced by service-stack.ts)
    user-data.sh               ← DELETE (no longer needed)
    isol8-stage.ts             ← MODIFY: rewire stacks
    app.ts                     ← MODIFY: no changes needed (pipeline stays)
  lambda/
    ws-connect/index.py        ← CREATE: $connect handler
    ws-disconnect/index.py     ← CREATE: $disconnect handler
    ws-message/index.py        ← CREATE: $default handler

apps/backend/
  Dockerfile                   ← MODIFY: add init_db.py to CMD
```

---

## Phase 1: Infrastructure Changes

### Task 1: Move ALB into NetworkStack

**Files:**
- Modify: `apps/infra/lib/stacks/network-stack.ts`

- [ ] **Step 1: Read current network-stack.ts and compute-stack.ts ALB section**

Read `network-stack.ts` (full file) and `compute-stack.ts` lines 120-190 (ALB, target group, listeners, security group).

- [ ] **Step 2: Add ALB to NetworkStack**

Add to `NetworkStackProps`:
```typescript
certificate?: acm.ICertificate;
```

Add to `NetworkStack`:
- ALB security group (allow 443 + 80 from VPC CIDR)
- ALB (internal, private subnets, 300s idle timeout)
- Target group (port 8000, HTTP, IP target type — Fargate uses `awsvpc`)
  - Health check: `/health`, interval 30s, 2 healthy / 3 unhealthy
  - Sticky sessions: 1 hour
- HTTPS listener (443, ACM cert, forwards to target group)
- HTTP listener (80, forwards to target group — for API Gateway VPC Link)

Export: `alb`, `albSecurityGroup`, `targetGroup`, `albHttpListenerArn`, `albHttpsListenerArn`

Note: target type must be `IP` (not `INSTANCE`) for Fargate compatibility.

- [ ] **Step 3: Verify synth**

```bash
cd apps/infra && AWS_PROFILE=isol8-admin npx cdk synth -q 2>&1 | grep "Successfully"
```

- [ ] **Step 4: Commit**

```bash
git add apps/infra/lib/stacks/network-stack.ts
git commit -m "feat: move ALB into NetworkStack (breaks circular dep)"
```

---

### Task 2: Create Lambda WebSocket handlers

**Files:**
- Create: `apps/infra/lambda/ws-connect/index.py`
- Create: `apps/infra/lambda/ws-disconnect/index.py`
- Create: `apps/infra/lambda/ws-message/index.py`

- [ ] **Step 1: Create ws-connect Lambda**

```python
"""WebSocket $connect handler — stores connection in DynamoDB, notifies backend."""
import os
import urllib.request
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    authorizer = event["requestContext"].get("authorizer", {})
    user_id = authorizer.get("userId", "")
    org_id = authorizer.get("orgId", "")

    logger.info("WebSocket connect: connection_id=%s user_id=%s", connection_id, user_id)

    # Store in DynamoDB
    table.put_item(Item={
        "connectionId": connection_id,
        "userId": user_id,
        "orgId": org_id or "",
        "connectedAt": str(event["requestContext"].get("connectedAt", "")),
    })

    # Notify backend (best-effort)
    try:
        req = urllib.request.Request(
            f"http://{os.environ['ALB_DNS_NAME']}/api/v1/ws/connect",
            method="POST",
            headers={
                "x-connection-id": connection_id,
                "x-user-id": user_id,
                "x-org-id": org_id or "",
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning("Failed to notify backend of connect: %s", e)

    return {"statusCode": 200}
```

- [ ] **Step 2: Create ws-disconnect Lambda**

```python
"""WebSocket $disconnect handler — removes connection from DynamoDB, notifies backend."""
import os
import urllib.request
import boto3
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]

    logger.info("WebSocket disconnect: connection_id=%s", connection_id)

    # Remove from DynamoDB
    try:
        table.delete_item(Key={"connectionId": connection_id})
    except Exception as e:
        logger.warning("Failed to remove connection from DynamoDB: %s", e)

    # Notify backend (best-effort)
    try:
        req = urllib.request.Request(
            f"http://{os.environ['ALB_DNS_NAME']}/api/v1/ws/disconnect",
            method="POST",
            headers={
                "x-connection-id": connection_id,
                "Content-Type": "application/json",
            },
            data=b"{}",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception as e:
        logger.warning("Failed to notify backend of disconnect: %s", e)

    return {"statusCode": 200}
```

- [ ] **Step 3: Create ws-message Lambda**

```python
"""WebSocket $default handler — forwards message body to backend via ALB."""
import os
import urllib.request
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    body = event.get("body", "") or ""

    try:
        req = urllib.request.Request(
            f"http://{os.environ['ALB_DNS_NAME']}/api/v1/ws/message",
            method="POST",
            headers={
                "x-connection-id": connection_id,
                "Content-Type": "application/json",
            },
            data=body.encode("utf-8") if body else b"{}",
        )
        resp = urllib.request.urlopen(req, timeout=10)
        return {"statusCode": resp.status}
    except Exception as e:
        logger.error("Failed to forward message: %s", e)
        return {"statusCode": 500}
```

- [ ] **Step 4: Commit**

```bash
git add apps/infra/lambda/ws-connect/ apps/infra/lambda/ws-disconnect/ apps/infra/lambda/ws-message/
git commit -m "feat: add Lambda WebSocket handlers (connect, disconnect, message)"
```

---

### Task 3: Rewrite ApiStack with L2 WebSocket + Lambda

**Files:**
- Rewrite: `apps/infra/lib/stacks/api-stack.ts`

- [ ] **Step 1: Read current api-stack.ts fully**

Understand all resources, exports, and cross-stack references.

- [ ] **Step 2: Rewrite ApiStack**

New props interface (no more NLB/ec2Role dependencies):
```typescript
export interface ApiStackProps extends cdk.StackProps {
  environment: string;
  vpc: ec2.IVpc;
  certificate: acm.ICertificate;
  hostedZone: route53.IHostedZone;
  alb: elbv2.IApplicationLoadBalancer;
  albHttpListenerArn: string;
  albSecurityGroup: ec2.ISecurityGroup;
}
```

HTTP API section: keep the same CfnApi + VPC Link v2 pattern (no L2 exists).

WebSocket API section: replace ALL L1 constructs with:
```typescript
import { WebSocketApi, WebSocketStage } from "aws-cdk-lib/aws-apigatewayv2";
import { WebSocketLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";

const wsApi = new WebSocketApi(this, "WebSocketApi", {
  apiName: `isol8-${env}-websocket`,
  routeSelectionExpression: "$request.body.action",
  connectRouteOptions: {
    integration: new WebSocketLambdaIntegration("ConnectIntegration", connectFn),
    authorizer: wsAuthorizer,  // L2 WebSocketIamAuthorizer or custom
  },
  disconnectRouteOptions: {
    integration: new WebSocketLambdaIntegration("DisconnectIntegration", disconnectFn),
  },
  defaultRouteOptions: {
    integration: new WebSocketLambdaIntegration("DefaultIntegration", messageFn),
  },
});

const wsStage = new WebSocketStage(this, "WsStage", {
  webSocketApi: wsApi,
  stageName: env,
  autoDeploy: true,
});
```

Lambda functions:
- 3x `lambda.Function` (Python 3.12, inline code from `lambda/ws-connect/`, etc.)
- VPC: private subnets (to reach ALB)
- Security group: allow outbound to ALB on port 80
- Environment: `ALB_DNS_NAME`, `CONNECTIONS_TABLE`
- Timeout: 10s

Lambda authorizer: keep existing Clerk JWT authorizer logic, adapt for L2 `WebSocketApi`.

Remove: VPC Link v1, CfnResource for VPC Link, all CfnIntegration for WebSocket, all CfnRoute for WebSocket, CfnIntegrationResponse, CfnRouteResponse.

Keep: DynamoDB connections table, custom domains, Route53 records, management API URL output, IAM policy for ManageConnections (attached to ServiceStack's task role).

Exports: `httpApiUrl`, `webSocketUrl`, `managementApiUrl`, `connectionsTableName`

- [ ] **Step 3: Install CDK L2 WebSocket packages**

```bash
cd apps/infra && npm install @aws-cdk/aws-apigatewayv2-integrations @aws-cdk/aws-apigatewayv2-authorizers
```

Note: Check if these are bundled in `aws-cdk-lib` v2 or need separate packages. In CDK v2, they should be at:
```typescript
import { WebSocketApi } from "aws-cdk-lib/aws-apigatewayv2";
import { WebSocketLambdaIntegration } from "aws-cdk-lib/aws-apigatewayv2-integrations";
import { WebSocketLambdaAuthorizer } from "aws-cdk-lib/aws-apigatewayv2-authorizers";
```

If not available in the installed CDK version, install:
```bash
npm install @aws-cdk/aws-apigatewayv2-alpha @aws-cdk/aws-apigatewayv2-integrations-alpha @aws-cdk/aws-apigatewayv2-authorizers-alpha
```

- [ ] **Step 4: Verify synth**

```bash
AWS_PROFILE=isol8-admin npx cdk synth -q 2>&1 | grep "Successfully"
```

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/api-stack.ts apps/infra/package*.json
git commit -m "feat: rewrite ApiStack with L2 WebSocket + Lambda integrations"
```

---

### Task 4: Create ServiceStack (Fargate replaces EC2)

**Files:**
- Create: `apps/infra/lib/stacks/service-stack.ts`

- [ ] **Step 1: Read compute-stack.ts IAM policies thoroughly**

Read `compute-stack.ts` lines 244-470 to capture ALL IAM permissions the EC2 role has. The Fargate task role needs the same permissions.

- [ ] **Step 2: Write ServiceStack**

Props interface:
```typescript
export interface ServiceStackProps extends cdk.StackProps {
  environment: string;
  vpc: ec2.IVpc;
  targetGroup: elbv2.IApplicationTargetGroup;
  database: {
    dbInstance: rds.IDatabaseInstance;
    dbSecurityGroup: ec2.ISecurityGroup;
    dbSecret: secretsmanager.ISecret;
  };
  secrets: AuthSecrets;
  kmsKey: kms.IKey;
  container: {
    cluster: ecs.ICluster;
    cloudMapNamespace: servicediscovery.IPrivateDnsNamespace;
    cloudMapService: servicediscovery.IService;
    efsFileSystem: efs.IFileSystem;
    efsSecurityGroup: ec2.ISecurityGroup;
    containerSecurityGroup: ec2.ISecurityGroup;
    taskExecutionRole: iam.IRole;
    taskRole: iam.IRole;
  };
  managementApiUrl: string;
  connectionsTableName: string;
}
```

Resources:
- **ECR repository**: `isol8-{env}-backend` (same as current)
- **DockerImageAsset**: from `apps/backend/`, platform linux/amd64
- **Security group**: allow ALB on 8000, allow EFS on 2049, allow outbound all
- **Task definition** (Fargate):
  - CPU: 1024 dev / 2048 prod
  - Memory: 2048 dev / 4096 prod
  - Task role: same permissions as current EC2 role (all 17 policy statements)
  - Execution role: ECR pull, CloudWatch, Secrets Manager
  - Container with:
    - Image: DockerImageAsset
    - Port: 8000
    - Environment vars: all current `.env` values from compute-stack `Fn.sub` map, now as plain CDK strings
    - Secrets: `DATABASE_URL`, `CLERK_ISSUER`, `CLERK_SECRET_KEY`, etc. from Secrets Manager via `ecs.Secret.fromSecretsManager()`
    - Health check: `CMD-SHELL, curl -f http://localhost:8000/health || exit 1`
    - Logging: CloudWatch (`/ecs/isol8-{env}`)
  - EFS volume: mounted at `/mnt/efs`, IAM auth, transit encryption
- **Fargate service**:
  - Cluster: from ContainerStack
  - Desired count: 1 dev / 2 prod
  - Circuit breaker with rollback
  - Private subnets
  - Register with ALB target group (from NetworkStack)
  - Security group ingress: ALB on 8000

Cross-stack security group rules (CfnSecurityGroupIngress):
- Allow service SG → EFS SG on 2049
- Allow service SG → container SG on all TCP
- Allow service SG → DB SG on 5432

Exports: `service`, `taskRole`

- [ ] **Step 3: Verify synth**

- [ ] **Step 4: Commit**

```bash
git add apps/infra/lib/stacks/service-stack.ts
git commit -m "feat: add ServiceStack (Fargate, replaces EC2 ASG)"
```

---

### Task 5: Update Dockerfile for init_db

**Files:**
- Modify: `apps/backend/Dockerfile`

- [ ] **Step 1: Update CMD to run init_db.py before uvicorn**

Change:
```dockerfile
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "300"]
```

To:
```dockerfile
CMD ["sh", "-c", "uv run python init_db.py 2>&1 || echo 'WARNING: init_db failed'; exec uv run uvicorn main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 300"]
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/Dockerfile
git commit -m "feat: run init_db.py on container start (idempotent)"
```

---

### Task 6: Rewire isol8-stage.ts

**Files:**
- Modify: `apps/infra/lib/isol8-stage.ts`
- Delete: `apps/infra/lib/stacks/compute-stack.ts`
- Delete: `apps/infra/lib/user-data.sh`

- [ ] **Step 1: Rewrite isol8-stage.ts**

New dependency order:
```typescript
const auth = new AuthStack(...);
const dns = new DnsStack(...);
const network = new NetworkStack(..., { certificate: dns.certificate });
const database = new DatabaseStack(..., { vpc: network.vpc, kmsKey: auth.kmsKey });
const container = new ContainerStack(..., { vpc: network.vpc, kmsKey: auth.kmsKey });

// ApiStack deploys BEFORE ServiceStack (no more circular dep)
const api = new ApiStack(..., {
  vpc: network.vpc,
  certificate: dns.certificate,
  hostedZone: dns.hostedZone,
  alb: network.alb,
  albHttpListenerArn: network.albHttpListenerArn,
  albSecurityGroup: network.albSecurityGroup,
});

const service = new ServiceStack(..., {
  vpc: network.vpc,
  targetGroup: network.targetGroup,
  database: { ... },
  secrets: auth.secrets,
  kmsKey: auth.kmsKey,
  container: { ... },
  managementApiUrl: api.managementApiUrl,  // Direct prop! No more CloudFormation query!
  connectionsTableName: api.connectionsTableName,
});
```

- [ ] **Step 2: Delete compute-stack.ts and user-data.sh**

```bash
rm apps/infra/lib/stacks/compute-stack.ts
rm apps/infra/lib/user-data.sh
```

- [ ] **Step 3: Verify synth**

```bash
AWS_PROFILE=isol8-admin npx cdk synth -q 2>&1 | grep "Successfully"
```

- [ ] **Step 4: Commit**

```bash
git add -A apps/infra/
git commit -m "feat: rewire stage — ApiStack before ServiceStack, delete EC2/NLB code"
```

---

## Phase 2: Deploy and Verify

### Task 7: Delete old stacks and deploy

- [ ] **Step 1: Delete old compute and API CloudFormation stacks**

Both dev and prod `isol8-{env}-compute` and `isol8-{env}-api` stacks must be deleted before deploying the new ones (resource name conflicts).

```bash
# Dev
AWS_PROFILE=isol8-admin aws cloudformation delete-stack --stack-name isol8-dev-api
AWS_PROFILE=isol8-admin aws cloudformation delete-stack --stack-name isol8-dev-compute
# Wait for deletion
AWS_PROFILE=isol8-admin aws cloudformation wait stack-delete-complete --stack-name isol8-dev-api
AWS_PROFILE=isol8-admin aws cloudformation wait stack-delete-complete --stack-name isol8-dev-compute

# Prod (same)
AWS_PROFILE=isol8-admin aws cloudformation delete-stack --stack-name isol8-prod-api
AWS_PROFILE=isol8-admin aws cloudformation delete-stack --stack-name isol8-prod-compute
AWS_PROFILE=isol8-admin aws cloudformation wait stack-delete-complete --stack-name isol8-prod-api
AWS_PROFILE=isol8-admin aws cloudformation wait stack-delete-complete --stack-name isol8-prod-compute
```

Note: VPC Links may stick in PENDING — delete them manually via `aws apigateway delete-vpc-link` if needed. ALB deletion protection must be disabled for prod.

- [ ] **Step 2: Push and trigger pipeline**

```bash
git push
```

Pipeline will: synth → deploy dev (network update + new API + new service stacks) → approval → deploy prod.

- [ ] **Step 3: Verify dev health**

```bash
curl -s https://api-dev.isol8.co/health
# Expected: {"status":"healthy","database":"connected"}
```

- [ ] **Step 4: Verify WebSocket**

Open `https://dev.isol8.co` in browser, check console for WebSocket connection success.

- [ ] **Step 5: Verify container provisioning**

Navigate to `/chat`, verify container starts successfully.

- [ ] **Step 6: Approve prod deployment**

Comment "approve" on the GitHub Issue created by the manual-approval action.

- [ ] **Step 7: Verify prod**

```bash
curl -s https://api.isol8.co/health
```

---

## Summary of Changes

| Before | After |
|--------|-------|
| EC2 ASG (t3.large) | Fargate service (1 vCPU / 2 GB) |
| user-data.sh (180 lines) | Deleted — env vars in task definition |
| NLB + VPC Link v1 | Deleted — Lambda WebSocket handlers |
| L1 CfnApi, CfnIntegration (WebSocket) | L2 WebSocketApi, WebSocketLambdaIntegration |
| CloudFormation query for WS URL | Direct prop from ApiStack → ServiceStack |
| ALB in ComputeStack | ALB in NetworkStack |
| Circular dep (compute ↔ API) | Linear dep (network → API → service) |
