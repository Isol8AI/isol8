# RDS PostgreSQL → DynamoDB Migration

**Date:** 2026-03-23
**Status:** Draft
**Scope:** Backend database layer only (no frontend changes)

## Motivation

The current RDS PostgreSQL database adds operational friction for quick data operations (deletes, edits) requiring terminal SQL. The actual data model is simple key-value access patterns that don't benefit from relational features. DynamoDB provides a console/CLI-friendly experience, eliminates RDS management overhead, and fits the existing access patterns naturally.

## Current State

### Tables to Migrate (4 active tables)

| Table | Rows Pattern | Primary Access | Used By |
|-------|-------------|----------------|---------|
| `users` | 1 row per Clerk user | Lookup by `user_id` (Clerk ID) | `users.py`, `billing_service.py` |
| `containers` | 1 row per user | Lookup by `user_id`, auth by `gateway_token`, filter by `status` | `ecs_manager.py`, `connection_pool.py`, `websocket_chat.py`, 6+ routers |
| `billing_account` | 1 row per user | Lookup by `clerk_user_id`, webhook lookup by `stripe_customer_id` | `billing_service.py`, `usage_service.py`, `usage_poller.py` |
| `user_api_keys` | ~0-4 rows per user | CRUD by `(user_id, tool_id)`, list by `user_id` | `key_service.py`, `settings_keys.py` |

### Tables to Drop (5 dead/aspirational tables)

| Table | Reason to Drop |
|-------|---------------|
| `audit_logs` | Dead code — model exists but nothing writes to it |
| `usage_event` | Aspirational — not confirmed working end-to-end |
| `usage_daily` | Aspirational — daily rollup for `usage_event` |
| `model_pricing` | Aspirational — seed data for usage cost calculation |
| `tool_pricing` | Aspirational — seed data for tool cost calculation |

**Note:** Stripe meter exists but usage pipeline is not confirmed functional. Usage/billing tables can be rebuilt on DynamoDB when needed. The `billing_account` table (Stripe customer mapping, plan tier) is actively used and will be migrated.

## DynamoDB Table Design

### Table 1: `isol8-{env}-users`

Simple single-item table. Exists primarily for FK-like consistency with billing.

| Key | Attribute | Type | Notes |
|-----|-----------|------|-------|
| **PK** | `user_id` | S | Clerk user ID (e.g., `user_2abc...`) |

No GSIs needed. Single access pattern: get/put by `user_id`.

---

### Table 2: `isol8-{env}-containers`

Most complex table — 4 access patterns.

| Key | Attribute | Type | Notes |
|-----|-----------|------|-------|
| **PK** | `user_id` | S | Clerk user ID (1:1 with user) |
| | `id` | S | UUID, stored as attribute |
| | `service_name` | S | ECS service name |
| | `task_arn` | S | Current ECS task ARN |
| | `access_point_id` | S | EFS access point |
| | `task_definition_arn` | S | Task definition revision |
| | `gateway_token` | S | OpenClaw gateway auth token |
| | `device_private_key_pem` | S | Device identity key |
| | `status` | S | provisioning/running/stopped/error |
| | `substatus` | S | Granular provisioning step |
| | `created_at` | S | ISO 8601 timestamp |
| | `updated_at` | S | ISO 8601 timestamp |

**GSI: `gateway-token-index`**
| Key | Attribute | Purpose |
|-----|-----------|---------|
| **PK** | `gateway_token` | RPC auth — look up container by token |

**GSI: `status-index`**
| Key | Attribute | Purpose |
|-----|-----------|---------|
| **PK** | `status` | Usage poller — find all `running` containers |

Access patterns:
1. Get container by `user_id` → table PK
2. Get container by `gateway_token` → GSI
3. List containers by `status` → GSI
4. Update status/substatus/task_arn → update expression on PK

---

### Table 3: `isol8-{env}-billing-accounts`

| Key | Attribute | Type | Notes |
|-----|-----------|------|-------|
| **PK** | `clerk_user_id` | S | Clerk user ID |
| | `id` | S | UUID |
| | `clerk_org_id` | S | Optional — org billing |
| | `stripe_customer_id` | S | Stripe customer ID |
| | `stripe_subscription_id` | S | Current subscription |
| | `plan_tier` | S | free/starter/pro |
| | `markup_multiplier` | N | e.g., 1.4 |
| | `created_at` | S | ISO 8601 |
| | `updated_at` | S | ISO 8601 |

**GSI: `stripe-customer-index`**
| Key | Attribute | Purpose |
|-----|-----------|---------|
| **PK** | `stripe_customer_id` | Stripe webhook → find account |

Access patterns:
1. Get billing account by `clerk_user_id` → table PK
2. Get billing account by `stripe_customer_id` → GSI (Stripe webhooks)
3. Update subscription/tier → update expression on PK

**Note on org billing:** The current schema has a check constraint requiring exactly one of `clerk_user_id` or `clerk_org_id`. If org billing is needed, we'd use a single-table design with `PK = "USER#xxx"` or `PK = "ORG#xxx"`. For now, `clerk_user_id` as PK is sufficient since org billing isn't active.

---

### Table 4: `isol8-{env}-api-keys`

| Key | Attribute | Type | Notes |
|-----|-----------|------|-------|
| **PK** | `user_id` | S | Clerk user ID |
| **SK** | `tool_id` | S | Tool identifier (e.g., `perplexity`, `elevenlabs`) |
| | `id` | S | UUID |
| | `encrypted_key` | S | Fernet-encrypted API key |
| | `created_at` | S | ISO 8601 |
| | `updated_at` | S | ISO 8601 |

No GSIs needed. Composite key gives us:
1. Get specific key: `PK=user_id, SK=tool_id`
2. List all keys for user: `PK=user_id` (query, no SK condition)
3. Delete key: `PK=user_id, SK=tool_id`

---

## Backend Changes

### Files to Delete

| File | Reason |
|------|--------|
| `core/database.py` | SQLAlchemy engine/session — replaced by DynamoDB client |
| `init_db.py` | Schema creation — DynamoDB tables created via CDK |
| `seed_pricing.py` | Seeds `model_pricing` — table dropped |
| `models/base.py` | SQLAlchemy declarative base |
| `models/user.py` | SQLAlchemy model → DynamoDB item |
| `models/container.py` | SQLAlchemy model → DynamoDB item |
| `models/billing.py` | All 5 billing models — 4 dropped, 1 rewritten |
| `models/audit_log.py` | Dead code |
| `models/user_api_key.py` | SQLAlchemy model → DynamoDB item |
| `models/__init__.py` | Re-export — rewritten |
| `migrations/001_add_containers_table.sql` | SQL migration — no longer needed |
| `core/services/usage_service.py` | Aspirational usage tracking |
| `core/services/usage_poller.py` | Aspirational usage polling |

### Files to Create

| File | Purpose |
|------|---------|
| `core/dynamodb.py` | DynamoDB client singleton, table name helpers, common operations |
| `core/repositories/user_repo.py` | User CRUD (get, put, delete) |
| `core/repositories/container_repo.py` | Container CRUD + GSI queries |
| `core/repositories/billing_repo.py` | BillingAccount CRUD + Stripe GSI |
| `core/repositories/api_key_repo.py` | UserApiKey CRUD + list by user |

### Files to Modify

These files currently import from `core/database.py` (get_db) or use SQLAlchemy sessions:

| File | Change |
|------|--------|
| `main.py` | Remove `init_db` startup, remove UsagePoller startup, init DynamoDB client. **Rewrite `/health` endpoint** — currently runs `SELECT 1` via SQLAlchemy for ALB health check. Replace with DynamoDB `describe_table` or similar connectivity check. Remove `from sqlalchemy import text` import. |
| `core/config.py` | Remove `DATABASE_URL`, add DynamoDB table name prefix config |
| `core/containers/ecs_manager.py` | Replace SQLAlchemy queries with `container_repo` calls |
| `core/containers/__init__.py` | Remove usage recording callback (aspirational) |
| `core/containers/config.py` | No DB changes expected, but verify |
| `core/gateway/connection_pool.py` | Replace container DB reads **and writes** with `container_repo`. This module imports `select`, `update` from SQLAlchemy and `get_session_factory` — it performs status transitions, not just lookups. |
| `core/services/billing_service.py` | Replace SQLAlchemy with `billing_repo` |
| `core/services/key_service.py` | Replace SQLAlchemy with `api_key_repo` |
| `routers/users.py` | Replace `get_db` dependency with repo calls |
| `routers/billing.py` | Replace DB queries with repo, remove usage endpoints (or stub them). **Stripe webhook handler** (lines ~189-239) queries `BillingAccount` by `stripe_customer_id` in 3 places using raw SQLAlchemy — replace with `billing_repo.get_by_stripe_customer_id()` via the `stripe-customer-index` GSI. Also passes `db` to `provision_user_container()` — that call chain needs repo injection. |
| `routers/container.py` | Replace DB queries with repo calls. **Note:** also queries `BillingAccount` directly via `_user_has_subscription()` — needs both `container_repo` and `billing_repo`. |
| `routers/container_rpc.py` | Replace gateway_token lookup with repo |
| `routers/websocket_chat.py` | Replace container lookups with repo |
| `routers/control_ui_proxy.py` | Replace container lookups with repo |
| `routers/proxy.py` | Replace container/key lookups with repo. **Also imports `BillingAccount`** — needs `billing_repo` access. |
| `routers/channels.py` | Replace container lookups with repo |
| `routers/settings_keys.py` | Replace DB session with repo calls |
| `routers/debug.py` | Replace DB queries with repo calls |

### Dependency Changes

**Remove from `pyproject.toml`:**
- `sqlalchemy[asyncio]`
- `asyncpg`
- `greenlet` (SQLAlchemy async dependency)

**Already present (no new deps):**
- `boto3` — already used for ECS, EFS, S3, Secrets Manager, CloudMap

### Repository Pattern

Each repo is a thin wrapper around `boto3.resource('dynamodb')`:

```python
# core/repositories/container_repo.py (sketch)
from core.dynamodb import get_table

async def get_by_user_id(user_id: str) -> dict | None:
    table = get_table("containers")
    response = table.get_item(Key={"user_id": user_id})
    return response.get("Item")

async def get_by_gateway_token(token: str) -> dict | None:
    table = get_table("containers")
    response = table.query(
        IndexName="gateway-token-index",
        KeyConditionExpression=Key("gateway_token").eq(token),
    )
    items = response.get("Items", [])
    return items[0] if items else None

async def update_status(user_id: str, status: str, **kwargs) -> None:
    table = get_table("containers")
    table.update_item(
        Key={"user_id": user_id},
        UpdateExpression="SET #s = :s, updated_at = :now",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": status, ":now": utc_now_iso()},
    )
```

**Note on async:** `boto3` is synchronous. Options:
1. **Use `aioboto3`** (async wrapper) — adds a dependency but keeps the async pattern
2. **Use `boto3` in a thread executor** via `asyncio.to_thread()` — no new deps, already pattern-compatible
3. **Use synchronous `boto3` directly** — DynamoDB calls are fast (<10ms), blocking is acceptable for single-digit ms

Recommendation: **Option 2** (`asyncio.to_thread`) for consistency with existing async FastAPI handlers, no new dependencies.

---

## CDK Infrastructure Changes

### Replace: `database-stack.ts` → `database-stack.ts` (rewrite)

Current stack provisions RDS PostgreSQL. Replace with DynamoDB tables:

```typescript
// Sketch — 4 tables + 3 GSIs
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";

export class DatabaseStack extends cdk.Stack {
  public readonly usersTable: dynamodb.Table;
  public readonly containersTable: dynamodb.Table;
  public readonly billingTable: dynamodb.Table;
  public readonly apiKeysTable: dynamodb.Table;

  constructor(scope, id, props) {
    // Users table
    this.usersTable = new dynamodb.Table(this, "UsersTable", {
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });

    // Containers table + 2 GSIs
    this.containersTable = new dynamodb.Table(this, "ContainersTable", {
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      // ...
    });
    this.containersTable.addGlobalSecondaryIndex({
      indexName: "gateway-token-index",
      partitionKey: { name: "gateway_token", type: dynamodb.AttributeType.STRING },
    });
    this.containersTable.addGlobalSecondaryIndex({
      indexName: "status-index",
      partitionKey: { name: "status", type: dynamodb.AttributeType.STRING },
    });

    // Billing table + 1 GSI
    this.billingTable = new dynamodb.Table(this, "BillingTable", {
      partitionKey: { name: "clerk_user_id", type: dynamodb.AttributeType.STRING },
      // ...
    });
    this.billingTable.addGlobalSecondaryIndex({
      indexName: "stripe-customer-index",
      partitionKey: { name: "stripe_customer_id", type: dynamodb.AttributeType.STRING },
    });

    // API Keys table (composite key)
    this.apiKeysTable = new dynamodb.Table(this, "ApiKeysTable", {
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "tool_id", type: dynamodb.AttributeType.STRING },
      // ...
    });
  }
}
```

### Modify: `isol8-stage.ts`

- Update `DatabaseStack` props (remove `vpc` — DynamoDB is serverless, no VPC needed)
- Remove `database.dbSecurityGroup` being passed to `ServiceStack`
- Pass table names/ARNs to `ServiceStack` for IAM permissions

### Modify: `service-stack.ts`

- **Remove** `DbFromServiceIngress` CfnSecurityGroupIngress rule (lines 134-141) — this was the only consumer of `dbSecurityGroup`, allowing Fargate → RDS on port 5432
- Grant EC2/Fargate instance role `dynamodb:GetItem`, `dynamodb:PutItem`, `dynamodb:UpdateItem`, `dynamodb:DeleteItem`, `dynamodb:Query` on the 4 tables + GSIs
- Remove `DATABASE_URL` from Secrets Manager / env vars
- Add `DYNAMODB_TABLE_PREFIX` env var (e.g., `isol8-dev-`)

**Security group impact analysis:** The `dbSecurityGroup` is used exclusively for RDS port 5432 ingress. It has zero relationship to WebSocket Lambdas (which use `wsLambdaSg`), the VPC Link V1 chain (NLB → ALB), or the existing DynamoDB `ws-connections` table (accessed via VPC Gateway Endpoint). Removing it is safe.

### Modify: `local-stage.ts`

- Same DynamoDB table definitions for LocalStack deployment
- Remove `database.dbSecurityGroup` prop passed to ServiceStack

### Remove from Stage Files

Both `isol8-stage.ts` and `local-stage.ts` pass `databaseUrl` as a secret name to `ServiceStack`. Remove this prop from both stage files and from the `SecretNames` interface in `service-stack.ts`.

### Delete from Secrets Manager

- `isol8/{env}/rds-credentials` — no longer needed
- `databaseUrl` secret reference — no longer needed

---

## LocalStack Changes

### `scripts/local-dev.sh`

- Remove: RDS wait/health-check logic
- Remove: `DATABASE_URL` generation from RDS endpoint
- Add: DynamoDB table creation happens automatically via `cdklocal deploy`
- LocalStack already supports DynamoDB (already in "Services emulated" list)
- Simpler startup — no waiting for RDS to be ready

### `docker-compose.yml` (if applicable)

- No changes — LocalStack already includes DynamoDB

---

## Test Changes

### Files to Delete

| File | Reason |
|------|--------|
| `tests/unit/models/test_audit_log.py` | Dead code |
| `tests/unit/services/test_usage_service.py` | Aspirational |
| `tests/unit/services/test_usage_poller.py` | Aspirational |
| `tests/unit/routers/test_usage_tracking.py` | Aspirational |
| `tests/unit/models/test_billing.py` | Tests dropped billing models (UsageEvent, UsageDaily, ModelPricing) |
| `tests/unit/models/test_tool_pricing.py` | Tests dropped ToolPricing model |

### Files to Rewrite/Update

| File | Change |
|------|--------|
| `tests/conftest.py` | **Major rewrite** — remove `override_get_db`, `override_get_session_factory`, all SQLAlchemy session fixtures. Replace with DynamoDB mocks (moto or repo-level mocks). |
| `tests/contract/conftest.py` | Same pattern — remove `get_db` overrides |
| `tests/contract/test_api_contracts.py` | Replace `get_db` overrides with repo mocks |
| `tests/contract/test_websocket_contracts.py` | Replace `get_db` overrides with repo mocks |
| `tests/unit/test_health.py` | Replace `get_db` mock with DynamoDB connectivity mock |
| `tests/unit/test_openapi_config.py` | Replace `get_db` mock |
| `tests/unit/models/test_container.py` | Rewrite for DynamoDB item structure |
| `tests/unit/models/test_user.py` | Rewrite for DynamoDB item structure |
| `tests/unit/models/test_user_api_keys.py` | Rewrite for DynamoDB item structure |
| `tests/unit/routers/test_container_status.py` | Replace Container model mocks with repo mocks |
| `tests/unit/routers/test_proxy.py` | Replace BillingAccount + Container mocks |
| `tests/unit/routers/test_billing.py` | Replace BillingAccount mocks |
| `tests/unit/services/test_billing_service.py` | Replace SQLAlchemy with billing_repo mocks |
| `tests/unit/services/test_key_service.py` | Replace SQLAlchemy with api_key_repo mocks |
| `tests/unit/containers/test_ecs_manager.py` | Replace Container model mocks |
| `tests/factories/user_factory.py` | Replace User model import with DynamoDB item factory |
| `tests/unit/routers/*.py` (remaining) | Update mocks: replace DB session with repo mocks |

### Test Strategy

- Unit tests: mock the repository layer (not DynamoDB directly)
- Integration tests: use `moto` library to mock DynamoDB in-process
- LocalStack tests: full end-to-end with real DynamoDB tables

---

## Migration Plan (Data)

### Dev Environment

No data migration needed — dev data is ephemeral. Deploy new CDK stack, old RDS can be destroyed.

### Production (when applicable)

1. Deploy DynamoDB tables alongside existing RDS (both live)
2. Run one-time migration script: read 4 tables from Postgres, write to DynamoDB
3. Switch backend to DynamoDB (deploy new code)
4. Verify everything works
5. Decommission RDS instance

Data volumes are tiny (handful of users), so migration is trivial.

---

## What This Does NOT Change

- **Frontend** — zero changes, API response shapes unchanged
- **WebSocket architecture** — unchanged, still API Gateway → Lambda → FastAPI
- **ECS/EFS container orchestration** — unchanged
- **Clerk auth** — unchanged
- **Stripe billing** — `billing_account` table migrated, checkout/portal/webhooks work the same
- **OpenClaw gateway protocol** — unchanged
- **GooseTown** — no DB tables involved (CLAUDE.md mentions `models/town.py` with town_agents/town_state/etc. tables, but this file does not exist in the repo and no town models are imported — CLAUDE.md description is stale)

---

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| DynamoDB eventually consistent reads on GSIs | Low | Gateway token lookups are rare (connection setup only). Use `ConsistentRead=True` on table PK reads. |
| **Stripe webhook GSI race condition** | Medium | After `create_customer_for_user` writes a `BillingAccount`, Stripe may immediately send a `customer.subscription.created` webhook. The `stripe-customer-index` GSI is eventually consistent — the query may miss the new item. **Mitigation:** Add a small retry (1-2s) in webhook handler if GSI lookup returns no results, or do a secondary table scan by `stripe_customer_id` as fallback. |
| Losing `ON CONFLICT` upsert for billing | Low | Only used by aspirational usage code being dropped |
| `status` GSI hot partition (most containers `stopped`) | Low | Tiny table (<1000 items), no throughput concern |
| boto3 sync in async FastAPI | Low | `asyncio.to_thread()` wrapping, DynamoDB latency <10ms |
| LocalStack DynamoDB fidelity | Low | Well-supported, already used for `WS_CONNECTIONS_TABLE` |
| `service_name` uniqueness not enforceable in DynamoDB | Low | Uniqueness is implicitly guaranteed by 1:1 user→container mapping and deterministic naming (`openclaw-{user_id}-{hash}`). No additional enforcement needed. |

---

## Estimated Scope

| Component | Effort |
|-----------|--------|
| CDK stack rewrite (database-stack.ts + stage files) | Small — 4 tables, 3 GSIs, remove SG refs |
| `core/dynamodb.py` + 4 repository files | Medium — new abstraction layer |
| Modify 18+ backend files (routers/services) | Medium — mechanical replacement, but Stripe webhook + connection_pool are complex |
| Delete 13+ source files (models, aspirational code) | Small — deletion |
| Rewrite test infrastructure (`conftest.py` + 17 test files) | Medium-Large — mock strategy overhaul |
| Delete 6 test files (aspirational/dead) | Small |
| Update `local-dev.sh` | Small — simplification |
| Update `core/config.py` + secret references in stage files | Small |
| **Total** | **~4-5 days** |
