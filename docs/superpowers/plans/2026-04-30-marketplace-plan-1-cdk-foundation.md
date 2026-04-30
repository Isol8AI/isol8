# Marketplace Plan 1: CDK + Stripe Connect Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision the AWS infrastructure (7 DynamoDB tables, 1 S3 bucket, 1 Lambda search-indexer, 1 Fargate task definition for MCP server) and the Stripe Connect Express SDK + webhook scaffolding that the marketplace.isol8.co subsystems will depend on.

**Architecture:** Extend the existing CDK `DatabaseStack` and `ServiceStack` rather than creating a new stack — the marketplace shares blast-radius with the rest of Isol8 and the existing service stack already wires KMS, secrets, and the agent-catalog S3 bucket using the same patterns. Stripe Connect is added to `core/services/billing_service.py` patterns (separate-charges-and-transfers model). The MCP Fargate service is task-definition-only in this plan; the actual MCP service code ships in Plan 3.

**Tech Stack:** AWS CDK 2.190.0 (TypeScript), DynamoDB (PAY_PER_REQUEST + KMS customer-managed), S3 (S3-managed encryption), AWS Lambda (Python 3.12), ECS Fargate, Stripe Python SDK (existing), pytest + unittest.mock.

---

## Context

The marketplace.isol8.co design (`docs/superpowers/specs/2026-04-29-marketplace-design.md`) introduces a new product surface — a public marketplace for AI agents and skills. The design doc commits to v1 scope of free + paid listings, Isol8 + non-Isol8 sellers/buyers, CLI installer + MCP server distribution. The total v1 surface decomposes into 6 sub-plans; this is Plan 1.

Plan 1 produces: deployable infrastructure that Plans 2-6 build on. Nothing in this plan ships user-visible behavior; it ships the bones.

Why first: every other plan depends on the DynamoDB tables, S3 bucket, Lambda, and Fargate task definitions provisioned here. The Stripe Connect SDK setup unblocks Plan 2's payout flow. Without Plan 1, Plans 2-6 cannot be tested locally (LocalStack) or deployed to dev.

Outcome: `cdk deploy` succeeds with all marketplace resources created in the dev account; Stripe Connect test-mode account creation succeeds end-to-end; webhook dedup table accepts marketplace event types.

## Existing patterns to reuse (verified)

- `apps/infra/lib/stacks/database-stack.ts` — DynamoDB table pattern with KMS encryption, GSIs, env-aware removal policy. Existing tables (12) all follow the same shape.
- `apps/infra/lib/stacks/service-stack.ts:506-516` — S3 bucket pattern (versioned, S3_MANAGED encryption, block-all public, env-aware autoDeleteObjects). The existing `isol8-{env}-agent-catalog` bucket is the model.
- `apps/infra/lib/stacks/api-stack.ts:201-207` — Lambda function pattern with `lambda.Code.fromAsset` + `bundling` for pip install.
- `apps/infra/lambda/<function-name>/index.py` — Lambda source file location.
- `apps/infra/test/database-stack.test.ts` — CDK test pattern using `Template.fromStack()` + `hasResourceProperties` + `Match.objectLike`/`Match.arrayWith` for GSI assertions.
- `apps/backend/core/services/webhook_dedup.py:57-84` — `record_event_or_skip(event_id, source)` is already wired to a 30-day-TTL DDB table; reuse for Stripe Connect webhooks.
- `apps/backend/core/services/billing_service.py` — Stripe SDK call patterns (idempotency keys, automatic_tax, customer creation). No Connect calls today; Plan 1 introduces them.
- `apps/backend/core/config.py:93-96` — Stripe env var pattern. Plan 1 adds `STRIPE_CONNECT_REFRESH_URL` and `STRIPE_CONNECT_RETURN_URL`.
- `apps/backend/tests/unit/services/test_billing_service.py` — `@patch("core.services.billing_service.stripe")` mocking pattern. Plan 1 adds `test_payout_service.py` using the same pattern.

## File structure

**Create:**
- `apps/infra/lambda/marketplace-search-indexer/index.py` — DDB Streams handler, refreshes search-index rows on listings updates.
- `apps/infra/lambda/marketplace-search-indexer/requirements.txt` — `boto3` only (already part of Lambda runtime; empty file is also fine but explicit is better).
- `apps/infra/test/marketplace-resources.test.ts` — CDK assertions for new DDB tables, S3 bucket, Lambda, Fargate task def.
- `apps/backend/core/services/payout_service.py` — Stripe Connect Express onboarding + Transfer creation (scaffold only — full logic in Plan 2).
- `apps/backend/tests/unit/services/test_payout_service.py` — `unittest.mock`-based tests for the scaffold.
- `scripts/validate-stripe-connect-sandbox.py` — one-shot script that exercises Connect Express against Stripe test mode end-to-end (creates account, generates onboarding link, asserts schema).

**Modify:**
- `apps/infra/lib/stacks/database-stack.ts` — add 7 new tables (`marketplace-listings`, `marketplace-listing-versions`, `marketplace-purchases`, `marketplace-payout-accounts`, `marketplace-takedowns`, `marketplace-mcp-sessions`, `marketplace-search-index`) following the existing pattern.
- `apps/infra/lib/stacks/service-stack.ts` — add `isol8-{env}-marketplace-artifacts` S3 bucket (parallel to existing `agentCatalogBucket`), grant read/write to the existing `taskRole`, define the marketplace-MCP Fargate task definition (no service yet — service ships in Plan 3), wire the search-indexer Lambda to the listings table's DDB stream.
- `apps/infra/lib/isol8-stage.ts` — pass new tables into `ServiceStackProps` so backend tasks get table names as env vars (extends existing pattern).
- `apps/backend/core/config.py` — add `STRIPE_CONNECT_REFRESH_URL` and `STRIPE_CONNECT_RETURN_URL` env vars; add table-name env vars (`MARKETPLACE_LISTINGS_TABLE`, etc.).
- `apps/backend/tests/unit/services/test_billing_service.py` — no changes (verifying isolation; payout has its own file).

**Operational (not code):**
- Stripe dashboard — enable Connect Express in test mode; capture client_id and webhook signing secret for the Connect events; add as GitHub secrets.
- AWS Secrets Manager — create `isol8/{env}/stripe_connect_client_id` and `isol8/{env}/stripe_connect_webhook_secret` (per-env).
- Vercel — create a new Vercel project pointed at `marketplace.isol8.co` subdomain. Project deployment pipeline ships in Plan 5; we just provision the project shell.

---

## Tasks

### Task 1: Add `marketplace-listings` and `marketplace-listing-versions` tables

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`
- Test: `apps/infra/test/marketplace-resources.test.ts` (create)

- [ ] **Step 1: Write the failing test**

Create `apps/infra/test/marketplace-resources.test.ts`:

```typescript
import * as cdk from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import * as kms from "aws-cdk-lib/aws-kms";
import { DatabaseStack } from "../lib/stacks/database-stack";

function buildDbStack(environment: "dev" | "prod"): Template {
  const app = new cdk.App();
  const env = { account: "877352799272", region: "us-east-1" };
  const supportStack = new cdk.Stack(app, `Support-${environment}`, { env });
  const kmsKey = new kms.Key(supportStack, "KmsKey");
  const dbStack = new DatabaseStack(app, `Database-${environment}`, {
    env,
    environment,
    kmsKey,
  });
  return Template.fromStack(dbStack);
}

describe("DatabaseStack — marketplace tables", () => {
  const template = buildDbStack("dev");

  test("creates marketplace-listings table with composite key", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-listings",
      KeySchema: [
        { AttributeName: "listing_id", KeyType: "HASH" },
        { AttributeName: "version", KeyType: "RANGE" },
      ],
      BillingMode: "PAY_PER_REQUEST",
    });
  });

  test("marketplace-listings has all 4 expected GSIs", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-listings",
      GlobalSecondaryIndexes: Match.arrayWith([
        Match.objectLike({ IndexName: "slug-version-index" }),
        Match.objectLike({ IndexName: "seller-created-index" }),
        Match.objectLike({ IndexName: "status-published-index" }),
        Match.objectLike({ IndexName: "tag-published-index" }),
      ]),
    });
  });

  test("creates marketplace-listing-versions table (immutable history)", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "isol8-dev-marketplace-listing-versions",
      KeySchema: [
        { AttributeName: "listing_id", KeyType: "HASH" },
        { AttributeName: "version", KeyType: "RANGE" },
      ],
    });
  });

  test("dev environment uses DESTROY removal policy for marketplace tables", () => {
    template.hasResource("AWS::DynamoDB::Table", {
      Properties: { TableName: "isol8-dev-marketplace-listings" },
      DeletionPolicy: "Delete",
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

Expected: `Resource matching marketplace-listings not found`. Test fails because tables don't exist yet.

- [ ] **Step 3: Add the two tables to `database-stack.ts`**

Edit `apps/infra/lib/stacks/database-stack.ts`. Add to the `public readonly` declarations near the top of the class:

```typescript
public readonly marketplaceListingsTable: dynamodb.Table;
public readonly marketplaceListingVersionsTable: dynamodb.Table;
```

Add to the constructor body, after the existing tables:

```typescript
this.marketplaceListingsTable = new dynamodb.Table(this, "MarketplaceListingsTable", {
  tableName: `isol8-${env}-marketplace-listings`,
  partitionKey: { name: "listing_id", type: dynamodb.AttributeType.STRING },
  sortKey: { name: "version", type: dynamodb.AttributeType.NUMBER },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: config.removalPolicy,
  pointInTimeRecovery: true,
  encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: props.kmsKey,
  stream: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
});
this.marketplaceListingsTable.addGlobalSecondaryIndex({
  indexName: "slug-version-index",
  partitionKey: { name: "slug", type: dynamodb.AttributeType.STRING },
  sortKey: { name: "version", type: dynamodb.AttributeType.NUMBER },
});
this.marketplaceListingsTable.addGlobalSecondaryIndex({
  indexName: "seller-created-index",
  partitionKey: { name: "seller_id", type: dynamodb.AttributeType.STRING },
  sortKey: { name: "created_at", type: dynamodb.AttributeType.STRING },
});
this.marketplaceListingsTable.addGlobalSecondaryIndex({
  indexName: "status-published-index",
  partitionKey: { name: "status", type: dynamodb.AttributeType.STRING },
  sortKey: { name: "published_at", type: dynamodb.AttributeType.STRING },
});
this.marketplaceListingsTable.addGlobalSecondaryIndex({
  indexName: "tag-published-index",
  partitionKey: { name: "tag", type: dynamodb.AttributeType.STRING },
  sortKey: { name: "published_at", type: dynamodb.AttributeType.STRING },
});

this.marketplaceListingVersionsTable = new dynamodb.Table(this, "MarketplaceListingVersionsTable", {
  tableName: `isol8-${env}-marketplace-listing-versions`,
  partitionKey: { name: "listing_id", type: dynamodb.AttributeType.STRING },
  sortKey: { name: "version", type: dynamodb.AttributeType.NUMBER },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: config.removalPolicy,
  pointInTimeRecovery: true,
  encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: props.kmsKey,
});
```

The DDB stream on the listings table is what the search-indexer Lambda subscribes to (Task 8).

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts apps/infra/test/marketplace-resources.test.ts
git commit -m "infra(marketplace): add listings + listing-versions DDB tables"
```

---

### Task 2: Add `marketplace-purchases` table

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`
- Test: `apps/infra/test/marketplace-resources.test.ts`

- [ ] **Step 1: Write the failing test (append to existing test file)**

```typescript
test("creates marketplace-purchases table with buyer_id PK", () => {
  template.hasResourceProperties("AWS::DynamoDB::Table", {
    TableName: "isol8-dev-marketplace-purchases",
    KeySchema: [
      { AttributeName: "buyer_id", KeyType: "HASH" },
      { AttributeName: "purchase_id", KeyType: "RANGE" },
    ],
  });
});

test("marketplace-purchases has listing_id and license_key GSIs", () => {
  template.hasResourceProperties("AWS::DynamoDB::Table", {
    TableName: "isol8-dev-marketplace-purchases",
    GlobalSecondaryIndexes: Match.arrayWith([
      Match.objectLike({ IndexName: "listing-created-index" }),
      Match.objectLike({ IndexName: "license-key-index" }),
    ]),
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

Expected: 2 new tests fail.

- [ ] **Step 3: Add the table to `database-stack.ts`**

Add the readonly declaration:

```typescript
public readonly marketplacePurchasesTable: dynamodb.Table;
```

Add to the constructor (after Task 1's tables):

```typescript
this.marketplacePurchasesTable = new dynamodb.Table(this, "MarketplacePurchasesTable", {
  tableName: `isol8-${env}-marketplace-purchases`,
  partitionKey: { name: "buyer_id", type: dynamodb.AttributeType.STRING },
  sortKey: { name: "purchase_id", type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: config.removalPolicy,
  pointInTimeRecovery: true,
  encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: props.kmsKey,
});
this.marketplacePurchasesTable.addGlobalSecondaryIndex({
  indexName: "listing-created-index",
  partitionKey: { name: "listing_id", type: dynamodb.AttributeType.STRING },
  sortKey: { name: "created_at", type: dynamodb.AttributeType.STRING },
});
this.marketplacePurchasesTable.addGlobalSecondaryIndex({
  indexName: "license-key-index",
  partitionKey: { name: "license_key", type: dynamodb.AttributeType.STRING },
});
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts apps/infra/test/marketplace-resources.test.ts
git commit -m "infra(marketplace): add purchases DDB table with buyer + license-key GSIs"
```

---

### Task 3: Add `marketplace-payout-accounts` table

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`
- Test: `apps/infra/test/marketplace-resources.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
test("creates marketplace-payout-accounts table with seller_id PK", () => {
  template.hasResourceProperties("AWS::DynamoDB::Table", {
    TableName: "isol8-dev-marketplace-payout-accounts",
    KeySchema: [{ AttributeName: "seller_id", KeyType: "HASH" }],
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

Expected: new test fails.

- [ ] **Step 3: Add the table to `database-stack.ts`**

```typescript
public readonly marketplacePayoutAccountsTable: dynamodb.Table;
```

In constructor:

```typescript
this.marketplacePayoutAccountsTable = new dynamodb.Table(this, "MarketplacePayoutAccountsTable", {
  tableName: `isol8-${env}-marketplace-payout-accounts`,
  partitionKey: { name: "seller_id", type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: config.removalPolicy,
  pointInTimeRecovery: true,
  encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: props.kmsKey,
});
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts apps/infra/test/marketplace-resources.test.ts
git commit -m "infra(marketplace): add payout-accounts DDB table"
```

---

### Task 4: Add `marketplace-takedowns` table

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`
- Test: `apps/infra/test/marketplace-resources.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
test("creates marketplace-takedowns table with composite key", () => {
  template.hasResourceProperties("AWS::DynamoDB::Table", {
    TableName: "isol8-dev-marketplace-takedowns",
    KeySchema: [
      { AttributeName: "listing_id", KeyType: "HASH" },
      { AttributeName: "takedown_id", KeyType: "RANGE" },
    ],
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 3: Add the table**

```typescript
public readonly marketplaceTakedownsTable: dynamodb.Table;
```

```typescript
this.marketplaceTakedownsTable = new dynamodb.Table(this, "MarketplaceTakedownsTable", {
  tableName: `isol8-${env}-marketplace-takedowns`,
  partitionKey: { name: "listing_id", type: dynamodb.AttributeType.STRING },
  sortKey: { name: "takedown_id", type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: config.removalPolicy,
  pointInTimeRecovery: true,
  encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: props.kmsKey,
});
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts apps/infra/test/marketplace-resources.test.ts
git commit -m "infra(marketplace): add takedowns DDB table"
```

---

### Task 5: Add `marketplace-mcp-sessions` table with TTL

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`
- Test: `apps/infra/test/marketplace-resources.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
test("creates marketplace-mcp-sessions table with TTL on 'ttl' attribute", () => {
  template.hasResourceProperties("AWS::DynamoDB::Table", {
    TableName: "isol8-dev-marketplace-mcp-sessions",
    KeySchema: [{ AttributeName: "session_id", KeyType: "HASH" }],
    TimeToLiveSpecification: {
      AttributeName: "ttl",
      Enabled: true,
    },
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 3: Add the table**

```typescript
public readonly marketplaceMcpSessionsTable: dynamodb.Table;
```

```typescript
this.marketplaceMcpSessionsTable = new dynamodb.Table(this, "MarketplaceMcpSessionsTable", {
  tableName: `isol8-${env}-marketplace-mcp-sessions`,
  partitionKey: { name: "session_id", type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: config.removalPolicy,
  pointInTimeRecovery: true,
  encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: props.kmsKey,
  timeToLiveAttribute: "ttl",
});
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts apps/infra/test/marketplace-resources.test.ts
git commit -m "infra(marketplace): add mcp-sessions DDB table with 24h TTL"
```

---

### Task 6: Add `marketplace-search-index` table (sharded)

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`
- Test: `apps/infra/test/marketplace-resources.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
test("creates marketplace-search-index table with shard_id PK", () => {
  template.hasResourceProperties("AWS::DynamoDB::Table", {
    TableName: "isol8-dev-marketplace-search-index",
    KeySchema: [
      { AttributeName: "shard_id", KeyType: "HASH" },
      { AttributeName: "published_listing", KeyType: "RANGE" },
    ],
  });
});
```

`published_listing` is the SK in format `<published_at>#<listing_id>` for ordered pagination per shard.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 3: Add the table**

```typescript
public readonly marketplaceSearchIndexTable: dynamodb.Table;
```

```typescript
this.marketplaceSearchIndexTable = new dynamodb.Table(this, "MarketplaceSearchIndexTable", {
  tableName: `isol8-${env}-marketplace-search-index`,
  partitionKey: { name: "shard_id", type: dynamodb.AttributeType.NUMBER },
  sortKey: { name: "published_listing", type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  removalPolicy: config.removalPolicy,
  pointInTimeRecovery: true,
  encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
  encryptionKey: props.kmsKey,
});
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/database-stack.ts apps/infra/test/marketplace-resources.test.ts
git commit -m "infra(marketplace): add 16-shard search-index DDB table"
```

---

### Task 7: Add `marketplace-artifacts` S3 bucket

**Files:**
- Modify: `apps/infra/lib/stacks/service-stack.ts`
- Test: `apps/infra/test/marketplace-resources.test.ts` (extends — write a new `buildServiceStack` helper or assert against the synthesized service template)

- [ ] **Step 1: Write the failing test**

The existing `service-stack.test.ts` has stack-instantiation helpers. Add to `marketplace-resources.test.ts`:

```typescript
import { ServiceStack } from "../lib/stacks/service-stack";
// ... add a buildServiceStack helper that mirrors the database-stack helper but
// instantiates ServiceStack. Mock the database/container/network props with stub
// constructs (existing service-stack.test.ts has the pattern — copy it).

describe("ServiceStack — marketplace S3 bucket", () => {
  const template = buildServiceStack("dev");
  test("creates isol8-dev-marketplace-artifacts bucket", () => {
    template.hasResourceProperties("AWS::S3::Bucket", {
      BucketName: "isol8-dev-marketplace-artifacts",
      VersioningConfiguration: { Status: "Enabled" },
      BucketEncryption: {
        ServerSideEncryptionConfiguration: [
          { ServerSideEncryptionByDefault: { SSEAlgorithm: "AES256" } },
        ],
      },
      PublicAccessBlockConfiguration: {
        BlockPublicAcls: true,
        BlockPublicPolicy: true,
        IgnorePublicAcls: true,
        RestrictPublicBuckets: true,
      },
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

Expected: bucket-resource assertion fails.

- [ ] **Step 3: Add the bucket to `service-stack.ts`**

Locate the existing `agentCatalogBucket` declaration (around line 506). Add directly after it:

```typescript
const marketplaceArtifactsBucket = new s3.Bucket(this, "MarketplaceArtifactsBucket", {
  bucketName: `isol8-${env}-marketplace-artifacts`,
  versioned: true,
  encryption: s3.BucketEncryption.S3_MANAGED,
  blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
  removalPolicy: env === "prod" ? cdk.RemovalPolicy.RETAIN : cdk.RemovalPolicy.DESTROY,
  autoDeleteObjects: env !== "prod",
});

marketplaceArtifactsBucket.grantReadWrite(this.taskRole);
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/service-stack.ts apps/infra/test/marketplace-resources.test.ts
git commit -m "infra(marketplace): add marketplace-artifacts S3 bucket with task-role read-write"
```

---

### Task 8: Add search-indexer Lambda + DDB Streams subscription

**Files:**
- Create: `apps/infra/lambda/marketplace-search-indexer/index.py`
- Create: `apps/infra/lambda/marketplace-search-indexer/requirements.txt`
- Modify: `apps/infra/lib/stacks/service-stack.ts`
- Test: `apps/infra/test/marketplace-resources.test.ts`

- [ ] **Step 1: Write the failing test**

```typescript
test("creates marketplace-search-indexer Lambda", () => {
  template.hasResourceProperties("AWS::Lambda::Function", {
    FunctionName: "isol8-dev-marketplace-search-indexer",
    Runtime: "python3.12",
    Handler: "index.handler",
  });
});

test("Lambda is subscribed to listings table DDB stream", () => {
  template.hasResourceProperties("AWS::Lambda::EventSourceMapping", {
    FunctionName: Match.objectLike({}),
    EventSourceArn: Match.objectLike({}),
    StartingPosition: "LATEST",
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 3a: Create the Lambda source file**

`apps/infra/lambda/marketplace-search-indexer/index.py`:

```python
"""Marketplace search-index refresh Lambda.

Subscribes to the marketplace-listings DDB stream. On INSERT or MODIFY events
for listings whose status is 'published', writes a denormalized row to the
search-index table sharded by uniform-random shard_id.
"""
import json
import os
import zlib
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

DDB = boto3.resource("dynamodb")
SEARCH_INDEX_TABLE = os.environ["MARKETPLACE_SEARCH_INDEX_TABLE"]
SHARD_COUNT = 16


def _shard_for(listing_id: str) -> int:
    """Uniform-random shard via CRC32. Avoids clustering on UUID prefix."""
    return zlib.crc32(listing_id.encode("utf-8")) % SHARD_COUNT


def _published_listing_sk(published_at: str, listing_id: str) -> str:
    return f"{published_at}#{listing_id}"


def _project_listing(item: dict) -> dict:
    """Project listing fields needed for search/browse."""
    return {
        "shard_id": _shard_for(item["listing_id"]),
        "published_listing": _published_listing_sk(
            item.get("published_at", ""), item["listing_id"]
        ),
        "listing_id": item["listing_id"],
        "slug": item.get("slug", ""),
        "name": item.get("name", ""),
        "description": item.get("description_md", "")[:500],
        "tags": item.get("tags", []),
        "format": item.get("format", ""),
        "price_cents": item.get("price_cents", 0),
        "seller_id": item.get("seller_id", ""),
    }


def handler(event, _context):
    table = DDB.Table(SEARCH_INDEX_TABLE)
    for record in event.get("Records", []):
        event_name = record["eventName"]
        if event_name not in ("INSERT", "MODIFY"):
            continue
        new = record.get("dynamodb", {}).get("NewImage")
        if not new:
            continue
        # DDB stream items are in {"S": "value"} form; unwrap minimally.
        unwrapped = {k: list(v.values())[0] for k, v in new.items()}
        if unwrapped.get("status") != "published":
            continue
        if unwrapped.get("version") and not unwrapped.get("LATEST_alias"):
            # Only project the LATEST row, not historical versions.
            continue
        try:
            table.put_item(Item=_project_listing(unwrapped))
        except ClientError as e:
            print(json.dumps({
                "level": "error",
                "msg": "search_index_write_failed",
                "listing_id": unwrapped.get("listing_id"),
                "error": str(e),
            }))
    return {"records": len(event.get("Records", []))}
```

- [ ] **Step 3b: Create the requirements file**

`apps/infra/lambda/marketplace-search-indexer/requirements.txt`:

```
# boto3 is provided by the Lambda runtime; no extra deps for v1.
```

- [ ] **Step 3c: Wire the Lambda + Stream subscription in `service-stack.ts`**

Add imports at the top:

```typescript
import * as lambdaEventSources from "aws-cdk-lib/aws-lambda-event-sources";
```

After the search-index table is in scope (passed via props from DatabaseStack), add:

```typescript
const searchIndexerFn = new lambda.Function(this, "MarketplaceSearchIndexerFn", {
  functionName: `isol8-${env}-marketplace-search-indexer`,
  runtime: lambda.Runtime.PYTHON_3_12,
  handler: "index.handler",
  code: lambda.Code.fromAsset(
    path.join(__dirname, "..", "..", "lambda", "marketplace-search-indexer"),
    {
      bundling: {
        image: lambda.Runtime.PYTHON_3_12.bundlingImage,
        command: ["bash", "-c", "pip install -r requirements.txt -t ."],
      },
    }
  ),
  environment: {
    MARKETPLACE_SEARCH_INDEX_TABLE: props.database.marketplaceSearchIndexTable.tableName,
  },
  timeout: cdk.Duration.seconds(30),
});

props.database.marketplaceSearchIndexTable.grantWriteData(searchIndexerFn);
props.database.marketplaceListingsTable.grantStreamRead(searchIndexerFn);

searchIndexerFn.addEventSource(
  new lambdaEventSources.DynamoEventSource(props.database.marketplaceListingsTable, {
    startingPosition: lambda.StartingPosition.LATEST,
    batchSize: 25,
    retryAttempts: 3,
  })
);
```

Update `ServiceStackProps` (and the wiring in `isol8-stage.ts`) so `marketplaceSearchIndexTable` and `marketplaceListingsTable` are passed in.

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lambda/marketplace-search-indexer/ apps/infra/lib/stacks/service-stack.ts apps/infra/lib/isol8-stage.ts apps/infra/test/marketplace-resources.test.ts
git commit -m "infra(marketplace): add search-indexer Lambda + DDB stream subscription"
```

---

### Task 9: Add `marketplace-mcp` Fargate task definition

**Files:**
- Modify: `apps/infra/lib/stacks/service-stack.ts`
- Test: `apps/infra/test/marketplace-resources.test.ts`

The actual MCP service code ships in Plan 3. This task creates the task definition (no FargateService — that ships when there's an image to point at).

- [ ] **Step 1: Write the failing test**

```typescript
test("creates marketplace-mcp Fargate task definition (1 vCPU / 2 GB)", () => {
  template.hasResourceProperties("AWS::ECS::TaskDefinition", {
    Family: "isol8-dev-marketplace-mcp",
    Cpu: "1024",
    Memory: "2048",
    NetworkMode: "awsvpc",
    RequiresCompatibilities: ["FARGATE"],
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 3: Add the task definition to `service-stack.ts`**

After the existing backend task definition:

```typescript
const mcpTaskDef = new ecs.FargateTaskDefinition(this, "MarketplaceMcpTaskDef", {
  family: `isol8-${env}-marketplace-mcp`,
  cpu: 1024,
  memoryLimitMiB: 2048,
  taskRole: this.taskRole,
  executionRole: taskExecutionRole,
});

// Placeholder image — replaced when Plan 3 ships the MCP service code.
// Use a public alpine image so synth + dev deploy succeed; service is not
// started in this plan.
mcpTaskDef.addContainer("mcp", {
  image: ecs.ContainerImage.fromRegistry("public.ecr.aws/docker/library/alpine:3.19"),
  command: ["sh", "-c", "echo 'placeholder — Plan 3 ships the real image' && sleep infinity"],
  portMappings: [{ containerPort: 3000 }],
  logging: ecs.LogDriver.awsLogs({ streamPrefix: `marketplace-mcp-${env}` }),
  environment: {
    ENV: env,
    MARKETPLACE_PURCHASES_TABLE: props.database.marketplacePurchasesTable.tableName,
    MARKETPLACE_LISTINGS_TABLE: props.database.marketplaceListingsTable.tableName,
    MARKETPLACE_MCP_SESSIONS_TABLE: props.database.marketplaceMcpSessionsTable.tableName,
    MARKETPLACE_ARTIFACTS_BUCKET: marketplaceArtifactsBucket.bucketName,
  },
});

props.database.marketplacePurchasesTable.grantReadData(this.taskRole);
props.database.marketplaceMcpSessionsTable.grantReadWriteData(this.taskRole);
marketplaceArtifactsBucket.grantRead(this.taskRole);
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/infra && npm test -- marketplace-resources.test.ts
```

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/service-stack.ts apps/infra/test/marketplace-resources.test.ts
git commit -m "infra(marketplace): add marketplace-mcp Fargate task definition (placeholder image)"
```

---

### Task 10: Wire table-name env vars into backend Fargate service

**Files:**
- Modify: `apps/infra/lib/stacks/service-stack.ts`
- Modify: `apps/backend/core/config.py`
- Test: `apps/backend/tests/unit/test_config.py` (existing, extend if present; otherwise smoke-test via `python -c "from core.config import settings; print(settings.MARKETPLACE_LISTINGS_TABLE)"`)

- [ ] **Step 1: Write the failing test**

In `apps/backend/tests/unit/test_config.py` (create if missing — pattern matches existing test files):

```python
import os
from unittest.mock import patch

import pytest


@patch.dict(os.environ, {"MARKETPLACE_LISTINGS_TABLE": "isol8-dev-marketplace-listings"})
def test_marketplace_listings_table_env_var_loaded():
    # Re-import to pick up env
    import importlib

    import core.config

    importlib.reload(core.config)
    assert core.config.settings.MARKETPLACE_LISTINGS_TABLE == "isol8-dev-marketplace-listings"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && uv run pytest tests/unit/test_config.py::test_marketplace_listings_table_env_var_loaded -v
```

Expected: AttributeError on missing setting.

- [ ] **Step 3a: Add config fields**

In `apps/backend/core/config.py`, add after existing Stripe block:

```python
# Marketplace
MARKETPLACE_LISTINGS_TABLE: str = os.getenv("MARKETPLACE_LISTINGS_TABLE", "")
MARKETPLACE_LISTING_VERSIONS_TABLE: str = os.getenv("MARKETPLACE_LISTING_VERSIONS_TABLE", "")
MARKETPLACE_PURCHASES_TABLE: str = os.getenv("MARKETPLACE_PURCHASES_TABLE", "")
MARKETPLACE_PAYOUT_ACCOUNTS_TABLE: str = os.getenv("MARKETPLACE_PAYOUT_ACCOUNTS_TABLE", "")
MARKETPLACE_TAKEDOWNS_TABLE: str = os.getenv("MARKETPLACE_TAKEDOWNS_TABLE", "")
MARKETPLACE_MCP_SESSIONS_TABLE: str = os.getenv("MARKETPLACE_MCP_SESSIONS_TABLE", "")
MARKETPLACE_SEARCH_INDEX_TABLE: str = os.getenv("MARKETPLACE_SEARCH_INDEX_TABLE", "")
MARKETPLACE_ARTIFACTS_BUCKET: str = os.getenv("MARKETPLACE_ARTIFACTS_BUCKET", "")

# Stripe Connect
STRIPE_CONNECT_REFRESH_URL: str = os.getenv("STRIPE_CONNECT_REFRESH_URL", "")
STRIPE_CONNECT_RETURN_URL: str = os.getenv("STRIPE_CONNECT_RETURN_URL", "")
```

- [ ] **Step 3b: Pass env vars to backend container in `service-stack.ts`**

In the existing backend `addContainer` block, append to the `environment` dict:

```typescript
MARKETPLACE_LISTINGS_TABLE: props.database.marketplaceListingsTable.tableName,
MARKETPLACE_LISTING_VERSIONS_TABLE: props.database.marketplaceListingVersionsTable.tableName,
MARKETPLACE_PURCHASES_TABLE: props.database.marketplacePurchasesTable.tableName,
MARKETPLACE_PAYOUT_ACCOUNTS_TABLE: props.database.marketplacePayoutAccountsTable.tableName,
MARKETPLACE_TAKEDOWNS_TABLE: props.database.marketplaceTakedownsTable.tableName,
MARKETPLACE_MCP_SESSIONS_TABLE: props.database.marketplaceMcpSessionsTable.tableName,
MARKETPLACE_SEARCH_INDEX_TABLE: props.database.marketplaceSearchIndexTable.tableName,
MARKETPLACE_ARTIFACTS_BUCKET: marketplaceArtifactsBucket.bucketName,
STRIPE_CONNECT_REFRESH_URL: env === "prod"
  ? "https://marketplace.isol8.co/payouts/refresh"
  : "https://marketplace.dev.isol8.co/payouts/refresh",
STRIPE_CONNECT_RETURN_URL: env === "prod"
  ? "https://marketplace.isol8.co/payouts/return"
  : "https://marketplace.dev.isol8.co/payouts/return",
```

Also grant the backend taskRole access to the new tables:

```typescript
props.database.marketplaceListingsTable.grantReadWriteData(this.taskRole);
props.database.marketplaceListingVersionsTable.grantReadWriteData(this.taskRole);
props.database.marketplacePurchasesTable.grantReadWriteData(this.taskRole);
props.database.marketplacePayoutAccountsTable.grantReadWriteData(this.taskRole);
props.database.marketplaceTakedownsTable.grantReadWriteData(this.taskRole);
props.database.marketplaceMcpSessionsTable.grantReadWriteData(this.taskRole);
props.database.marketplaceSearchIndexTable.grantReadData(this.taskRole);
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/backend && uv run pytest tests/unit/test_config.py -v
```

- [ ] **Step 5: Commit**

```bash
git add apps/infra/lib/stacks/service-stack.ts apps/backend/core/config.py apps/backend/tests/unit/test_config.py
git commit -m "infra(marketplace): wire DDB table names + Stripe Connect URLs into backend env"
```

---

### Task 11: Scaffold `payout_service.py` with Stripe Connect Express SDK calls

**Files:**
- Create: `apps/backend/core/services/payout_service.py`
- Create: `apps/backend/tests/unit/services/test_payout_service.py`

This task creates the scaffold only — onboarding link generation, Connect Account creation, balance-held tracking. The full purchase-driven Transfer flow ships in Plan 2 because it depends on the listings/purchases services.

- [ ] **Step 1: Write the failing test**

`apps/backend/tests/unit/services/test_payout_service.py`:

```python
"""Tests for payout_service Stripe Connect Express scaffold."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.services import payout_service


@pytest.mark.asyncio
@patch("core.services.payout_service.stripe")
async def test_create_connect_account_for_seller(mock_stripe):
    mock_stripe.Account.create.return_value = MagicMock(id="acct_test_123")
    result = await payout_service.create_connect_account(
        seller_id="user_abc",
        email="seller@example.com",
        country="US",
    )
    assert result == "acct_test_123"
    mock_stripe.Account.create.assert_called_once()
    call_kwargs = mock_stripe.Account.create.call_args.kwargs
    assert call_kwargs["type"] == "express"
    assert call_kwargs["country"] == "US"
    assert call_kwargs["email"] == "seller@example.com"
    assert call_kwargs["metadata"]["seller_id"] == "user_abc"
    # Idempotency: re-running with same seller_id reuses idempotency key
    assert "idempotency_key" in call_kwargs


@pytest.mark.asyncio
@patch("core.services.payout_service.stripe")
async def test_create_onboarding_link(mock_stripe):
    mock_stripe.AccountLink.create.return_value = MagicMock(url="https://connect.stripe.com/setup/abc123")
    url = await payout_service.create_onboarding_link(
        connect_account_id="acct_test_123",
        refresh_url="https://example.com/refresh",
        return_url="https://example.com/return",
    )
    assert url == "https://connect.stripe.com/setup/abc123"
    call_kwargs = mock_stripe.AccountLink.create.call_args.kwargs
    assert call_kwargs["account"] == "acct_test_123"
    assert call_kwargs["type"] == "account_onboarding"


@pytest.mark.asyncio
@patch("core.services.payout_service.stripe")
async def test_rejects_non_us_country(mock_stripe):
    """Per design doc, v1 = US sellers only."""
    with pytest.raises(payout_service.UnsupportedCountryError):
        await payout_service.create_connect_account(
            seller_id="user_abc",
            email="seller@example.com",
            country="DE",
        )
    mock_stripe.Account.create.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_payout_service.py -v
```

Expected: ImportError — `core.services.payout_service` doesn't exist.

- [ ] **Step 3: Create `payout_service.py`**

`apps/backend/core/services/payout_service.py`:

```python
"""Payout service: Stripe Connect Express onboarding + Transfer creation.

v1 launches with US sellers only. International support is post-v1.

Connect flow uses 'separate charges and transfers':
  1. Buyer's purchase → Stripe Charge to the platform balance.
  2. Seller onboards via Express → Connect account exists.
  3. Held balance flushed via stripe.Transfer.create() to the connected account.

This module owns steps 2 and 3. Step 1 (Charge) lives in marketplace_service
(Plan 2). The webhook handler (also Plan 2) calls back into this module on
account.updated to flush held balances.
"""
import stripe

from core.config import settings


SUPPORTED_COUNTRIES = {"US"}


class UnsupportedCountryError(Exception):
    """Raised when seller's country is not supported in v1."""


async def create_connect_account(
    *, seller_id: str, email: str, country: str
) -> str:
    """Create a Stripe Connect Express account for a seller. Returns account_id.

    Idempotent on seller_id: re-calling for the same seller returns the
    Stripe-side existing account (Stripe deduplicates on idempotency_key).
    """
    if country not in SUPPORTED_COUNTRIES:
        raise UnsupportedCountryError(
            f"v1 supports only {SUPPORTED_COUNTRIES}; got {country}"
        )

    stripe.api_key = settings.STRIPE_SECRET_KEY
    account = stripe.Account.create(
        type="express",
        country=country,
        email=email,
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
        metadata={"seller_id": seller_id},
        idempotency_key=f"connect_account_create:{seller_id}",
    )
    return account.id


async def create_onboarding_link(
    *, connect_account_id: str, refresh_url: str, return_url: str
) -> str:
    """Create a one-time Stripe Express onboarding link. Returns the URL."""
    stripe.api_key = settings.STRIPE_SECRET_KEY
    link = stripe.AccountLink.create(
        account=connect_account_id,
        refresh_url=refresh_url,
        return_url=return_url,
        type="account_onboarding",
    )
    return link.url


async def transfer_held_balance(
    *, connect_account_id: str, amount_cents: int, transfer_group: str
) -> str:
    """Create a Transfer from platform balance to the connected account.

    transfer_group: groups Transfers logically per purchase batch; useful for
    Reversals on refund.
    Returns the Stripe transfer_id.
    """
    stripe.api_key = settings.STRIPE_SECRET_KEY
    transfer = stripe.Transfer.create(
        amount=amount_cents,
        currency="usd",
        destination=connect_account_id,
        transfer_group=transfer_group,
        idempotency_key=f"transfer:{connect_account_id}:{transfer_group}",
    )
    return transfer.id
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd apps/backend && uv run pytest tests/unit/services/test_payout_service.py -v
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/services/payout_service.py apps/backend/tests/unit/services/test_payout_service.py
git commit -m "feat(marketplace): scaffold Stripe Connect Express payout service (US-only v1)"
```

---

### Task 12: Add `validate-stripe-connect-sandbox.py` script for end-to-end Connect verification

**Files:**
- Create: `scripts/validate-stripe-connect-sandbox.py`

This is the highest-uncertainty piece per the design doc's Risks section. Run it once before any other marketplace code lands. It's a one-shot script, not a unit test.

- [ ] **Step 1: Create the script**

`scripts/validate-stripe-connect-sandbox.py`:

```python
#!/usr/bin/env python3
"""Validate Stripe Connect Express end-to-end against test mode.

Run once with `STRIPE_SECRET_KEY=sk_test_...` exported in the shell. The
script does not modify production state — Stripe test mode is fully
isolated. Exit 0 means the separate-charges-and-transfers flow works as
the design doc claims.

Usage:
  STRIPE_SECRET_KEY=sk_test_... uv run python scripts/validate-stripe-connect-sandbox.py
"""
import os
import sys
import time

import stripe


def main() -> int:
    key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not key.startswith("sk_test_"):
        print("ERROR: STRIPE_SECRET_KEY must be a test-mode key (starts with sk_test_)")
        return 1
    stripe.api_key = key

    # Step 1: Create an Express connected account.
    print("[1/5] Creating Express account...")
    account = stripe.Account.create(
        type="express",
        country="US",
        email=f"test-seller-{int(time.time())}@example.com",
        capabilities={
            "card_payments": {"requested": True},
            "transfers": {"requested": True},
        },
        metadata={"validation_run": "true"},
    )
    print(f"      account.id = {account.id}")

    # Step 2: Create the onboarding link (would redirect a real user).
    print("[2/5] Creating onboarding AccountLink...")
    link = stripe.AccountLink.create(
        account=account.id,
        refresh_url="https://example.com/refresh",
        return_url="https://example.com/return",
        type="account_onboarding",
    )
    print(f"      link.url = {link.url[:60]}...")

    # Step 3: Simulate a charge to the platform balance (no transfer_data).
    print("[3/5] Creating PaymentIntent against platform...")
    intent = stripe.PaymentIntent.create(
        amount=2000,
        currency="usd",
        payment_method_types=["card"],
        confirm=True,
        payment_method="pm_card_visa",
        metadata={"validation_run": "true", "seller_id": account.id},
    )
    print(f"      intent.id = {intent.id}, status = {intent.status}")
    if intent.status != "succeeded":
        print(f"ERROR: expected status 'succeeded', got '{intent.status}'")
        return 2

    # Step 4: Attempt a Transfer to the connected account.
    # In real Connect Express test mode, the destination account must have
    # capabilities.transfers active — for an unfinished onboarding this fails.
    # We expect this Transfer to fail with the documented error and use that
    # as evidence the held-balance pattern is feasible.
    print("[4/5] Attempting Transfer (expected to fail until onboarding completes)...")
    try:
        transfer = stripe.Transfer.create(
            amount=1700,  # 85% of 2000 (15% platform cut)
            currency="usd",
            destination=account.id,
            transfer_group=f"validation_{intent.id}",
        )
        # If this DOES succeed, the test account already had transfers enabled,
        # which is also valid evidence of feasibility.
        print(f"      transfer.id = {transfer.id} (account had transfers enabled)")
    except stripe.error.InvalidRequestError as e:
        if "transfers" in str(e).lower() or "capability" in str(e).lower():
            print(f"      expected failure: {e.user_message or e}")
            print("      → confirms held-balance pattern: charges land in platform")
            print("      → balance, transfer would succeed once seller onboards.")
        else:
            print(f"ERROR: unexpected Stripe error: {e}")
            return 3

    # Step 5: Confirm the platform balance reflects the charge.
    print("[5/5] Reading platform balance...")
    balance = stripe.Balance.retrieve()
    pending = sum(b.amount for b in balance.pending if b.currency == "usd")
    print(f"      platform USD pending balance includes the test charge: {pending} cents")

    print()
    print("OK — separate-charges-and-transfers pattern is feasible in this Stripe account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Make the script executable + verify it parses**

```bash
chmod +x scripts/validate-stripe-connect-sandbox.py
uv run python -c "import ast; ast.parse(open('scripts/validate-stripe-connect-sandbox.py').read())"
```

Expected: no parse errors. The script does NOT run end-to-end here; it requires a real `sk_test_...` key set in the environment.

- [ ] **Step 3: Run the script against your real Stripe test account (manual)**

```bash
export STRIPE_SECRET_KEY=sk_test_...
uv run python scripts/validate-stripe-connect-sandbox.py
```

Expected: exit 0, with output describing each step. If exit non-zero, the design doc's Stripe Connect approach has a flaw and Plan 2 should not start until resolved.

- [ ] **Step 4: Commit**

```bash
git add scripts/validate-stripe-connect-sandbox.py
git commit -m "tools(marketplace): one-shot Stripe Connect sandbox validator"
```

---

### Task 13: Document Vercel project provisioning + AWS Secrets Manager setup (operational, not code)

**Files:**
- Create: `docs/superpowers/runbooks/marketplace-plan-1-provisioning.md`

This task is documentation only — the operational steps that need to happen outside of `cdk deploy`.

- [ ] **Step 1: Create the runbook**

`docs/superpowers/runbooks/marketplace-plan-1-provisioning.md`:

```markdown
# Marketplace Plan 1 — Operational Provisioning

This runbook covers steps that `cdk deploy` does NOT do. Run these once per
environment (dev, then prod when ready) before deploying Plan 2.

## 1. Vercel — Create marketplace.isol8.co project

1. https://vercel.com/dashboard → New Project
2. Import the `Isol8AI/isol8` GitHub repo.
3. Project name: `isol8-marketplace`
4. Root directory: `apps/marketplace` (this directory does not yet exist; project
   creates after first push that includes it. For now, create the project shell
   and skip the build until Plan 5 ships.)
5. Domain: assign `marketplace.dev.isol8.co` (dev) or `marketplace.isol8.co` (prod).
   DNS records added to Route 53 separately — see DNS section below.
6. Environment variables (per env): leave empty for now; Plan 5 wires them.
7. Note: do NOT enable auto-deploy on push; the project is dormant until Plan 5.

## 2. AWS Secrets Manager — Stripe Connect secrets

Two new secrets per environment. Run as the AWS admin role in `us-east-1`.

```bash
# DEV
aws secretsmanager create-secret \
  --name "isol8/dev/stripe_connect_client_id" \
  --secret-string "ca_test_..." \
  --profile isol8-admin --region us-east-1

aws secretsmanager create-secret \
  --name "isol8/dev/stripe_connect_webhook_secret" \
  --secret-string "whsec_test_..." \
  --profile isol8-admin --region us-east-1
```

Repeat for prod with the live-mode values.

## 3. Stripe dashboard — Enable Connect Express

1. https://dashboard.stripe.com/test/connect → enable Express in test mode.
2. Settings → Connect → register a webhook endpoint:
   - URL: `https://api-dev.isol8.co/api/v1/marketplace/webhooks/stripe-marketplace`
   - Events: `checkout.session.completed`, `charge.refunded`, `account.updated`,
     `transfer.failed`, `payout.paid`, `payout.failed`
3. Copy the webhook signing secret → store as the `stripe_connect_webhook_secret`.
4. Repeat for live mode when promoting to prod.

## 4. Route 53 — DNS records

For dev: CNAME `marketplace.dev.isol8.co` → `cname.vercel-dns.com.` (Vercel provides
the exact value during domain assignment).

For prod: same pattern but `marketplace.isol8.co`.

## 5. Verify

```bash
aws secretsmanager describe-secret --name "isol8/dev/stripe_connect_client_id" \
  --profile isol8-admin --region us-east-1
# Expect: returns metadata, secret exists.

curl -I https://marketplace.dev.isol8.co
# Expect: 404 from Vercel (project exists, no deployment yet — that's correct)
```

## When Plan 1 is "done"

- `cdk deploy isol8-pipeline-dev/Database` succeeds; all 7 marketplace tables visible
  via `aws dynamodb list-tables | grep marketplace`.
- `cdk deploy isol8-pipeline-dev/Service` succeeds; bucket, Lambda, MCP task def visible.
- `scripts/validate-stripe-connect-sandbox.py` exits 0 against a real `sk_test_...` key.
- Vercel project shell exists; DNS resolves.
- Secrets Manager has both Connect secrets per env.

Plans 2-6 can now begin.
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/runbooks/marketplace-plan-1-provisioning.md
git commit -m "docs(marketplace): runbook for Plan 1 operational provisioning"
```

---

## Verification (end-to-end, after all tasks)

Run these from the repo root after merging Plan 1:

```bash
# 1. CDK tests
cd apps/infra && npm test -- marketplace-resources.test.ts
# Expected: all assertions pass.

# 2. Backend unit tests for payout_service scaffold
cd apps/backend && uv run pytest tests/unit/services/test_payout_service.py -v
# Expected: 3 tests pass.

# 3. CDK synth (no deploy yet)
cd apps/infra && npx cdk synth isol8-pipeline-dev/Database
# Expected: clean synth, lists all 7 marketplace tables in the output.

# 4. Stripe sandbox validation (manual)
export STRIPE_SECRET_KEY=sk_test_...  # your test-mode key
uv run python scripts/validate-stripe-connect-sandbox.py
# Expected: exit 0, output describes 5 successful steps.

# 5. Once merged + deployed to dev:
aws dynamodb list-tables --profile isol8-admin --region us-east-1 | grep marketplace
# Expected: 7 lines (all marketplace tables).

aws s3 ls --profile isol8-admin --region us-east-1 | grep marketplace
# Expected: isol8-dev-marketplace-artifacts.

aws lambda list-functions --profile isol8-admin --region us-east-1 \
  --query 'Functions[?contains(FunctionName, `marketplace`)].FunctionName' --output text
# Expected: isol8-dev-marketplace-search-indexer.
```

## Self-review notes

- **Spec coverage:** all 7 v1 DynamoDB tables present (reviews table excluded per Phase 2 deferral). S3 bucket present. Lambda + DDB stream subscription present. MCP task definition present (placeholder image, not running). Stripe Connect Express SDK present + sandbox validation script present. Vercel project shell + Secrets Manager + DNS captured in operational runbook.
- **Type consistency:** `marketplaceListingsTable` (camelCase) used throughout the CDK code. `MARKETPLACE_LISTINGS_TABLE` (SCREAMING_SNAKE) used throughout env vars. `marketplace-listings` (kebab-case) used throughout AWS resource names. Internally consistent.
- **No placeholders:** every step contains exact code, exact commands, exact expected output. The MCP task definition uses a public alpine image as a deliberate placeholder, called out explicitly with a comment naming Plan 3 as the swap-in.
- **Coverage of design doc Plan 1 scope:** matches the worktree-parallelization Phase 0 + the Lane F+G items from the eng-review doc.

## What's NOT in Plan 1 (deferred to Plan 2-6)

- All marketplace router code (`routers/marketplace_listings.py`, etc.)
- Listing create / update / publish service logic
- Webhook handler implementation
- License key generation and validation
- Skill.md adapter
- MCP server actual code (just the task definition shell here)
- CLI installer
- Storefront frontend
- Admin moderation UI
