# RDS PostgreSQL → DynamoDB Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace RDS PostgreSQL with DynamoDB for all 4 active tables (users, containers, billing_account, user_api_keys), delete 5 aspirational/dead tables, and update all backend code + CDK infrastructure.

**Architecture:** Repository pattern wrapping boto3 DynamoDB calls. Each table gets a dedicated repo module. All async FastAPI handlers use `asyncio.to_thread()` for boto3 calls. CDK provisions DynamoDB tables with GSIs. No frontend changes.

**Tech Stack:** boto3 (DynamoDB), CDK (aws-dynamodb), FastAPI, pytest + moto (testing)

**Spec:** `docs/superpowers/specs/2026-03-23-rds-to-dynamodb-migration-design.md`

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `apps/backend/core/dynamodb.py` | DynamoDB resource singleton, table name helper, `run_in_thread` wrapper |
| `apps/backend/core/repositories/__init__.py` | Package init |
| `apps/backend/core/repositories/user_repo.py` | User get/put/delete |
| `apps/backend/core/repositories/container_repo.py` | Container CRUD + GSI queries (gateway_token, status) |
| `apps/backend/core/repositories/billing_repo.py` | BillingAccount CRUD + Stripe customer GSI |
| `apps/backend/core/repositories/api_key_repo.py` | API key CRUD + list by user |
| `apps/backend/tests/unit/repositories/test_user_repo.py` | User repo tests |
| `apps/backend/tests/unit/repositories/test_container_repo.py` | Container repo tests |
| `apps/backend/tests/unit/repositories/test_billing_repo.py` | Billing repo tests |
| `apps/backend/tests/unit/repositories/test_api_key_repo.py` | API key repo tests |
| `apps/infra/lib/stacks/database-stack.ts` | Rewritten — DynamoDB tables + GSIs |

### Files to Delete
| File | Reason |
|------|--------|
| `apps/backend/core/database.py` | SQLAlchemy engine/session — replaced |
| `apps/backend/init_db.py` | Schema creation — CDK handles tables |
| `apps/backend/seed_pricing.py` | Seeds dropped model_pricing table |
| `apps/backend/models/base.py` | SQLAlchemy declarative base |
| `apps/backend/models/user.py` | SQLAlchemy model |
| `apps/backend/models/container.py` | SQLAlchemy model |
| `apps/backend/models/billing.py` | 5 billing models (4 dropped, 1 moved to repo) |
| `apps/backend/models/audit_log.py` | Dead code |
| `apps/backend/models/user_api_key.py` | SQLAlchemy model |
| `apps/backend/migrations/001_add_containers_table.sql` | SQL migration |
| `apps/backend/core/services/usage_service.py` | Aspirational |
| `apps/backend/core/services/usage_poller.py` | Aspirational |
| `apps/backend/tests/unit/models/test_audit_log.py` | Dead code test |
| `apps/backend/tests/unit/models/test_billing.py` | Tests dropped models |
| `apps/backend/tests/unit/models/test_tool_pricing.py` | Tests dropped model |
| `apps/backend/tests/unit/services/test_usage_service.py` | Aspirational |
| `apps/backend/tests/unit/services/test_usage_poller.py` | Aspirational |
| `apps/backend/tests/unit/routers/test_usage_tracking.py` | Aspirational |

### Files to Modify
| File | Change Summary |
|------|---------------|
| `apps/backend/models/__init__.py` | Gutted — re-export nothing or delete |
| `apps/backend/main.py` | Remove init_db/UsagePoller, rewrite health check |
| `apps/backend/core/config.py` | Remove DATABASE_URL, add DYNAMODB_TABLE_PREFIX |
| `apps/backend/core/containers/ecs_manager.py` | Replace SQLAlchemy with container_repo |
| `apps/backend/core/containers/__init__.py` | Remove usage recording callback |
| `apps/backend/core/gateway/connection_pool.py` | Replace SQLAlchemy reads+writes with container_repo |
| `apps/backend/core/services/billing_service.py` | Replace SQLAlchemy with billing_repo |
| `apps/backend/core/services/key_service.py` | Replace SQLAlchemy with api_key_repo |
| `apps/backend/routers/users.py` | Replace get_db with user_repo + billing_repo |
| `apps/backend/routers/billing.py` | Replace get_db with billing_repo, stub usage endpoints |
| `apps/backend/routers/container.py` | Replace get_db with container_repo + billing_repo |
| `apps/backend/routers/container_rpc.py` | Replace gateway_token lookup with container_repo |
| `apps/backend/routers/websocket_chat.py` | Replace get_session_factory with container_repo |
| `apps/backend/routers/control_ui_proxy.py` | Replace container lookups with container_repo |
| `apps/backend/routers/proxy.py` | Replace with container_repo + billing_repo + api_key_repo |
| `apps/backend/routers/channels.py` | Replace get_session_factory with container_repo |
| `apps/backend/routers/settings_keys.py` | Replace get_db with api_key_repo |
| `apps/backend/routers/debug.py` | Replace get_db with container_repo |
| `apps/backend/tests/conftest.py` | Remove SQLAlchemy fixtures, add moto DynamoDB fixtures |
| `apps/backend/tests/contract/conftest.py` | Remove get_db overrides |
| `apps/backend/pyproject.toml` | Remove sqlalchemy, asyncpg, greenlet |
| `apps/infra/lib/isol8-stage.ts` | Update DatabaseStack props, remove dbSecurityGroup |
| `apps/infra/lib/local-stage.ts` | Same as isol8-stage |
| `apps/infra/lib/stacks/service-stack.ts` | Remove DB SG ingress, add DynamoDB IAM, remove DATABASE_URL secret |

---

## Task 1: CDK — Replace RDS with DynamoDB Tables

**Files:**
- Rewrite: `apps/infra/lib/stacks/database-stack.ts`
- Modify: `apps/infra/lib/isol8-stage.ts:37-42,70-74,84`
- Modify: `apps/infra/lib/local-stage.ts:37,48-53,78-82`
- Modify: `apps/infra/lib/stacks/service-stack.ts:28,36-40,133-141`

- [ ] **Step 1: Rewrite database-stack.ts**

Replace entire file. Remove all RDS/ec2/secretsmanager imports. Create 4 DynamoDB tables with GSIs:

```typescript
import * as cdk from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as kms from "aws-cdk-lib/aws-kms";
import { Construct } from "constructs";

export interface DatabaseStackProps extends cdk.StackProps {
  environment: string;
  kmsKey: kms.IKey;
}

const ENV_CONFIG: Record<string, { removalPolicy: cdk.RemovalPolicy }> = {
  dev: { removalPolicy: cdk.RemovalPolicy.DESTROY },
  prod: { removalPolicy: cdk.RemovalPolicy.RETAIN },
};

export class DatabaseStack extends cdk.Stack {
  public readonly usersTable: dynamodb.Table;
  public readonly containersTable: dynamodb.Table;
  public readonly billingTable: dynamodb.Table;
  public readonly apiKeysTable: dynamodb.Table;

  constructor(scope: Construct, id: string, props: DatabaseStackProps) {
    super(scope, id, props);

    const config = ENV_CONFIG[props.environment] ?? ENV_CONFIG.dev;
    const env = props.environment;

    this.usersTable = new dynamodb.Table(this, "UsersTable", {
      tableName: `isol8-${env}-users`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });

    this.containersTable = new dynamodb.Table(this, "ContainersTable", {
      tableName: `isol8-${env}-containers`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });
    this.containersTable.addGlobalSecondaryIndex({
      indexName: "gateway-token-index",
      partitionKey: { name: "gateway_token", type: dynamodb.AttributeType.STRING },
    });
    this.containersTable.addGlobalSecondaryIndex({
      indexName: "status-index",
      partitionKey: { name: "status", type: dynamodb.AttributeType.STRING },
    });

    this.billingTable = new dynamodb.Table(this, "BillingTable", {
      tableName: `isol8-${env}-billing-accounts`,
      partitionKey: { name: "clerk_user_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });
    this.billingTable.addGlobalSecondaryIndex({
      indexName: "stripe-customer-index",
      partitionKey: { name: "stripe_customer_id", type: dynamodb.AttributeType.STRING },
    });

    this.apiKeysTable = new dynamodb.Table(this, "ApiKeysTable", {
      tableName: `isol8-${env}-api-keys`,
      partitionKey: { name: "user_id", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "tool_id", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: config.removalPolicy,
      pointInTimeRecovery: true,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: props.kmsKey,
    });

    // Outputs for backend configuration
    new cdk.CfnOutput(this, "DynamoTablePrefix", {
      value: `isol8-${env}-`,
      exportName: `${this.stackName}-table-prefix`,
    });
  }
}
```

- [ ] **Step 2: Update isol8-stage.ts**

Remove `vpc` from DatabaseStack props (DynamoDB is serverless). Remove `dbSecurityGroup` from ServiceStack props. Remove `databaseUrl` secret. Add table ARNs for IAM.

At line 37-42, change:
```typescript
const database = new DatabaseStack(this, `isol8-${env}-database`, {
  stackName: `isol8-${env}-database`,
  environment: env,
  kmsKey: auth.kmsKey,
});
```

At lines 70-74 (ServiceStack props), replace the `database` prop:
```typescript
database: {
  usersTable: database.usersTable,
  containersTable: database.containersTable,
  billingTable: database.billingTable,
  apiKeysTable: database.apiKeysTable,
},
```

At line 84, remove `databaseUrl` from secret names.

- [ ] **Step 3: Update local-stage.ts**

Same changes as isol8-stage.ts — remove `vpc` from DatabaseStack, update database prop shape, remove `databaseUrl` placeholder at line 37.

- [ ] **Step 4: Update service-stack.ts**

In `ServiceStackProps` interface (line 36-40), change `database` prop type:
```typescript
database: {
  usersTable: dynamodb.Table;
  containersTable: dynamodb.Table;
  billingTable: dynamodb.Table;
  apiKeysTable: dynamodb.Table;
};
```

Remove `DbFromServiceIngress` at lines 133-141 (the `CfnSecurityGroupIngress` for port 5432).

Remove `databaseUrl` from `SecretNames` interface at line 28.

Add DynamoDB IAM grants to the service task role:
```typescript
props.database.usersTable.grantReadWriteData(taskRole);
props.database.containersTable.grantReadWriteData(taskRole);
props.database.billingTable.grantReadWriteData(taskRole);
props.database.apiKeysTable.grantReadWriteData(taskRole);
```

Add environment variable for table prefix:
```typescript
DYNAMODB_TABLE_PREFIX: `isol8-${props.environment}-`,
```

- [ ] **Step 5: Verify CDK synth compiles**

Run: `cd apps/infra && npx cdk synth --quiet`
Expected: No errors, generates CloudFormation templates with DynamoDB tables instead of RDS.

- [ ] **Step 6: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts apps/infra/lib/isol8-stage.ts apps/infra/lib/local-stage.ts apps/infra/lib/stacks/service-stack.ts
git commit -m "infra: replace RDS PostgreSQL with DynamoDB tables and GSIs"
```

---

## Task 2: Core DynamoDB Client + Config

**Files:**
- Create: `apps/backend/core/dynamodb.py`
- Modify: `apps/backend/core/config.py:22`

- [ ] **Step 1: Write test for DynamoDB client**

Create `apps/backend/tests/unit/core/test_dynamodb.py`:
```python
import pytest
from unittest.mock import patch, MagicMock

from core.dynamodb import get_table, table_name


def test_table_name_with_prefix():
    with patch("core.dynamodb._table_prefix", "isol8-dev-"):
        assert table_name("containers") == "isol8-dev-containers"


def test_table_name_without_prefix():
    with patch("core.dynamodb._table_prefix", ""):
        assert table_name("containers") == "containers"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/core/test_dynamodb.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.dynamodb'`

- [ ] **Step 3: Create core/dynamodb.py**

```python
"""DynamoDB client singleton and helpers."""

import asyncio
import functools
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import boto3

from core.config import settings

_table_prefix: str = getattr(settings, "DYNAMODB_TABLE_PREFIX", "")
_dynamodb_resource = None


def _get_resource():
    global _dynamodb_resource
    if _dynamodb_resource is None:
        kwargs = {}
        endpoint = getattr(settings, "DYNAMODB_ENDPOINT_URL", None)
        if endpoint:
            kwargs["endpoint_url"] = endpoint
        _dynamodb_resource = boto3.resource(
            "dynamodb",
            region_name=getattr(settings, "AWS_REGION", "us-east-1"),
            **kwargs,
        )
    return _dynamodb_resource


def table_name(short_name: str) -> str:
    """Return full table name with environment prefix."""
    return f"{_table_prefix}{short_name}"


def get_table(short_name: str):
    """Get a DynamoDB Table resource by short name."""
    return _get_resource().Table(table_name(short_name))


T = TypeVar("T")


async def run_in_thread(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a synchronous boto3 call in a thread executor."""
    return await asyncio.to_thread(functools.partial(func, **kwargs) if kwargs else func, *args)


def utc_now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
```

- [ ] **Step 4: Update core/config.py**

At line 22, replace `DATABASE_URL` with DynamoDB config:
```python
DYNAMODB_TABLE_PREFIX: str = os.getenv("DYNAMODB_TABLE_PREFIX", "isol8-dev-")
DYNAMODB_ENDPOINT_URL: str | None = os.getenv("DYNAMODB_ENDPOINT_URL", None)
```

Keep `DATABASE_URL` temporarily commented out — we'll delete it when all consumers are migrated.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/core/test_dynamodb.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/backend/core/dynamodb.py apps/backend/core/config.py apps/backend/tests/unit/core/test_dynamodb.py
git commit -m "feat: add DynamoDB client singleton and config"
```

---

## Task 3: User Repository

**Files:**
- Create: `apps/backend/core/repositories/__init__.py`
- Create: `apps/backend/core/repositories/user_repo.py`
- Create: `apps/backend/tests/unit/repositories/__init__.py`
- Create: `apps/backend/tests/unit/repositories/test_user_repo.py`

- [ ] **Step 1: Write test for user_repo**

```python
import pytest
from moto import mock_aws
import boto3

from core.repositories import user_repo


@pytest.fixture
def dynamodb_users_table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="test-users",
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield table


@pytest.mark.asyncio
async def test_put_and_get_user(dynamodb_users_table, monkeypatch):
    monkeypatch.setattr(user_repo, "_get_table", lambda: dynamodb_users_table)

    await user_repo.put("user_abc123")
    result = await user_repo.get("user_abc123")
    assert result is not None
    assert result["user_id"] == "user_abc123"


@pytest.mark.asyncio
async def test_get_nonexistent_user(dynamodb_users_table, monkeypatch):
    monkeypatch.setattr(user_repo, "_get_table", lambda: dynamodb_users_table)

    result = await user_repo.get("user_doesnotexist")
    assert result is None


@pytest.mark.asyncio
async def test_delete_user(dynamodb_users_table, monkeypatch):
    monkeypatch.setattr(user_repo, "_get_table", lambda: dynamodb_users_table)

    await user_repo.put("user_abc123")
    await user_repo.delete("user_abc123")
    result = await user_repo.get("user_abc123")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_user_repo.py -v`
Expected: FAIL

- [ ] **Step 3: Create the repository package and user_repo.py**

Create `apps/backend/core/repositories/__init__.py` (empty).
Create `apps/backend/tests/unit/repositories/__init__.py` (empty).

Create `apps/backend/core/repositories/user_repo.py`:
```python
"""User repository — DynamoDB operations for the users table."""

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("users")


async def get(user_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(table.get_item, Key={"user_id": user_id})
    return response.get("Item")


async def put(user_id: str) -> dict:
    table = _get_table()
    item = {"user_id": user_id, "created_at": utc_now_iso()}
    await run_in_thread(table.put_item, Item=item)
    return item


async def delete(user_id: str) -> None:
    table = _get_table()
    await run_in_thread(table.delete_item, Key={"user_id": user_id})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_user_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/repositories/ apps/backend/tests/unit/repositories/
git commit -m "feat: add user DynamoDB repository"
```

---

## Task 4: Container Repository

**Files:**
- Create: `apps/backend/core/repositories/container_repo.py`
- Create: `apps/backend/tests/unit/repositories/test_container_repo.py`

- [ ] **Step 1: Write test for container_repo**

```python
import uuid
import pytest
from moto import mock_aws
import boto3

from core.repositories import container_repo


@pytest.fixture
def dynamodb_containers_table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="test-containers",
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "gateway_token", "AttributeType": "S"},
                {"AttributeName": "status", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "gateway-token-index",
                    "KeySchema": [{"AttributeName": "gateway_token", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "status-index",
                    "KeySchema": [{"AttributeName": "status", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield table


@pytest.mark.asyncio
async def test_upsert_and_get_by_user(dynamodb_containers_table, monkeypatch):
    monkeypatch.setattr(container_repo, "_get_table", lambda: dynamodb_containers_table)

    await container_repo.upsert(
        user_id="user_1",
        gateway_token="tok_abc",
        status="provisioning",
    )
    result = await container_repo.get_by_user_id("user_1")
    assert result is not None
    assert result["user_id"] == "user_1"
    assert result["gateway_token"] == "tok_abc"
    assert result["status"] == "provisioning"
    assert "id" in result


@pytest.mark.asyncio
async def test_get_by_gateway_token(dynamodb_containers_table, monkeypatch):
    monkeypatch.setattr(container_repo, "_get_table", lambda: dynamodb_containers_table)

    await container_repo.upsert(
        user_id="user_1",
        gateway_token="tok_xyz",
        status="running",
    )
    result = await container_repo.get_by_gateway_token("tok_xyz")
    assert result is not None
    assert result["user_id"] == "user_1"


@pytest.mark.asyncio
async def test_get_by_status(dynamodb_containers_table, monkeypatch):
    monkeypatch.setattr(container_repo, "_get_table", lambda: dynamodb_containers_table)

    await container_repo.upsert(user_id="u1", gateway_token="t1", status="running")
    await container_repo.upsert(user_id="u2", gateway_token="t2", status="stopped")
    await container_repo.upsert(user_id="u3", gateway_token="t3", status="running")

    running = await container_repo.get_by_status("running")
    assert len(running) == 2
    assert all(c["status"] == "running" for c in running)


@pytest.mark.asyncio
async def test_update_status(dynamodb_containers_table, monkeypatch):
    monkeypatch.setattr(container_repo, "_get_table", lambda: dynamodb_containers_table)

    await container_repo.upsert(user_id="u1", gateway_token="t1", status="provisioning")
    await container_repo.update_status("u1", "running", substatus="gateway_healthy")
    result = await container_repo.get_by_user_id("u1")
    assert result["status"] == "running"
    assert result["substatus"] == "gateway_healthy"


@pytest.mark.asyncio
async def test_update_fields(dynamodb_containers_table, monkeypatch):
    monkeypatch.setattr(container_repo, "_get_table", lambda: dynamodb_containers_table)

    await container_repo.upsert(user_id="u1", gateway_token="t1", status="provisioning")
    await container_repo.update_fields("u1", task_arn="arn:aws:ecs:...", service_name="svc-123")
    result = await container_repo.get_by_user_id("u1")
    assert result["task_arn"] == "arn:aws:ecs:..."
    assert result["service_name"] == "svc-123"


@pytest.mark.asyncio
async def test_delete(dynamodb_containers_table, monkeypatch):
    monkeypatch.setattr(container_repo, "_get_table", lambda: dynamodb_containers_table)

    await container_repo.upsert(user_id="u1", gateway_token="t1", status="running")
    await container_repo.delete("u1")
    assert await container_repo.get_by_user_id("u1") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_container_repo.py -v`
Expected: FAIL

- [ ] **Step 3: Create container_repo.py**

```python
"""Container repository — DynamoDB operations for the containers table."""

import uuid

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("containers")


async def get_by_user_id(user_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(table.get_item, Key={"user_id": user_id})
    return response.get("Item")


async def get_by_gateway_token(token: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(
        table.query,
        IndexName="gateway-token-index",
        KeyConditionExpression=Key("gateway_token").eq(token),
    )
    items = response.get("Items", [])
    return items[0] if items else None


async def get_by_status(status: str) -> list[dict]:
    table = _get_table()
    response = await run_in_thread(
        table.query,
        IndexName="status-index",
        KeyConditionExpression=Key("status").eq(status),
    )
    return response.get("Items", [])


async def upsert(
    user_id: str,
    gateway_token: str,
    status: str = "provisioning",
    **extra_fields,
) -> dict:
    table = _get_table()
    now = utc_now_iso()
    item = {
        "user_id": user_id,
        "id": str(uuid.uuid4()),
        "gateway_token": gateway_token,
        "status": status,
        "created_at": now,
        "updated_at": now,
        **extra_fields,
    }
    # Preserve existing id and created_at if item already exists
    existing = await get_by_user_id(user_id)
    if existing:
        item["id"] = existing["id"]
        item["created_at"] = existing["created_at"]
    await run_in_thread(table.put_item, Item=item)
    return item


async def update_status(user_id: str, status: str, substatus: str | None = None) -> None:
    table = _get_table()
    expr = "SET #s = :s, updated_at = :now"
    names = {"#s": "status"}
    values = {":s": status, ":now": utc_now_iso()}
    if substatus is not None:
        expr += ", substatus = :sub"
        values[":sub"] = substatus
    await run_in_thread(
        table.update_item,
        Key={"user_id": user_id},
        UpdateExpression=expr,
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


async def update_fields(user_id: str, **fields) -> None:
    if not fields:
        return
    table = _get_table()
    names = {}
    values = {":now": utc_now_iso()}
    parts = ["updated_at = :now"]
    for i, (key, val) in enumerate(fields.items()):
        alias = f"#f{i}"
        placeholder = f":v{i}"
        names[alias] = key
        values[placeholder] = val
        parts.append(f"{alias} = {placeholder}")
    await run_in_thread(
        table.update_item,
        Key={"user_id": user_id},
        UpdateExpression="SET " + ", ".join(parts),
        ExpressionAttributeNames=names,
        ExpressionAttributeValues=values,
    )


async def delete(user_id: str) -> None:
    table = _get_table()
    await run_in_thread(table.delete_item, Key={"user_id": user_id})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_container_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/repositories/container_repo.py apps/backend/tests/unit/repositories/test_container_repo.py
git commit -m "feat: add container DynamoDB repository with GSI queries"
```

---

## Task 5: Billing Repository

**Files:**
- Create: `apps/backend/core/repositories/billing_repo.py`
- Create: `apps/backend/tests/unit/repositories/test_billing_repo.py`

- [ ] **Step 1: Write test for billing_repo**

```python
import pytest
from moto import mock_aws
import boto3

from core.repositories import billing_repo


@pytest.fixture
def dynamodb_billing_table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="test-billing-accounts",
            KeySchema=[{"AttributeName": "clerk_user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": "clerk_user_id", "AttributeType": "S"},
                {"AttributeName": "stripe_customer_id", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "stripe-customer-index",
                    "KeySchema": [{"AttributeName": "stripe_customer_id", "KeyType": "HASH"}],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield table


@pytest.mark.asyncio
async def test_create_and_get(dynamodb_billing_table, monkeypatch):
    monkeypatch.setattr(billing_repo, "_get_table", lambda: dynamodb_billing_table)

    account = await billing_repo.create(
        clerk_user_id="user_1",
        stripe_customer_id="cus_abc",
    )
    assert account["clerk_user_id"] == "user_1"
    assert account["plan_tier"] == "free"

    result = await billing_repo.get_by_clerk_user_id("user_1")
    assert result["stripe_customer_id"] == "cus_abc"


@pytest.mark.asyncio
async def test_get_by_stripe_customer_id(dynamodb_billing_table, monkeypatch):
    monkeypatch.setattr(billing_repo, "_get_table", lambda: dynamodb_billing_table)

    await billing_repo.create(clerk_user_id="user_1", stripe_customer_id="cus_xyz")
    result = await billing_repo.get_by_stripe_customer_id("cus_xyz")
    assert result is not None
    assert result["clerk_user_id"] == "user_1"


@pytest.mark.asyncio
async def test_update_subscription(dynamodb_billing_table, monkeypatch):
    monkeypatch.setattr(billing_repo, "_get_table", lambda: dynamodb_billing_table)

    await billing_repo.create(clerk_user_id="user_1", stripe_customer_id="cus_abc")
    await billing_repo.update_subscription("user_1", subscription_id="sub_123", plan_tier="starter")
    result = await billing_repo.get_by_clerk_user_id("user_1")
    assert result["stripe_subscription_id"] == "sub_123"
    assert result["plan_tier"] == "starter"


@pytest.mark.asyncio
async def test_create_idempotent(dynamodb_billing_table, monkeypatch):
    monkeypatch.setattr(billing_repo, "_get_table", lambda: dynamodb_billing_table)

    await billing_repo.create(clerk_user_id="user_1", stripe_customer_id="cus_1")
    # Second create should not overwrite
    existing = await billing_repo.get_or_create(clerk_user_id="user_1", stripe_customer_id="cus_2")
    assert existing["stripe_customer_id"] == "cus_1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_billing_repo.py -v`
Expected: FAIL

- [ ] **Step 3: Create billing_repo.py**

```python
"""Billing account repository — DynamoDB operations for billing-accounts table."""

import uuid
from decimal import Decimal

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("billing-accounts")


async def get_by_clerk_user_id(clerk_user_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(table.get_item, Key={"clerk_user_id": clerk_user_id})
    return response.get("Item")


async def get_by_stripe_customer_id(stripe_customer_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(
        table.query,
        IndexName="stripe-customer-index",
        KeyConditionExpression=Key("stripe_customer_id").eq(stripe_customer_id),
    )
    items = response.get("Items", [])
    return items[0] if items else None


async def create(
    clerk_user_id: str,
    stripe_customer_id: str,
    plan_tier: str = "free",
    markup_multiplier: float = 1.4,
) -> dict:
    table = _get_table()
    now = utc_now_iso()
    item = {
        "clerk_user_id": clerk_user_id,
        "id": str(uuid.uuid4()),
        "stripe_customer_id": stripe_customer_id,
        "plan_tier": plan_tier,
        "markup_multiplier": Decimal(str(markup_multiplier)),
        "created_at": now,
        "updated_at": now,
    }
    await run_in_thread(table.put_item, Item=item)
    return item


async def get_or_create(
    clerk_user_id: str,
    stripe_customer_id: str,
) -> dict:
    existing = await get_by_clerk_user_id(clerk_user_id)
    if existing:
        return existing
    return await create(clerk_user_id=clerk_user_id, stripe_customer_id=stripe_customer_id)


async def update_subscription(
    clerk_user_id: str,
    subscription_id: str | None = None,
    plan_tier: str | None = None,
) -> None:
    table = _get_table()
    parts = ["updated_at = :now"]
    values = {":now": utc_now_iso()}
    names = {}
    if subscription_id is not None:
        parts.append("stripe_subscription_id = :sub")
        values[":sub"] = subscription_id
    if plan_tier is not None:
        parts.append("plan_tier = :tier")
        values[":tier"] = plan_tier
    await run_in_thread(
        table.update_item,
        Key={"clerk_user_id": clerk_user_id},
        UpdateExpression="SET " + ", ".join(parts),
        ExpressionAttributeValues=values,
    )


async def delete(clerk_user_id: str) -> None:
    table = _get_table()
    await run_in_thread(table.delete_item, Key={"clerk_user_id": clerk_user_id})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_billing_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/repositories/billing_repo.py apps/backend/tests/unit/repositories/test_billing_repo.py
git commit -m "feat: add billing account DynamoDB repository with Stripe GSI"
```

---

## Task 6: API Key Repository

**Files:**
- Create: `apps/backend/core/repositories/api_key_repo.py`
- Create: `apps/backend/tests/unit/repositories/test_api_key_repo.py`

- [ ] **Step 1: Write test for api_key_repo**

```python
import pytest
from moto import mock_aws
import boto3

from core.repositories import api_key_repo


@pytest.fixture
def dynamodb_api_keys_table():
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.create_table(
            TableName="test-api-keys",
            KeySchema=[
                {"AttributeName": "user_id", "KeyType": "HASH"},
                {"AttributeName": "tool_id", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "user_id", "AttributeType": "S"},
                {"AttributeName": "tool_id", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        table.wait_until_exists()
        yield table


@pytest.mark.asyncio
async def test_set_and_get_key(dynamodb_api_keys_table, monkeypatch):
    monkeypatch.setattr(api_key_repo, "_get_table", lambda: dynamodb_api_keys_table)

    await api_key_repo.set_key("user_1", "perplexity", "encrypted_abc")
    result = await api_key_repo.get_key("user_1", "perplexity")
    assert result is not None
    assert result["encrypted_key"] == "encrypted_abc"


@pytest.mark.asyncio
async def test_list_keys(dynamodb_api_keys_table, monkeypatch):
    monkeypatch.setattr(api_key_repo, "_get_table", lambda: dynamodb_api_keys_table)

    await api_key_repo.set_key("user_1", "perplexity", "enc1")
    await api_key_repo.set_key("user_1", "elevenlabs", "enc2")
    await api_key_repo.set_key("user_2", "perplexity", "enc3")

    keys = await api_key_repo.list_keys("user_1")
    assert len(keys) == 2
    tool_ids = {k["tool_id"] for k in keys}
    assert tool_ids == {"perplexity", "elevenlabs"}


@pytest.mark.asyncio
async def test_delete_key(dynamodb_api_keys_table, monkeypatch):
    monkeypatch.setattr(api_key_repo, "_get_table", lambda: dynamodb_api_keys_table)

    await api_key_repo.set_key("user_1", "perplexity", "enc1")
    deleted = await api_key_repo.delete_key("user_1", "perplexity")
    assert deleted is True
    result = await api_key_repo.get_key("user_1", "perplexity")
    assert result is None


@pytest.mark.asyncio
async def test_update_key(dynamodb_api_keys_table, monkeypatch):
    monkeypatch.setattr(api_key_repo, "_get_table", lambda: dynamodb_api_keys_table)

    await api_key_repo.set_key("user_1", "perplexity", "old_enc")
    await api_key_repo.set_key("user_1", "perplexity", "new_enc")
    result = await api_key_repo.get_key("user_1", "perplexity")
    assert result["encrypted_key"] == "new_enc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_api_key_repo.py -v`
Expected: FAIL

- [ ] **Step 3: Create api_key_repo.py**

```python
"""API key repository — DynamoDB operations for the api-keys table."""

import uuid

from boto3.dynamodb.conditions import Key

from core.dynamodb import get_table, run_in_thread, utc_now_iso


def _get_table():
    return get_table("api-keys")


async def get_key(user_id: str, tool_id: str) -> dict | None:
    table = _get_table()
    response = await run_in_thread(
        table.get_item,
        Key={"user_id": user_id, "tool_id": tool_id},
    )
    return response.get("Item")


async def set_key(user_id: str, tool_id: str, encrypted_key: str) -> dict:
    table = _get_table()
    now = utc_now_iso()
    existing = await get_key(user_id, tool_id)
    item = {
        "user_id": user_id,
        "tool_id": tool_id,
        "id": existing["id"] if existing else str(uuid.uuid4()),
        "encrypted_key": encrypted_key,
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
    }
    await run_in_thread(table.put_item, Item=item)
    return item


async def list_keys(user_id: str) -> list[dict]:
    table = _get_table()
    response = await run_in_thread(
        table.query,
        KeyConditionExpression=Key("user_id").eq(user_id),
        ProjectionExpression="tool_id, created_at, updated_at",
    )
    return response.get("Items", [])


async def delete_key(user_id: str, tool_id: str) -> bool:
    table = _get_table()
    response = await run_in_thread(
        table.delete_item,
        Key={"user_id": user_id, "tool_id": tool_id},
        ReturnValues="ALL_OLD",
    )
    return "Attributes" in response
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd apps/backend && uv run pytest tests/unit/repositories/test_api_key_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/repositories/api_key_repo.py apps/backend/tests/unit/repositories/test_api_key_repo.py
git commit -m "feat: add API key DynamoDB repository with composite key"
```

---

## Task 7: Migrate Services (billing_service, key_service)

**Files:**
- Modify: `apps/backend/core/services/billing_service.py:6-8,11,47-48,56,72,76,124,134`
- Modify: `apps/backend/core/services/key_service.py:6-7,10,37-38,44-72`

- [ ] **Step 1: Rewrite billing_service.py**

Remove all SQLAlchemy imports (lines 6-8, 11). Remove `db: AsyncSession` constructor param. Replace all `self.db.execute(select(...))` calls with `billing_repo` calls.

Key changes:
- `__init__(self, db)` → `__init__(self)` (no DB session needed)
- `self.db.execute(select(BillingAccount).where(...))` → `await billing_repo.get_by_clerk_user_id(...)`
- `self.db.add(account)` + `self.db.commit()` → `await billing_repo.create(...)`
- IntegrityError catch → `billing_repo.get_or_create(...)`
- Stripe customer lookup → `billing_repo.get_by_stripe_customer_id(...)`
- Subscription update → `billing_repo.update_subscription(...)`

- [ ] **Step 2: Rewrite key_service.py**

Remove SQLAlchemy imports (lines 6-7, 10). Remove `db: AsyncSession` constructor param.

Key changes:
- `__init__(self, db)` → `__init__(self)` (no DB session needed)
- `self.db.execute(select(UserApiKey).where(...))` → `await api_key_repo.get_key(user_id, tool_id)`
- `self.db.add(key)` + `self.db.flush()` → `await api_key_repo.set_key(...)`
- `self.db.execute(delete(...))` → `await api_key_repo.delete_key(...)`
- List query → `await api_key_repo.list_keys(user_id)`

- [ ] **Step 3: Update existing service tests**

Update `tests/unit/services/test_billing_service.py` — remove `db_session` fixture usage, mock `billing_repo` instead.

Update `tests/unit/services/test_key_service.py` — remove `db_session` fixture usage, mock `api_key_repo` instead.

- [ ] **Step 4: Run service tests**

Run: `cd apps/backend && uv run pytest tests/unit/services/test_billing_service.py tests/unit/services/test_key_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/billing_service.py apps/backend/core/services/key_service.py apps/backend/tests/unit/services/
git commit -m "feat: migrate billing and key services from SQLAlchemy to DynamoDB repos"
```

---

## Task 8: Migrate ECS Manager + Connection Pool

**Files:**
- Modify: `apps/backend/core/containers/ecs_manager.py:17-18,28-29,47`
- Modify: `apps/backend/core/containers/__init__.py:13,16,38-50`
- Modify: `apps/backend/core/gateway/connection_pool.py:19,28-29`

- [ ] **Step 1: Rewrite ecs_manager.py DB interactions**

Remove SQLAlchemy imports (lines 17-18: `from sqlalchemy import select, update` and `from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker`). Remove database import (line 28: `from core.database import async_session_factory` — note: actual import name is `async_session_factory`, not `get_session_factory`). Remove `session_factory` constructor param.

Replace all `async with self._session_factory() as db:` patterns with direct `container_repo` calls:
- `db.execute(select(Container).where(Container.user_id == user_id))` → `await container_repo.get_by_user_id(user_id)`
- `db.add(container)` + `db.commit()` → `await container_repo.upsert(...)`
- `db.execute(update(Container).where(...).values(status=...))` → `await container_repo.update_status(...)`
- `db.execute(update(Container).where(...).values(task_arn=...))` → `await container_repo.update_fields(...)`

- [ ] **Step 2: Rewrite containers/__init__.py**

Remove database import (line 13) and usage service import (line 16). Remove the usage recording callback (lines 38-50) — this was aspirational code.

- [ ] **Step 3: Rewrite connection_pool.py DB interactions**

Remove SQLAlchemy imports (line 19: `from sqlalchemy import select, update`). Remove database import (line 28: `from core.database import get_session_factory`). Remove Container model import (line 29).

Replace `get_session_factory()` pattern with `container_repo`:
- Container lookups → `await container_repo.get_by_user_id(...)` or `await container_repo.get_by_gateway_token(...)`
- Status updates → `await container_repo.update_status(...)`

- [ ] **Step 4: Update container/ECS tests**

Update `tests/unit/containers/test_ecs_manager.py` — mock `container_repo` instead of DB session.

- [ ] **Step 5: Run tests**

Run: `cd apps/backend && uv run pytest tests/unit/containers/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/backend/core/containers/ apps/backend/core/gateway/connection_pool.py apps/backend/tests/unit/containers/
git commit -m "feat: migrate ECS manager and connection pool from SQLAlchemy to DynamoDB repos"
```

---

## Task 9: Migrate All Routers

**Files:**
- Modify: `apps/backend/routers/users.py:6-8,10,13,31,34-50`
- Modify: `apps/backend/routers/billing.py:8-9,16,19,50-52,98-100,149,189-239`
- Modify: `apps/backend/routers/container.py:11-12,18-19,28,56-58`
- Modify: `apps/backend/routers/container_rpc.py:22,28`
- Modify: `apps/backend/routers/websocket_chat.py:20,23,58-60`
- Modify: `apps/backend/routers/control_ui_proxy.py`
- Modify: `apps/backend/routers/proxy.py:14-15,18,20-21,54-60`
- Modify: `apps/backend/routers/channels.py:15,36-38`
- Modify: `apps/backend/routers/settings_keys.py:7,10-11,22-25,33-37,52-55`
- Modify: `apps/backend/routers/debug.py:11-12,20-21,51,56-78`

This is the largest task — mechanical but extensive. Each router follows the same pattern:

**Pattern for every router:**
1. Remove `from sqlalchemy...` imports
2. Remove `from core.database import get_db` (or `get_session_factory`)
3. Remove `from models.xxx import Xxx`
4. Add `from core.repositories import xxx_repo`
5. Remove `db: AsyncSession = Depends(get_db)` from function signatures
6. Replace `db.execute(select(...))` → `await xxx_repo.get_by_...()`
7. Remove `await db.commit()` / `await db.rollback()` calls

- [ ] **Step 1: Migrate routers/users.py**

```python
# Remove: lines 6-8 (sqlalchemy imports), line 10 (get_db), line 13 (User model)
# Add:
from core.repositories import user_repo, billing_repo

# sync_user function: remove db param, replace body:
async def sync_user(auth: AuthContext = Depends(get_current_user)):
    user = await user_repo.get(auth.user_id)
    if not user:
        await user_repo.put(auth.user_id)
    # Ensure billing account exists
    billing_svc = BillingService()  # No db param
    await billing_svc.create_customer_for_user(auth.user_id)
    return SyncUserResponse(status="ok", user_id=auth.user_id)
```

- [ ] **Step 2: Migrate routers/billing.py**

Remove SQLAlchemy imports. Replace `db` param with repo calls. **Critical: Stripe webhook handler** — replace `select(BillingAccount).where(BillingAccount.stripe_customer_id == customer_id)` with `await billing_repo.get_by_stripe_customer_id(customer_id)`.

Stub out `/usage` endpoint to return empty data (usage tracking dropped):
```python
@router.get("/usage")
async def get_usage(auth: AuthContext = Depends(get_current_user)):
    return {"period": None, "total_cost": 0, "total_requests": 0, "by_model": [], "by_day": []}
```

**Stripe webhook GSI race condition:** When `create_customer_for_user` writes a new billing account and Stripe immediately fires a webhook, the `stripe-customer-index` GSI may not have propagated yet. Add a simple retry in the webhook handler:
```python
account = await billing_repo.get_by_stripe_customer_id(customer_id)
if account is None:
    # GSI eventual consistency — retry once after brief delay
    await asyncio.sleep(1)
    account = await billing_repo.get_by_stripe_customer_id(customer_id)
if account is None:
    logger.warning(f"Billing account not found for Stripe customer {customer_id}")
    return JSONResponse(status_code=200, content={"status": "ignored"})
```

- [ ] **Step 3: Migrate routers/container.py**

Replace `_user_has_subscription()`:
```python
async def _user_has_subscription(user_id: str) -> bool:
    account = await billing_repo.get_by_clerk_user_id(user_id)
    return account is not None and account.get("stripe_subscription_id") is not None
```

- [ ] **Step 4: Migrate remaining routers**

Apply the same pattern to: `container_rpc.py`, `websocket_chat.py`, `control_ui_proxy.py`, `proxy.py`, `channels.py`, `settings_keys.py`, `debug.py`.

For routers using `get_session_factory()` (websocket_chat, channels, proxy):
- Replace `session_factory = get_session_factory()` + `async with session_factory() as db:` with direct repo calls
- Pass repo functions instead of DB sessions to downstream service calls

- [ ] **Step 5: Update all router tests**

Update mocks in all `tests/unit/routers/test_*.py` files:
- Replace `override_get_db` / `mock_db_session` with repo-level mocks using `monkeypatch` on repo modules
- Remove `BillingAccount`, `Container`, `User` model imports from tests

- [ ] **Step 6: Run all router tests**

Run: `cd apps/backend && uv run pytest tests/unit/routers/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apps/backend/routers/ apps/backend/tests/unit/routers/
git commit -m "feat: migrate all routers from SQLAlchemy to DynamoDB repos"
```

---

## Task 10: Rewrite main.py Health Check + Cleanup

**Files:**
- Modify: `apps/backend/main.py:16,20,51-54,228-234`
- Modify: `apps/backend/models/__init__.py`

- [ ] **Step 1: Rewrite main.py**

Remove line 16 (`from sqlalchemy import text`), line 20 (`from core.database import get_db, get_session_factory`).

Remove UsagePoller startup (lines 51-54):
```python
# DELETE these lines:
# db_factory = get_session_factory()
# usage_poller = UsagePoller(db_factory=db_factory)
```

Rewrite health check (lines 228-234):
```python
@app.get("/health")
async def health_check():
    """Health check for ALB — validates DynamoDB connectivity."""
    try:
        from core.dynamodb import get_table, run_in_thread
        table = get_table("users")
        await run_in_thread(table.load)  # DescribeTable API call — validates connectivity
        return {"status": "healthy", "database": "dynamodb"}
    except Exception as e:
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})
```
Note: `table.load()` is a method that forces a `DescribeTable` API call. Do NOT use `table.table_status` — it's a property, not callable.

- [ ] **Step 2: Gut models/__init__.py**

Replace with empty package or delete entirely:
```python
"""Models package — DynamoDB items are plain dicts, no ORM models needed."""
```

- [ ] **Step 3: Run health check test**

Run: `cd apps/backend && uv run pytest tests/unit/test_health.py -v`
Expected: PASS (after updating the test to not mock get_db)

- [ ] **Step 4: Commit**

```bash
git add apps/backend/main.py apps/backend/models/__init__.py apps/backend/tests/unit/test_health.py
git commit -m "feat: rewrite health check for DynamoDB, remove UsagePoller startup"
```

---

## Task 11: Update Test Infrastructure (BEFORE deleting files)

**IMPORTANT:** This task MUST run before deleting old files, because `tests/conftest.py` imports from `models/` and `core/database.py`. Rewriting the test infra first prevents intermediate breakage.

**Files:**
- Modify: `apps/backend/tests/conftest.py:16,19-24,27-30,43-94`
- Modify: `apps/backend/tests/contract/conftest.py:31,72-73`
- Modify: `apps/backend/tests/contract/test_api_contracts.py`
- Modify: `apps/backend/tests/contract/test_websocket_contracts.py`
- Modify: `apps/backend/tests/unit/test_openapi_config.py`
- Modify: `apps/backend/tests/unit/routers/test_websocket_agent_chat.py` (patches `get_session_factory`)
- Modify: `apps/backend/tests/unit/routers/test_websocket_chat.py` (patches `get_session_factory`)
- Modify: `apps/backend/tests/unit/routers/test_channels.py` (patches `get_session_factory`)
- Modify: `apps/backend/tests/factories/user_factory.py` (imports `User` model)
- Modify: `apps/backend/tests/unit/models/test_user.py` (rewrite for DynamoDB)
- Modify: `apps/backend/tests/unit/models/test_container.py` (rewrite for DynamoDB)
- Modify: `apps/backend/tests/unit/models/test_user_api_keys.py` (rewrite for DynamoDB)

- [ ] **Step 1: Rewrite tests/conftest.py**

Remove all SQLAlchemy fixtures (`override_get_db`, `override_get_session_factory`, model imports at lines 19-24, engine setup at 27-30, `db_session` fixture at 43-84). Add moto-based DynamoDB fixtures:

```python
import pytest
from moto import mock_aws
import boto3


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """Mock AWS credentials for moto."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def dynamodb_tables():
    """Create all DynamoDB tables for testing."""
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        # Create all 4 tables with their GSIs
        # (table creation code same as repo tests)
        ...
        yield ddb
```

- [ ] **Step 2: Update test files that patch `get_session_factory`**

These files directly patch the SQLAlchemy session factory and will break:
- `tests/unit/routers/test_websocket_agent_chat.py` (line ~201) — replace `get_session_factory` patch with `container_repo` mock
- `tests/unit/routers/test_websocket_chat.py` (line ~51) — same pattern
- `tests/unit/routers/test_channels.py` — same pattern

- [ ] **Step 3: Update tests/factories/user_factory.py**

Replace `from models.user import User` with a plain dict factory:
```python
def create_user(user_id: str = "user_test123") -> dict:
    return {"user_id": user_id, "created_at": "2026-01-01T00:00:00+00:00"}
```

- [ ] **Step 4: Update contract test conftest**

Remove `get_db` and `get_session_factory` overrides in `tests/contract/conftest.py`. Replace with repo-level mocks if needed.

- [ ] **Step 5: Run full test suite**

Run: `cd apps/backend && uv run pytest tests/ -v --tb=short`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add apps/backend/tests/
git commit -m "chore: rewrite test infrastructure for DynamoDB (moto)"
```

---

## Task 12: Delete Dead/Aspirational Files

**Files:** See "Files to Delete" section above.

- [ ] **Step 1: Delete source files**

```bash
cd apps/backend
rm -f core/database.py init_db.py seed_pricing.py
rm -f models/base.py models/user.py models/container.py models/billing.py models/audit_log.py models/user_api_key.py
rm -f migrations/001_add_containers_table.sql
rm -f core/services/usage_service.py core/services/usage_poller.py
```

- [ ] **Step 2: Delete test files for dropped code**

```bash
cd apps/backend
rm -f tests/unit/models/test_audit_log.py tests/unit/models/test_billing.py tests/unit/models/test_tool_pricing.py
rm -f tests/unit/services/test_usage_service.py tests/unit/services/test_usage_poller.py
rm -f tests/unit/routers/test_usage_tracking.py
```

- [ ] **Step 3: Remove SQLAlchemy dependencies from pyproject.toml**

Remove `sqlalchemy[asyncio]`, `asyncpg`, and `greenlet` from dependencies. Add `moto[dynamodb]` to dev dependencies if not present.

- [ ] **Step 4: Run full test suite**

Run: `cd apps/backend && uv run pytest tests/ -v`
Expected: All tests PASS. No import errors for deleted modules.

- [ ] **Step 5: Commit**

```bash
git add -A apps/backend/
git commit -m "chore: delete SQLAlchemy models, aspirational usage code, and RDS dependencies"
```

---

## Task 13: Update local-dev.sh + Config

**Files:**
- Modify: `scripts/local-dev.sh`
- Modify: `apps/backend/core/config.py`

- [ ] **Step 1: Update local-dev.sh**

Remove RDS wait/health-check logic. Remove `DATABASE_URL` generation from RDS endpoint. DynamoDB tables are created by `cdklocal deploy` — no extra setup needed.

Add `DYNAMODB_ENDPOINT_URL=http://localhost:4566` to the backend environment (LocalStack endpoint).

Add `DYNAMODB_TABLE_PREFIX=isol8-local-` to match CDK local stage table names.

- [ ] **Step 2: Finalize core/config.py**

Remove the commented-out `DATABASE_URL` (if still present). Ensure `DYNAMODB_TABLE_PREFIX` and `DYNAMODB_ENDPOINT_URL` are the only DB-related settings.

- [ ] **Step 3: Test local-dev.sh boots cleanly**

Run: `./scripts/local-dev.sh --seed-only`
Expected: LocalStack starts, CDK deploys DynamoDB tables, no RDS errors.

- [ ] **Step 4: Commit**

```bash
git add scripts/local-dev.sh apps/backend/core/config.py
git commit -m "chore: update local-dev.sh for DynamoDB, remove RDS config"
```

---

## Task 14: Final Verification

- [ ] **Step 1: Run full backend test suite**

Run: `cd apps/backend && uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 2: Run linting**

Run: `cd apps/backend && uv run ruff check .`
Expected: No errors

- [ ] **Step 3: Verify no SQLAlchemy references remain**

Run: `grep -r "sqlalchemy\|asyncpg\|get_db\|AsyncSession\|DeclarativeBase" apps/backend/core/ apps/backend/routers/ apps/backend/main.py --include="*.py"`
Expected: No matches

- [ ] **Step 4: Verify CDK synth**

Run: `cd apps/infra && npx cdk synth --quiet`
Expected: Clean synthesis

- [ ] **Step 5: Run Turborepo full check**

Run: `turbo run test lint --filter=@isol8/backend`
Expected: All pass

- [ ] **Step 6: Final commit if any remaining changes**

```bash
git add -A
git commit -m "chore: final cleanup for RDS to DynamoDB migration"
```
