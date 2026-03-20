# ECS Fargate + Lambda WebSocket Migration — Design Spec

**Date:** 2026-03-20
**Status:** Approved

## Overview

Migrate the isol8 backend from EC2 ASG to ECS Fargate, and replace the NLB + VPC Link v1 WebSocket architecture with Lambda-based WebSocket handlers. This eliminates the NLB, user-data.sh, instance profiles, and the circular dependency between ComputeStack and ApiStack.

## Motivation

- **Eliminate boot script complexity** — user-data.sh has been the source of multiple deployment issues (EFS mount, secrets fetch, WS management URL query, database init)
- **Eliminate NLB** — only existed because WebSocket API Gateway required VPC Link v1 which only targets NLB
- **Fix circular dependency** — ComputeStack and ApiStack have a dependency cycle around NLB/ALB/management URL. Moving ALB to NetworkStack and using Lambda WebSocket breaks this cycle
- **Simplify deployments** — Fargate task definitions are declarative; env vars and secrets are managed by CDK, not fetched at boot time
- **Use standard AWS patterns** — Lambda WebSocket with DynamoDB connection tracking is the AWS-recommended pattern
- **Use L2 CDK constructs** — `WebSocketApi`, `WebSocketLambdaIntegration`, `FargateService` replace L1 `CfnResource` hacks

## Architecture

### Before

```
HTTP API GW → VPC Link v2 → ALB → EC2 ASG (FastAPI Docker)
WS API GW   → VPC Link v1 → NLB → EC2 ASG
                                      ├── EFS mount (user-data.sh)
                                      ├── boto3 → ECS Fargate (per-user OpenClaw)
                                      ├── boto3 → @connections Management API
                                      └── RDS PostgreSQL
```

### After

```
HTTP API GW → VPC Link v2 → ALB → Fargate Service (FastAPI Docker)
WS API GW   → Lambda ($connect, $disconnect, $default)
                  ├── $connect/$disconnect → DynamoDB (connection tracking)
                  └── $default → ALB → Fargate Service (message processing)
                                          ├── EFS mount (task definition)
                                          ├── boto3 → ECS Fargate (per-user OpenClaw)
                                          ├── boto3 → @connections Management API
                                          └── RDS PostgreSQL
```

### Removed

- NLB (Network Load Balancer)
- VPC Link v1 (`AWS::ApiGateway::VpcLink`)
- NLB target group, NLB listener
- EC2 Auto Scaling Group, launch template
- `user-data.sh` bootstrap script
- EC2 instance profile (IAM role for EC2)
- CloudFormation DescribeStacks permission (no longer needed)
- `Fn::Sub` variable substitution for user-data

### Added

- Fargate service + task definition (declarative env vars, secrets, EFS mounts)
- 3 Lambda functions (ws-connect, ws-disconnect, ws-message)
- L2 WebSocket constructs (`WebSocketApi`, `WebSocketStage`, `WebSocketLambdaIntegration`)

## Stack Restructure

### Before

```
NetworkStack (VPC)
ComputeStack (EC2 ASG, ALB, NLB, ECR, IAM)  ← ALB and NLB here
ApiStack (HTTP API GW, WS API GW, VPC Links) ← depends on ALB + NLB from Compute
```

Circular dependency: Compute exports ALB/NLB → ApiStack needs them. ApiStack exports managementApiUrl → Compute needs it (workaround: CloudFormation query at boot).

### After

```
NetworkStack (VPC, ALB)                       ← ALB moves here
ServiceStack (Fargate service, ECR, IAM)      ← depends on ALB from Network
ApiStack (HTTP API GW, WS API GW, Lambdas)    ← depends on ALB from Network
```

No circular dependency: both ServiceStack and ApiStack depend on NetworkStack for the ALB. ApiStack exports managementApiUrl → ServiceStack receives it as a direct prop.

### Full Dependency Graph

```
AuthStack         (no deps)
DnsStack          (no deps)
NetworkStack      (no deps) — now includes ALB
DatabaseStack     (depends on: Network, Auth)
ContainerStack    (depends on: Network, Auth)
ApiStack          (depends on: Network, Auth, DNS) — no dependency on ServiceStack
ServiceStack      (depends on: Network, Database, Auth, DNS, Container, ApiStack)
                  — receives managementApiUrl from ApiStack as direct prop
```

## Stack Details

### NetworkStack (Updated)

Adds ALB to the existing VPC stack:

- **ALB (internal)**
  - HTTPS listener (port 443) with ACM cert
  - HTTP listener (port 80) forwarding to target group (for API Gateway VPC Link)
  - Target group: port 8000, HTTP, IP target type (Fargate uses `awsvpc` networking)
  - Health check: `/health`, interval 30s
  - Idle timeout: 300s (for SSE streaming)
  - Sticky sessions: 1 hour

**Exports:** `vpc`, `alb`, `albListener`, `albHttpListener`, `albSecurityGroup`, `targetGroup`

### ServiceStack (Replaces ComputeStack)

Replaces EC2 ASG with Fargate service:

- **ECR repository** — `isol8-{env}-backend` (unchanged)
- **DockerImageAsset** — builds from `apps/backend/` (unchanged)
- **Fargate task definition:**
  - CPU: 1024 (1 vCPU) dev, 2048 (2 vCPU) prod
  - Memory: 2048 MB dev, 4096 MB prod
  - Task role: same permissions as current EC2 role (ECS management, Secrets Manager, Bedrock, Cloud Map, KMS, EFS, S3)
  - Task execution role: ECR pull, CloudWatch logs, Secrets Manager read
  - Container env vars: all current `.env` values, now declared in CDK
  - Container secrets: injected by ECS from Secrets Manager (no boot-time fetch)
  - EFS volume: mounted at `/mnt/efs`, IAM auth, transit encryption
  - Port mapping: 8000
  - Health check: `curl -f http://localhost:8000/health`
  - Logging: CloudWatch Logs (`/ecs/isol8-{env}`)
- **Fargate service:**
  - Cluster: existing ECS cluster from ContainerStack
  - Desired count: 1 (dev), 2 (prod)
  - Circuit breaker with rollback
  - Private subnets
  - Security group: allow ALB on 8000, allow EFS on 2049, allow outbound all
  - Registered with ALB target group
- **Database initialization:**
  - `init_db.py` runs as part of Docker `CMD` or entrypoint wrapper (idempotent)

**Exports:** `service`, `taskRole`

### ApiStack (Simplified)

Replaces L1 WebSocket constructs with L2 + Lambda:

**HTTP API (unchanged pattern):**
- `CfnApi` (HTTP protocol) — still L1 (no full L2 for HTTP API v2 + VPC Link)
- VPC Link v2 → ALB HTTP listener
- Custom domain: `api-{env}.isol8.co`

**WebSocket API (new — L2 constructs):**
- `WebSocketApi` (L2) with route selection expression `$request.body.action`
- `WebSocketStage` (L2) with auto-deploy, throttling
- Lambda authorizer (existing Clerk JWT validator)
- Three Lambda integrations:
  - `$connect` → `WebSocketLambdaIntegration` → ws-connect Lambda
  - `$disconnect` → `WebSocketLambdaIntegration` → ws-disconnect Lambda
  - `$default` → `WebSocketLambdaIntegration` → ws-message Lambda
- Custom domain: `ws-{env}.isol8.co`

**Lambda functions:**
- Runtime: Python 3.12
- VPC: private subnets (to reach ALB)
- Security group: allow outbound to ALB on port 80
- Environment: `ALB_DNS_NAME`, `CONNECTIONS_TABLE_NAME`

**DynamoDB connections table:** unchanged

**Management API URL:** exported as stack output, passed to ServiceStack as prop

**No NLB, no VPC Link v1, no CfnResource hacks.**

**Exports:** `httpApiUrl`, `webSocketUrl`, `managementApiUrl`, `connectionsTableName`

### Props Flow (No Circular Dependencies)

```
NetworkStack.alb              → ServiceStack (registers Fargate with ALB target group)
NetworkStack.alb              → ApiStack (HTTP API VPC Link, Lambda env var for ALB DNS)
NetworkStack.albHttpListener  → ApiStack (HTTP API integration URI)
ApiStack.managementApiUrl     → ServiceStack (Fargate task env var)
ApiStack.connectionsTableName → ServiceStack (Fargate task env var)
```

## Lambda WebSocket Functions

### ws-connect (Python)

```python
import boto3
import urllib.request
import json
import os

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(os.environ["CONNECTIONS_TABLE"])

def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    authorizer = event["requestContext"].get("authorizer", {})
    user_id = authorizer.get("userId", "")
    org_id = authorizer.get("orgId", "")

    # Store connection in DynamoDB
    table.put_item(Item={
        "connectionId": connection_id,
        "userId": user_id,
        "orgId": org_id,
        "connectedAt": event["requestContext"].get("connectedAt", ""),
    })

    # Forward to backend
    req = urllib.request.Request(
        f"http://{os.environ['ALB_DNS_NAME']}/api/v1/ws/connect",
        method="POST",
        headers={
            "x-connection-id": connection_id,
            "x-user-id": user_id,
            "x-org-id": org_id,
            "Content-Type": "application/json",
        },
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # Backend connect is best-effort

    return {"statusCode": 200}
```

### ws-disconnect (Python)

```python
def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]

    table.delete_item(Key={"connectionId": connection_id})

    req = urllib.request.Request(
        f"http://{os.environ['ALB_DNS_NAME']}/api/v1/ws/disconnect",
        method="POST",
        headers={"x-connection-id": connection_id, "Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

    return {"statusCode": 200}
```

### ws-message (Python)

```python
def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    body = event.get("body", "")

    req = urllib.request.Request(
        f"http://{os.environ['ALB_DNS_NAME']}/api/v1/ws/message",
        method="POST",
        data=body.encode("utf-8") if body else b"",
        headers={"x-connection-id": connection_id, "Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return {"statusCode": resp.status}
    except Exception:
        return {"statusCode": 500}
```

## What Does NOT Change

- **Backend application code** — FastAPI, all routes, all services, all models
- **Dockerfile** — same image, same entrypoint
- **RDS PostgreSQL** — same database, same connection
- **DynamoDB connections table** — same schema, same usage
- **ECS cluster** — same cluster for both backend and per-user containers
- **Cloud Map** — same service discovery for per-user containers
- **EFS filesystem** — same filesystem, mounted via task definition instead of user-data
- **Clerk auth** — same JWT validation
- **Stripe billing** — same webhook flow
- **Management API pattern** — backend still pushes via `@connections`
- **EC2 → Fargate container RPC** — backend still opens direct WebSocket to Fargate tasks
- **HTTP API Gateway** — same HTTP API, same VPC Link v2, same ALB target

## Environment Configuration

| Config | Dev | Prod |
|--------|-----|------|
| Fargate CPU | 1024 (1 vCPU) | 2048 (2 vCPU) |
| Fargate Memory | 2048 MB | 4096 MB |
| Desired count | 1 | 2 |
| Min/max (auto-scaling) | 1/2 | 2/4 |

## Database Initialization

Currently in `user-data.sh`, runs `docker exec isol8 uv run python init_db.py`.

With Fargate, add a wrapper entrypoint script or modify `CMD` in Dockerfile:

```dockerfile
CMD ["sh", "-c", "uv run python init_db.py && uv run uvicorn main:app --host 0.0.0.0 --port 8000"]
```

This runs `init_db.py` (idempotent) before starting the server on every container start.

## Migration Strategy

1. Create new stacks (ServiceStack, updated ApiStack) alongside existing
2. Deploy to dev — verify health, WebSocket, billing, container provisioning
3. Delete old stacks (ComputeStack with EC2/NLB)
4. Deploy to prod after dev verification

## Risks

- **EFS mount on Fargate** — Fargate EFS mounts are well-supported but require IAM auth and transit encryption. Already using both on EC2.
- **Lambda cold starts** — WebSocket $connect may add ~200ms on cold start. Acceptable for connection establishment.
- **ALB target type change** — EC2 uses `INSTANCE` target type, Fargate uses `IP`. ALB target group must be recreated (new stack handles this).
