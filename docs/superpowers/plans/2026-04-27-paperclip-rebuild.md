# Paperclip Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Paperclip as a bundled feature for every $50 flat-fee user, accessible at `company.isol8.co`, by deploying a single shared Paperclip ECS service backed by Aurora Serverless v2 with scale-to-zero, fronted by our existing FastAPI backend acting as an auth-injecting reverse proxy.

**Architecture:** One Paperclip server (multi-tenant via its native `companies` table) on a private subnet, talks to a shared Aurora cluster. Each Isol8 user gets their own Paperclip company provisioned at signup via Clerk webhook. The user's browser only ever talks to FastAPI; FastAPI proxies to Paperclip with a per-user Board API key. Paperclip's agents reach the user's per-user OpenClaw container via the `@paperclipai/adapter-openclaw-gateway` package using a long-lived service-token JWT that our extended Lambda Authorizer validates.

**Tech Stack:** AWS CDK (TypeScript) · ECS Fargate · Aurora Serverless v2 + pgvector · DynamoDB · FastAPI (Python 3.13) · httpx · websockets · Fernet encryption · Better Auth (Paperclip's; bypassed via Board API keys) · Clerk · upstream `paperclipai/paperclip:latest` Docker image.

**Test discipline:** Per memory `feedback_run_tests_at_end` + `feedback_write_tests_run_at_end`, write tests with each task but defer running them to end-of-plan verification (Tasks 19–20). Per-task targeted runs only if a task is high-risk or you suspect a regression.

**Branch:** All work on `feat/paperclip-rebuild` worktree at `.worktrees/paperclip-rebuild`.

---

## File Structure

### CDK (`apps/infra/`)
- **Modify** `lib/stacks/database-stack.ts` — Aurora Serverless v2 cluster + `paperclip-companies` DynamoDB table
- **Modify** `lib/stacks/auth-stack.ts` — three new secrets
- **Create** `lib/stacks/paperclip-stack.ts` — Paperclip ECS service + migration runner
- **Modify** `lib/stacks/network-stack.ts` — ALB host rule for `company.isol8.co`
- **Modify** `lib/stacks/dns-stack.ts` — Route 53 + ACM SAN
- **Modify** `lib/app.ts` (or `lib/local-stage.ts` + `lib/isol8-stage.ts`) — register `paperclip-stack`
- **Modify** `lambda/websocket-authorizer/index.py` — accept service-token JWTs

### Backend (`apps/backend/`)
- **Create** `core/services/paperclip_admin_client.py` — typed httpx client to Paperclip admin API
- **Create** `core/services/service_token.py` — mint/verify long-lived OpenClaw service-token JWTs
- **Create** `core/services/paperclip_provisioning.py` — orchestrator (Clerk → Paperclip company)
- **Create** `core/repositories/paperclip_repo.py` — DynamoDB repo for new table
- **Create** `routers/paperclip_proxy.py` — `company.isol8.co/*` reverse proxy
- **Modify** `core/config.py` — three new settings
- **Modify** `main.py` — host-conditional middleware mounts proxy router
- **Modify** `routers/webhooks.py` — Clerk + Stripe handler integration
- **Modify** `core/services/update_service.py` — extend pending-updates worker for cleanup cron

### Frontend (`apps/frontend/`)
- **Modify** the chat sidebar/header (TBD by reading current layout) — add a "Teams" link

### Tests
- **Create** `apps/backend/tests/test_paperclip_admin_client.py`
- **Create** `apps/backend/tests/test_paperclip_provisioning.py`
- **Create** `apps/backend/tests/test_paperclip_repo.py`
- **Create** `apps/backend/tests/test_paperclip_proxy.py`
- **Create** `apps/backend/tests/test_service_token.py`
- **Modify** `apps/infra/lambda/websocket-authorizer/test_index.py` (or create) — service-token validation cases

---

## Phase 1 — Infrastructure (CDK)

### Task 1: Aurora Serverless v2 cluster with pgvector

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`
- Test: `apps/infra/test/database-stack.test.ts` (extend if it exists; otherwise skip — CDK snapshot tests are optional in this repo)

- [ ] **Step 1: Read the existing database-stack.ts to understand naming conventions, tag patterns, and how secrets are referenced from other stacks.**

```bash
cat apps/infra/lib/stacks/database-stack.ts
```

- [ ] **Step 2: Add Aurora cluster construct.**

In `database-stack.ts`, after the existing DynamoDB tables, add:

```typescript
import * as rds from 'aws-cdk-lib/aws-rds';
import * as ec2 from 'aws-cdk-lib/aws-ec2';

// Inside the DatabaseStack class constructor, after existing tables:
const paperclipDbSubnetGroup = new rds.SubnetGroup(this, 'PaperclipDbSubnets', {
  vpc: props.vpc,
  description: 'Subnets for Paperclip Aurora cluster',
  vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
});

const paperclipDbSecurityGroup = new ec2.SecurityGroup(this, 'PaperclipDbSg', {
  vpc: props.vpc,
  description: 'Paperclip Aurora cluster — only backend SG and Paperclip task SG may reach 5432',
  allowAllOutbound: false,
});

this.paperclipDbCluster = new rds.DatabaseCluster(this, 'PaperclipDb', {
  engine: rds.DatabaseClusterEngine.auroraPostgres({
    version: rds.AuroraPostgresEngineVersion.VER_16_4,
  }),
  serverlessV2MinCapacity: 0,   // scale-to-zero
  serverlessV2MaxCapacity: 4,
  writer: rds.ClusterInstance.serverlessV2('writer'),
  vpc: props.vpc,
  subnetGroup: paperclipDbSubnetGroup,
  securityGroups: [paperclipDbSecurityGroup],
  defaultDatabaseName: 'paperclip',
  credentials: rds.Credentials.fromGeneratedSecret('paperclip_admin', {
    secretName: `isol8-${props.envName}-paperclip-db-credentials`,
  }),
  backup: { retention: cdk.Duration.days(7) },
  storageEncrypted: true,
  removalPolicy: cdk.RemovalPolicy.SNAPSHOT,
  clusterIdentifier: `isol8-${props.envName}-paperclip-db`,
});

// Expose so paperclip-stack can grant connect + reference SG
this.paperclipDbSecurityGroup = paperclipDbSecurityGroup;

// Output the connection-string-able pieces (Secrets Manager already has the
// password; we expose host + port for the DATABASE_URL builder in
// paperclip-stack).
new cdk.CfnOutput(this, 'PaperclipDbEndpoint', {
  value: this.paperclipDbCluster.clusterEndpoint.hostname,
  exportName: `isol8-${props.envName}-paperclip-db-endpoint`,
});
```

Add the property declarations near the top of the class:

```typescript
public readonly paperclipDbCluster: rds.DatabaseCluster;
public readonly paperclipDbSecurityGroup: ec2.SecurityGroup;
```

- [ ] **Step 3: Enable pgvector extension via initial migration.**

pgvector lives as a Postgres extension. Aurora Postgres 16.4 has it available but it must be `CREATE EXTENSION` from inside the database. We do this as part of the migrations runner in Task 5, NOT here. Add a comment in the cluster construct:

```typescript
// pgvector extension is created by the drizzle migrations runner in
// paperclip-stack.ts (Task 5), not here.
```

- [ ] **Step 4: Commit.**

```bash
cd .worktrees/paperclip-rebuild
git add apps/infra/lib/stacks/database-stack.ts
git commit -m "feat(infra): provision Aurora Serverless v2 cluster for Paperclip

Scale-to-zero (min 0 ACU, max 4 ACU) with pgvector available.
Subnet group on private subnets. Generated credentials in Secrets Manager.
pgvector extension is created by the drizzle migrations runner."
```

---

### Task 2: paperclip-companies DynamoDB table

**Files:**
- Modify: `apps/infra/lib/stacks/database-stack.ts`

- [ ] **Step 1: Add the table to database-stack.ts** (in same file, alongside existing tables):

```typescript
this.paperclipCompaniesTable = new dynamodb.Table(this, 'PaperclipCompaniesTable', {
  tableName: `isol8-${props.envName}-paperclip-companies`,
  partitionKey: { name: 'user_id', type: dynamodb.AttributeType.STRING },
  billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
  encryption: dynamodb.TableEncryption.AWS_MANAGED,
  pointInTimeRecovery: true,
  removalPolicy: props.envName === 'prod'
    ? cdk.RemovalPolicy.RETAIN
    : cdk.RemovalPolicy.DESTROY,
});

// GSI for the cleanup cron — lets us scan disabled rows past their grace window
this.paperclipCompaniesTable.addGlobalSecondaryIndex({
  indexName: 'by-status-purge-at',
  partitionKey: { name: 'status', type: dynamodb.AttributeType.STRING },
  sortKey: { name: 'scheduled_purge_at', type: dynamodb.AttributeType.STRING },
  projectionType: dynamodb.ProjectionType.KEYS_ONLY,
});
```

Add property declaration:

```typescript
public readonly paperclipCompaniesTable: dynamodb.Table;
```

- [ ] **Step 2: Commit.**

```bash
git add apps/infra/lib/stacks/database-stack.ts
git commit -m "feat(infra): add paperclip-companies DynamoDB table

PK user_id maps Isol8 user → Paperclip company + encrypted credentials.
GSI by-status-purge-at supports the cleanup cron."
```

---

### Task 3: New secrets in auth-stack

**Files:**
- Modify: `apps/infra/lib/stacks/auth-stack.ts`

- [ ] **Step 1: Read auth-stack.ts to follow the existing secret pattern.**

```bash
cat apps/infra/lib/stacks/auth-stack.ts
```

- [ ] **Step 2: Add three new secrets following the existing pattern.**

```typescript
// At the end of the AuthStack constructor, alongside existing secrets:
this.paperclipAdminBoardKey = new secretsmanager.Secret(this, 'PaperclipAdminBoardKey', {
  secretName: `isol8-${props.envName}-paperclip-admin-board-key`,
  description: 'Instance-admin Board API key used by FastAPI to call Paperclip admin API',
  encryptionKey: this.kmsKey,
  // No generateSecretString — minted manually post-deploy on first Paperclip
  // bootstrap (Task 5 captures this in the runbook).
});

this.paperclipBetterAuthSecret = new secretsmanager.Secret(this, 'PaperclipBetterAuthSecret', {
  secretName: `isol8-${props.envName}-paperclip-better-auth-secret`,
  description: 'Paperclip BETTER_AUTH_SECRET (cookie signing); not used by us but required by Paperclip server',
  encryptionKey: this.kmsKey,
  generateSecretString: {
    passwordLength: 64,
    excludePunctuation: true,
  },
});

this.paperclipServiceTokenKey = new secretsmanager.Secret(this, 'PaperclipServiceTokenKey', {
  secretName: `isol8-${props.envName}-paperclip-service-token-key`,
  description: 'Symmetric secret for signing/verifying OpenClaw service-token JWTs (used by paperclip_provisioning + Lambda Authorizer)',
  encryptionKey: this.kmsKey,
  generateSecretString: {
    passwordLength: 64,
    excludePunctuation: true,
  },
});
```

Property declarations:

```typescript
public readonly paperclipAdminBoardKey: secretsmanager.Secret;
public readonly paperclipBetterAuthSecret: secretsmanager.Secret;
public readonly paperclipServiceTokenKey: secretsmanager.Secret;
```

- [ ] **Step 3: Commit.**

```bash
git add apps/infra/lib/stacks/auth-stack.ts
git commit -m "feat(infra): add Paperclip secrets (admin key, BetterAuth secret, service-token key)

All KMS-encrypted. BetterAuth + service-token-key are auto-generated.
Admin Board API key is minted manually post-first-deploy."
```

---

### Task 4: Paperclip ECS service + ALB internal target group

**Files:**
- Create: `apps/infra/lib/stacks/paperclip-stack.ts`
- Modify: `apps/infra/lib/app.ts` (or per-stage stage classes — read existing wiring first)

- [ ] **Step 1: Read existing service-stack.ts to copy the ECS service + autoscaling pattern.**

```bash
cat apps/infra/lib/stacks/service-stack.ts | head -200
```

- [ ] **Step 2: Create `paperclip-stack.ts`.**

```typescript
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as ecs from 'aws-cdk-lib/aws-ecs';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as rds from 'aws-cdk-lib/aws-rds';

interface PaperclipStackProps extends cdk.StackProps {
  envName: string;
  vpc: ec2.IVpc;
  cluster: ecs.ICluster;                     // reuse existing ECS cluster from container-stack
  paperclipDbCluster: rds.IDatabaseCluster;
  paperclipDbSecurityGroup: ec2.ISecurityGroup;
  paperclipBetterAuthSecretName: string;
  // ALB internal listener wiring (provided by network-stack)
  internalAlbListener: elbv2.ApplicationListener;
  internalAlbListenerRulePriorityStart: number;
}

export class PaperclipStack extends cdk.Stack {
  public readonly service: ecs.FargateService;
  public readonly taskSecurityGroup: ec2.SecurityGroup;
  public readonly internalUrl: string;

  constructor(scope: Construct, id: string, props: PaperclipStackProps) {
    super(scope, id, props);

    const logGroup = new logs.LogGroup(this, 'PaperclipLogs', {
      logGroupName: `/isol8/${props.envName}/paperclip`,
      retention: logs.RetentionDays.TWO_WEEKS,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    this.taskSecurityGroup = new ec2.SecurityGroup(this, 'PaperclipTaskSg', {
      vpc: props.vpc,
      description: 'Paperclip ECS task — egress to Aurora + ALB ingress only',
      allowAllOutbound: true,
    });
    // Allow the task to reach Aurora
    props.paperclipDbSecurityGroup.addIngressRule(
      this.taskSecurityGroup,
      ec2.Port.tcp(5432),
      'Paperclip task → Aurora',
    );

    const taskDefinition = new ecs.FargateTaskDefinition(this, 'PaperclipTaskDef', {
      family: `isol8-${props.envName}-paperclip-server`,
      cpu: 512,
      memoryLimitMiB: 1024,
    });

    // DATABASE_URL is built from the cluster's master secret + endpoint.
    // Paperclip accepts standard postgres:// URLs (per its docs/deploy/database.md).
    const dbCredsSecret = props.paperclipDbCluster.secret!;
    const dbUrlSecret = ecs.Secret.fromSecretsManager(dbCredsSecret); // we'll wire this as DB_PASSWORD and build URL via entrypoint env

    const betterAuthSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      'PaperclipBetterAuthSecretRef',
      props.paperclipBetterAuthSecretName,
    );

    taskDefinition.addContainer('paperclip', {
      image: ecs.ContainerImage.fromRegistry('paperclipai/paperclip:latest'),
      logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'paperclip', logGroup }),
      environment: {
        PORT: '3100',
        PAPERCLIP_DEPLOYMENT_MODE: 'authenticated',
        PAPERCLIP_DEPLOYMENT_EXPOSURE: 'public',
        PAPERCLIP_PUBLIC_URL: `https://company${props.envName === 'prod' ? '' : '-' + props.envName}.isol8.co`,
        PAPERCLIP_AUTH_DISABLE_SIGN_UP: 'true',
        PAPERCLIP_BIND: 'lan',
        // Construct DATABASE_URL inline. Paperclip accepts standard postgres:// strings;
        // the cluster's generated secret has username/password/host/port fields.
        // We bake host/port at synth time and inject password at runtime via secret env.
        PGHOST: props.paperclipDbCluster.clusterEndpoint.hostname,
        PGPORT: '5432',
        PGUSER: 'paperclip_admin',
        PGDATABASE: 'paperclip',
      },
      secrets: {
        PGPASSWORD: ecs.Secret.fromSecretsManager(dbCredsSecret, 'password'),
        BETTER_AUTH_SECRET: ecs.Secret.fromSecretsManager(betterAuthSecret),
      },
      // Paperclip's docker-entrypoint reads DATABASE_URL OR PG* env. If it
      // doesn't accept PG* directly, switch to building DATABASE_URL via a
      // small entrypoint wrapper (see Discovery note in spec §8).
      command: [
        '/bin/sh',
        '-c',
        'export DATABASE_URL="postgres://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}" && exec docker-entrypoint.sh node --import ./server/node_modules/tsx/dist/loader.mjs server/dist/index.js',
      ],
      healthCheck: {
        command: ['CMD-SHELL', 'curl -fsS http://localhost:3100/api/health || exit 1'],
        interval: cdk.Duration.seconds(30),
        timeout: cdk.Duration.seconds(10),
        retries: 3,
        startPeriod: cdk.Duration.seconds(60),
      },
      portMappings: [{ containerPort: 3100, protocol: ecs.Protocol.TCP }],
    });

    this.service = new ecs.FargateService(this, 'PaperclipService', {
      cluster: props.cluster,
      taskDefinition,
      serviceName: `isol8-${props.envName}-paperclip-server`,
      desiredCount: 1,
      securityGroups: [this.taskSecurityGroup],
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
      assignPublicIp: false,
      circuitBreaker: { rollback: true },
      minHealthyPercent: 100,
      maxHealthyPercent: 200,
    });

    // Autoscale on CPU
    const scaling = this.service.autoScaleTaskCount({ minCapacity: 1, maxCapacity: 4 });
    scaling.scaleOnCpuUtilization('CpuScaling', {
      targetUtilizationPercent: 70,
      scaleInCooldown: cdk.Duration.minutes(5),
      scaleOutCooldown: cdk.Duration.minutes(2),
    });

    // Internal target group + listener rule (FastAPI reaches Paperclip via this).
    const targetGroup = new elbv2.ApplicationTargetGroup(this, 'PaperclipTg', {
      vpc: props.vpc,
      port: 3100,
      protocol: elbv2.ApplicationProtocol.HTTP,
      targetType: elbv2.TargetType.IP,
      healthCheck: {
        path: '/api/health',
        interval: cdk.Duration.seconds(30),
        healthyHttpCodes: '200',
      },
    });
    this.service.attachToApplicationTargetGroup(targetGroup);

    new elbv2.ApplicationListenerRule(this, 'PaperclipInternalRule', {
      listener: props.internalAlbListener,
      priority: props.internalAlbListenerRulePriorityStart,
      conditions: [elbv2.ListenerCondition.hostHeaders([`paperclip.internal.isol8.local`])],
      action: elbv2.ListenerAction.forward([targetGroup]),
    });

    this.internalUrl = `http://paperclip.internal.isol8.local`;

    new cdk.CfnOutput(this, 'PaperclipInternalUrl', {
      value: this.internalUrl,
      exportName: `isol8-${props.envName}-paperclip-internal-url`,
    });
  }
}
```

- [ ] **Step 3: Wire `paperclip-stack` into the per-env stage.**

Read the existing stage class to find the pattern:

```bash
grep -l "DatabaseStack\|ServiceStack" apps/infra/lib/*.ts
```

Add to whichever stage file (likely `lib/local-stage.ts` and `lib/isol8-stage.ts`):

```typescript
const paperclipStack = new PaperclipStack(this, 'Paperclip', {
  envName: this.envName,
  vpc: networkStack.vpc,
  cluster: containerStack.cluster,
  paperclipDbCluster: databaseStack.paperclipDbCluster,
  paperclipDbSecurityGroup: databaseStack.paperclipDbSecurityGroup,
  paperclipBetterAuthSecretName: authStack.paperclipBetterAuthSecret.secretName,
  internalAlbListener: networkStack.internalAlbListener,
  internalAlbListenerRulePriorityStart: 200,
});
paperclipStack.addDependency(databaseStack);
paperclipStack.addDependency(authStack);
paperclipStack.addDependency(containerStack);
```

> **Discovery note:** the spec §8 calls out verification that Paperclip's entrypoint accepts the DATABASE_URL we construct. Test this by running the container locally first: `docker run --rm -e DATABASE_URL=postgres://...localhost... -p 3100:3100 paperclipai/paperclip:latest` against a local Postgres + pgvector. If the entrypoint requires a different env shape, adjust the `command` block above.

- [ ] **Step 4: Commit.**

```bash
git add apps/infra/lib/stacks/paperclip-stack.ts apps/infra/lib/local-stage.ts apps/infra/lib/isol8-stage.ts
git commit -m "feat(infra): Paperclip ECS service stack

One Fargate task, 0.5 vCPU / 1 GB, autoscale 1-4. Pulls upstream
paperclipai/paperclip:latest. Wired to Aurora via DATABASE_URL.
Internal-only target group on shared ALB; FastAPI is the only
caller able to reach it."
```

---

### Task 5: Drizzle migrations one-shot ECS task

**Files:**
- Modify: `apps/infra/lib/stacks/paperclip-stack.ts`

- [ ] **Step 1: Read Paperclip's Drizzle config to confirm the migrations command.**

```bash
grep -rn "drizzle-kit\|migrate" ~/Desktop/paperclip/server/package.json ~/Desktop/paperclip/packages/db/package.json | head -10
```

The expected command is `pnpm --filter @paperclipai/db migrate` or `npx drizzle-kit migrate` from the package root. Confirm by reading the actual package.json scripts.

- [ ] **Step 2: Add a one-shot ECS task definition for migrations + a CDK custom resource that invokes it on deploy.**

In `paperclip-stack.ts`, after the main `service` declaration:

```typescript
import * as triggers from 'aws-cdk-lib/triggers';

const migrateTaskDef = new ecs.FargateTaskDefinition(this, 'PaperclipMigrateTaskDef', {
  family: `isol8-${props.envName}-paperclip-migrate`,
  cpu: 256,
  memoryLimitMiB: 512,
});
migrateTaskDef.addContainer('migrate', {
  image: ecs.ContainerImage.fromRegistry('paperclipai/paperclip:latest'),
  logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'paperclip-migrate', logGroup }),
  environment: {
    PGHOST: props.paperclipDbCluster.clusterEndpoint.hostname,
    PGPORT: '5432',
    PGUSER: 'paperclip_admin',
    PGDATABASE: 'paperclip',
  },
  secrets: {
    PGPASSWORD: ecs.Secret.fromSecretsManager(dbCredsSecret, 'password'),
  },
  command: [
    '/bin/sh',
    '-c',
    [
      'export DATABASE_URL="postgres://${PGUSER}:${PGPASSWORD}@${PGHOST}:${PGPORT}/${PGDATABASE}"',
      // Enable pgvector before running app migrations
      'apt-get update && apt-get install -y postgresql-client && PGPASSWORD="$PGPASSWORD" psql -h "$PGHOST" -U "$PGUSER" -d "$PGDATABASE" -c "CREATE EXTENSION IF NOT EXISTS vector;"',
      'cd /app && pnpm --filter @paperclipai/db migrate',
    ].join(' && '),
  ],
});
```

> **Note:** triggering an ECS RunTask from a CDK custom resource is non-trivial. For v1 use a simpler pattern — manually run the migration after deploy, documented in a runbook. Or use the AWS CLI from a CI step. Skipping the auto-trigger custom resource keeps the plan simpler.

Add a CDK output with the run-task command for the runbook:

```typescript
new cdk.CfnOutput(this, 'PaperclipMigrateRunCommand', {
  value: `aws ecs run-task --cluster ${props.cluster.clusterName} --launch-type FARGATE --task-definition ${migrateTaskDef.family} --network-configuration 'awsvpcConfiguration={subnets=[<private-subnet>],securityGroups=[${this.taskSecurityGroup.securityGroupId}]}'`,
  description: 'Run this command after CDK deploy to apply Paperclip Drizzle migrations + create pgvector extension',
});
```

- [ ] **Step 3: Document the runbook step in `apps/infra/openclaw/README.md` or a new file.**

Create `apps/infra/paperclip/RUNBOOK.md`:

```markdown
# Paperclip Migrations Runbook

After every `cdk deploy` of the Paperclip stack, run database migrations:

```bash
aws ecs run-task --cluster <cluster-arn> \
  --launch-type FARGATE \
  --task-definition isol8-<env>-paperclip-migrate \
  --network-configuration "awsvpcConfiguration={subnets=[<priv-subnet-1>,<priv-subnet-2>],securityGroups=[<paperclip-task-sg>]}" \
  --profile isol8-admin --region us-east-1
```

This:
1. Connects to Aurora using the cluster credentials
2. Creates the `vector` extension if not present
3. Runs `drizzle-kit migrate` against the `@paperclipai/db` package

Wait for the task to reach `STOPPED` with exit code 0 before the Paperclip
service is considered deployable.
```

- [ ] **Step 4: Commit.**

```bash
git add apps/infra/lib/stacks/paperclip-stack.ts apps/infra/paperclip/RUNBOOK.md
git commit -m "feat(infra): Paperclip drizzle migrations one-shot task

Separate ECS task definition for migrations. Run manually post-deploy
per RUNBOOK.md. Creates pgvector extension before running drizzle-kit migrate."
```

---

### Task 6: ALB host rule for company.isol8.co

**Files:**
- Modify: `apps/infra/lib/stacks/network-stack.ts`

- [ ] **Step 1: Read network-stack.ts to find where the `api.isol8.co` host rule lives.**

```bash
grep -n "api.isol8.co\|hostHeaders\|ListenerRule" apps/infra/lib/stacks/network-stack.ts
```

- [ ] **Step 2: Add a new ALB listener rule for `company.isol8.co` pointing at the same FastAPI target group as `api.isol8.co`.**

```typescript
// Inside NetworkStack, alongside the existing api.isol8.co rule:
const companyHost = props.envName === 'prod' ? 'company.isol8.co' : `company-${props.envName}.isol8.co`;

new elbv2.ApplicationListenerRule(this, 'CompanyHostRule', {
  listener: this.publicHttpsListener,
  priority: 150,                         // pick a free priority — confirm via grep
  conditions: [elbv2.ListenerCondition.hostHeaders([companyHost])],
  action: elbv2.ListenerAction.forward([this.backendTargetGroup]),  // SAME target group as api.isol8.co
});
```

- [ ] **Step 3: Commit.**

```bash
git add apps/infra/lib/stacks/network-stack.ts
git commit -m "feat(infra): ALB rule for company.isol8.co → FastAPI

Routes to the same backend target group as api.isol8.co.
Backend dispatches by Host header (Task 16)."
```

---

### Task 7: Route 53 record + ACM SAN

**Files:**
- Modify: `apps/infra/lib/stacks/dns-stack.ts`

- [ ] **Step 1: Read dns-stack.ts to follow the existing record + cert pattern.**

```bash
cat apps/infra/lib/stacks/dns-stack.ts
```

- [ ] **Step 2: Add `company.isol8.co` (or `company-{env}.isol8.co` for non-prod) to the existing ACM cert SANs and create a Route 53 A-alias to the ALB.**

```typescript
// Add to existing cert subjectAlternativeNames array:
const companyDomain = props.envName === 'prod' ? 'company.isol8.co' : `company-${props.envName}.isol8.co`;

// In the Certificate construct's subjectAlternativeNames:
subjectAlternativeNames: [
  // ...existing...
  companyDomain,
],

// New A-record alias:
new route53.ARecord(this, 'CompanyAlbAlias', {
  zone: props.hostedZone,
  recordName: companyDomain,
  target: route53.RecordTarget.fromAlias(new targets.LoadBalancerTarget(props.alb)),
});
```

- [ ] **Step 3: Commit.**

```bash
git add apps/infra/lib/stacks/dns-stack.ts
git commit -m "feat(infra): Route 53 + ACM SAN for company.isol8.co"
```

---

## Phase 2 — Backend foundations

### Task 8: paperclip_repo.py (DynamoDB repository)

**Files:**
- Create: `apps/backend/core/repositories/paperclip_repo.py`
- Create: `apps/backend/tests/test_paperclip_repo.py`

- [ ] **Step 1: Read an existing repo to follow the pattern.**

```bash
cat apps/backend/core/repositories/api_key_repo.py
```

- [ ] **Step 2: Write the test file (`tests/test_paperclip_repo.py`).**

```python
"""Tests for paperclip_repo using moto's DynamoDB mock."""
import pytest
import boto3
from moto import mock_aws
from datetime import datetime, timezone

from core.repositories.paperclip_repo import PaperclipRepo, PaperclipCompany

TABLE_NAME = "test-paperclip-companies"


@pytest.fixture
def repo():
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE_NAME,
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield PaperclipRepo(table_name=TABLE_NAME, region="us-east-1")


def test_put_and_get_round_trips(repo):
    company = PaperclipCompany(
        user_id="user_123",
        company_id="co_abc",
        board_api_key_encrypted="enc_key",
        service_token_encrypted="enc_token",
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repo.put(company)
    retrieved = repo.get("user_123")
    assert retrieved is not None
    assert retrieved.company_id == "co_abc"
    assert retrieved.status == "active"


def test_get_returns_none_for_missing(repo):
    assert repo.get("user_does_not_exist") is None


def test_update_status(repo):
    repo.put(PaperclipCompany(
        user_id="user_456",
        company_id="co_def",
        board_api_key_encrypted="enc",
        service_token_encrypted="enc",
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    repo.update_status("user_456", status="disabled", scheduled_purge_at=datetime(2026, 5, 27, tzinfo=timezone.utc))
    retrieved = repo.get("user_456")
    assert retrieved.status == "disabled"
    assert retrieved.scheduled_purge_at is not None


def test_delete(repo):
    repo.put(PaperclipCompany(
        user_id="user_789",
        company_id="co_ghi",
        board_api_key_encrypted="enc",
        service_token_encrypted="enc",
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    ))
    repo.delete("user_789")
    assert repo.get("user_789") is None
```

- [ ] **Step 3: Implement `paperclip_repo.py`.**

```python
"""DynamoDB repository for paperclip-companies table.

PK: user_id (S)
Maps Isol8 user → Paperclip company + encrypted credentials.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Key


@dataclass
class PaperclipCompany:
    user_id: str
    company_id: str
    board_api_key_encrypted: str
    service_token_encrypted: str
    status: str  # "provisioning" | "active" | "failed" | "disabled"
    created_at: datetime
    updated_at: datetime
    last_error: Optional[str] = None
    scheduled_purge_at: Optional[datetime] = None


class PaperclipRepo:
    def __init__(self, table_name: str, region: str = "us-east-1"):
        self._table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def put(self, company: PaperclipCompany) -> None:
        item = {
            "user_id": company.user_id,
            "company_id": company.company_id,
            "board_api_key_encrypted": company.board_api_key_encrypted,
            "service_token_encrypted": company.service_token_encrypted,
            "status": company.status,
            "created_at": company.created_at.isoformat(),
            "updated_at": company.updated_at.isoformat(),
        }
        if company.last_error is not None:
            item["last_error"] = company.last_error
        if company.scheduled_purge_at is not None:
            item["scheduled_purge_at"] = company.scheduled_purge_at.isoformat()
        self._table.put_item(Item=item)

    def get(self, user_id: str) -> Optional[PaperclipCompany]:
        resp = self._table.get_item(Key={"user_id": user_id})
        if "Item" not in resp:
            return None
        item = resp["Item"]
        return PaperclipCompany(
            user_id=item["user_id"],
            company_id=item["company_id"],
            board_api_key_encrypted=item["board_api_key_encrypted"],
            service_token_encrypted=item["service_token_encrypted"],
            status=item["status"],
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
            last_error=item.get("last_error"),
            scheduled_purge_at=(
                datetime.fromisoformat(item["scheduled_purge_at"])
                if item.get("scheduled_purge_at")
                else None
            ),
        )

    def update_status(
        self,
        user_id: str,
        *,
        status: str,
        last_error: Optional[str] = None,
        scheduled_purge_at: Optional[datetime] = None,
    ) -> None:
        update_expr = "SET #s = :s, updated_at = :u"
        expr_names = {"#s": "status"}
        expr_values = {
            ":s": status,
            ":u": datetime.now(timezone.utc).isoformat(),
        }
        if last_error is not None:
            update_expr += ", last_error = :e"
            expr_values[":e"] = last_error
        if scheduled_purge_at is not None:
            update_expr += ", scheduled_purge_at = :p"
            expr_values[":p"] = scheduled_purge_at.isoformat()
        self._table.update_item(
            Key={"user_id": user_id},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=expr_values,
        )

    def delete(self, user_id: str) -> None:
        self._table.delete_item(Key={"user_id": user_id})

    def scan_purge_due(self, now: datetime) -> list[PaperclipCompany]:
        """Scan disabled rows whose scheduled_purge_at <= now via the GSI."""
        resp = self._table.query(
            IndexName="by-status-purge-at",
            KeyConditionExpression=Key("status").eq("disabled") & Key("scheduled_purge_at").lte(now.isoformat()),
        )
        # GSI is KEYS_ONLY; fetch full items
        return [self.get(item["user_id"]) for item in resp.get("Items", []) if self.get(item["user_id"])]
```

- [ ] **Step 4: Commit.**

```bash
git add apps/backend/core/repositories/paperclip_repo.py apps/backend/tests/test_paperclip_repo.py
git commit -m "feat(backend): paperclip-companies DynamoDB repository

PK user_id. CRUD + scan_purge_due via GSI for the cleanup cron."
```

---

### Task 9: service_token.py + Lambda Authorizer extension

**Files:**
- Create: `apps/backend/core/services/service_token.py`
- Create: `apps/backend/tests/test_service_token.py`
- Modify: `apps/infra/lambda/websocket-authorizer/index.py`

- [ ] **Step 1: Read existing Clerk JWT handling in `core/auth.py` to follow the JWT pattern.**

```bash
sed -n '1,80p' apps/backend/core/auth.py
```

- [ ] **Step 2: Write `service_token.py`.**

```python
"""OpenClaw service-token JWTs.

These are long-lived JWTs minted by the backend, signed with a symmetric secret
shared with the Lambda Authorizer. They authorize Paperclip agents to reach a
specific user's OpenClaw container via the existing WebSocket gateway.

Format: HS256 JWT
Claims:
  - sub: user_id (string)
  - kind: "paperclip_service" (string)
  - iat: issued-at (int)
  - exp: expiry (int)  — default 1 year
  - jti: unique token id (string)  — for revocation
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

import jwt

SERVICE_TOKEN_KIND = "paperclip_service"
DEFAULT_TTL_DAYS = 365


def _signing_key() -> str:
    key = os.environ.get("PAPERCLIP_SERVICE_TOKEN_KEY")
    if not key:
        raise RuntimeError("PAPERCLIP_SERVICE_TOKEN_KEY env var not set")
    return key


def mint(user_id: str, ttl_days: int = DEFAULT_TTL_DAYS) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "kind": SERVICE_TOKEN_KIND,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=ttl_days)).timestamp()),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, _signing_key(), algorithm="HS256")


def verify(token: str) -> dict:
    """Verify a service token. Returns the claims dict on success.

    Raises jwt.ExpiredSignatureError, jwt.InvalidTokenError on failure.
    """
    claims = jwt.decode(token, _signing_key(), algorithms=["HS256"])
    if claims.get("kind") != SERVICE_TOKEN_KIND:
        raise jwt.InvalidTokenError(f"Wrong kind claim: {claims.get('kind')!r}")
    if not claims.get("sub"):
        raise jwt.InvalidTokenError("Missing sub claim")
    return claims
```

- [ ] **Step 3: Write `tests/test_service_token.py`.**

```python
import os
import pytest
import jwt as pyjwt

from core.services import service_token


@pytest.fixture(autouse=True)
def signing_key(monkeypatch):
    monkeypatch.setenv("PAPERCLIP_SERVICE_TOKEN_KEY", "test-secret-not-real")


def test_mint_then_verify():
    token = service_token.mint("user_123")
    claims = service_token.verify(token)
    assert claims["sub"] == "user_123"
    assert claims["kind"] == "paperclip_service"
    assert "jti" in claims


def test_verify_wrong_kind_rejected(monkeypatch):
    # Manually craft a JWT with the wrong kind
    bad = pyjwt.encode({"sub": "user_x", "kind": "clerk_user"}, "test-secret-not-real", algorithm="HS256")
    with pytest.raises(pyjwt.InvalidTokenError):
        service_token.verify(bad)


def test_verify_expired_rejected(monkeypatch):
    expired = pyjwt.encode(
        {"sub": "u", "kind": "paperclip_service", "exp": 1},
        "test-secret-not-real",
        algorithm="HS256",
    )
    with pytest.raises(pyjwt.ExpiredSignatureError):
        service_token.verify(expired)


def test_verify_wrong_secret_rejected():
    other = pyjwt.encode({"sub": "u", "kind": "paperclip_service"}, "different-secret", algorithm="HS256")
    with pytest.raises(pyjwt.InvalidTokenError):
        service_token.verify(other)
```

- [ ] **Step 4: Extend the Lambda Authorizer to accept service tokens.**

Read the current authorizer:

```bash
cat apps/infra/lambda/websocket-authorizer/index.py
```

Then add a service-token validation branch alongside the existing Clerk JWT validation. Pseudocode (adapt to actual code shape):

```python
# At the top of index.py:
import os

import jwt

PAPERCLIP_SERVICE_TOKEN_KEY = os.environ.get("PAPERCLIP_SERVICE_TOKEN_KEY", "")

def _try_service_token(token: str) -> dict | None:
    if not PAPERCLIP_SERVICE_TOKEN_KEY:
        return None
    try:
        claims = jwt.decode(token, PAPERCLIP_SERVICE_TOKEN_KEY, algorithms=["HS256"])
        if claims.get("kind") != "paperclip_service":
            return None
        return {"user_id": claims["sub"], "auth_kind": "paperclip_service", "jti": claims.get("jti")}
    except jwt.PyJWTError:
        return None


# In the lambda_handler, BEFORE attempting Clerk JWT verification, try service-token first:
def lambda_handler(event, context):
    token = _extract_bearer_token(event)
    # Try service token first (cheap symmetric verify)
    if claims := _try_service_token(token):
        return _allow(claims["user_id"], event, auth_kind=claims["auth_kind"])
    # Fall through to existing Clerk JWT path
    # ... existing code ...
```

- [ ] **Step 5: Wire the secret into the Lambda's environment via CDK (`api-stack.ts`).**

```typescript
// In api-stack.ts, on the websocket authorizer Lambda:
authorizerFn.addEnvironment(
  'PAPERCLIP_SERVICE_TOKEN_KEY_SECRET_ARN',
  paperclipServiceTokenKey.secretArn,
);
paperclipServiceTokenKey.grantRead(authorizerFn);
```

For the Lambda's `index.py` to read from Secrets Manager at cold start, add a small helper. (Or wire as plain env if the deploy script can fetch and set it — confirm pattern from existing Lambda envs.)

- [ ] **Step 6: Update Lambda `requirements.txt`** to ensure `pyjwt` is present:

```bash
grep -q pyjwt apps/infra/lambda/websocket-authorizer/requirements.txt || echo "pyjwt>=2.8" >> apps/infra/lambda/websocket-authorizer/requirements.txt
```

- [ ] **Step 7: Commit.**

```bash
git add apps/backend/core/services/service_token.py apps/backend/tests/test_service_token.py apps/infra/lambda/websocket-authorizer/index.py apps/infra/lambda/websocket-authorizer/requirements.txt apps/infra/lib/stacks/api-stack.ts
git commit -m "feat(auth): mint + verify OpenClaw service-token JWTs

HS256 with shared secret. Lambda Authorizer accepts both Clerk JWTs
and service tokens; service tokens authorize Paperclip agents to reach
a specific user's OpenClaw container."
```

---

### Task 10: paperclip_admin_client.py

**Files:**
- Create: `apps/backend/core/services/paperclip_admin_client.py`
- Create: `apps/backend/tests/test_paperclip_admin_client.py`

- [ ] **Step 1: Read Paperclip's API docs to confirm exact endpoint shapes.**

```bash
ls ~/Desktop/paperclip/docs/api/
cat ~/Desktop/paperclip/docs/api/companies.md
cat ~/Desktop/paperclip/docs/api/agents.md
```

Note any deviations from the assumed shapes below — adjust accordingly. **The plan assumes:**
- `POST /api/companies` → `{name, owner_email}` → returns `{id, ...}`
- `POST /api/companies/{companyId}/board-api-keys` → `{user_email, name}` → returns `{token, id}`
- `POST /api/companies/{companyId}/agents` → `{name, role, adapter_config}` → returns `{id, ...}`
- `POST /api/companies/{companyId}/disable` (or DELETE) → 204
- `DELETE /api/companies/{companyId}` → 204

If the actual surface differs, this client + the provisioning service in Task 11 must be updated to match. **Discovery:** if board API keys are minted at the user-level (`/api/users/.../keys`) rather than per-company, restructure accordingly.

- [ ] **Step 2: Write the test file.**

```python
"""Tests for paperclip_admin_client using httpx MockTransport."""
import pytest
import httpx

from core.services.paperclip_admin_client import (
    PaperclipAdminClient,
    PaperclipApiError,
)


def make_client(handler):
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://paperclip.test")
    return PaperclipAdminClient(http_client=http, admin_token="admin-test-key")


@pytest.mark.asyncio
async def test_create_company_sends_admin_bearer_and_idempotency_key():
    captured = {}
    def handler(req: httpx.Request):
        captured["url"] = str(req.url)
        captured["auth"] = req.headers.get("authorization")
        captured["idem"] = req.headers.get("idempotency-key")
        return httpx.Response(200, json={"id": "co_abc", "name": "u@example.com"})
    client = make_client(handler)
    company = await client.create_company(name="u@example.com", owner_email="u@example.com", idempotency_key="user_123")
    assert captured["auth"] == "Bearer admin-test-key"
    assert captured["idem"] == "user_123"
    assert company["id"] == "co_abc"


@pytest.mark.asyncio
async def test_5xx_raises_paperclip_api_error():
    def handler(req: httpx.Request):
        return httpx.Response(503, json={"error": "down"})
    client = make_client(handler)
    with pytest.raises(PaperclipApiError):
        await client.create_company(name="x", owner_email="x@y.com")


@pytest.mark.asyncio
async def test_mint_board_api_key_returns_token():
    def handler(req: httpx.Request):
        return httpx.Response(200, json={"id": "key_1", "token": "secret-token-value"})
    client = make_client(handler)
    result = await client.mint_board_api_key(company_id="co_abc", user_email="u@example.com", name="primary")
    assert result["token"] == "secret-token-value"


@pytest.mark.asyncio
async def test_create_agent_passes_adapter_config():
    captured = {}
    def handler(req: httpx.Request):
        captured["body"] = req.read().decode()
        return httpx.Response(200, json={"id": "agent_1"})
    client = make_client(handler)
    await client.create_agent(
        company_id="co_abc",
        name="Main Agent",
        role="ceo",
        adapter_config={
            "adapter": "openclaw-gateway",
            "url": "wss://ws-dev.isol8.co",
            "authToken": "svc_token_xyz",
            "sessionKeyStrategy": "fixed",
            "sessionKey": "user_123",
        },
    )
    assert "openclaw-gateway" in captured["body"]
    assert "svc_token_xyz" in captured["body"]
```

- [ ] **Step 3: Write the implementation.**

```python
"""Typed httpx client for Paperclip's admin API.

Auth: instance-admin Board API key (Bearer header).
All mutations send Idempotency-Key headers when caller provides one.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


class PaperclipApiError(Exception):
    """Raised when Paperclip returns a non-2xx response."""

    def __init__(self, message: str, status_code: int, body: Any):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class PaperclipAdminClient:
    def __init__(self, http_client: httpx.AsyncClient, admin_token: str):
        self._http = http_client
        self._admin_token = admin_token

    def _headers(self, idempotency_key: Optional[str] = None) -> dict:
        headers = {
            "Authorization": f"Bearer {self._admin_token}",
            "Content-Type": "application/json",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _post(self, path: str, json: dict, idempotency_key: Optional[str] = None) -> dict:
        resp = await self._http.post(path, json=json, headers=self._headers(idempotency_key))
        if resp.status_code >= 400:
            raise PaperclipApiError(
                f"POST {path} -> {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )
        return resp.json() if resp.content else {}

    async def _delete(self, path: str) -> None:
        resp = await self._http.delete(path, headers=self._headers())
        if resp.status_code >= 400 and resp.status_code != 404:
            raise PaperclipApiError(
                f"DELETE {path} -> {resp.status_code}",
                status_code=resp.status_code,
                body=resp.text,
            )

    async def create_company(
        self,
        *,
        name: str,
        owner_email: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        return await self._post(
            "/api/companies",
            json={"name": name, "ownerEmail": owner_email},
            idempotency_key=idempotency_key,
        )

    async def mint_board_api_key(
        self,
        *,
        company_id: str,
        user_email: str,
        name: str,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        return await self._post(
            f"/api/companies/{company_id}/board-api-keys",
            json={"userEmail": user_email, "name": name},
            idempotency_key=idempotency_key,
        )

    async def create_agent(
        self,
        *,
        company_id: str,
        name: str,
        role: str,
        adapter_config: dict,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        return await self._post(
            f"/api/companies/{company_id}/agents",
            json={
                "name": name,
                "role": role,
                "adapterConfig": adapter_config,
            },
            idempotency_key=idempotency_key,
        )

    async def disable_company(self, *, company_id: str) -> None:
        await self._post(f"/api/companies/{company_id}/disable", json={})

    async def delete_company(self, *, company_id: str) -> None:
        await self._delete(f"/api/companies/{company_id}")
```

- [ ] **Step 4: Commit.**

```bash
git add apps/backend/core/services/paperclip_admin_client.py apps/backend/tests/test_paperclip_admin_client.py
git commit -m "feat(backend): typed httpx client for Paperclip admin API

create_company, mint_board_api_key, create_agent, disable_company,
delete_company. Sends Idempotency-Key on mutations."
```

---

### Task 11: paperclip_provisioning.py

**Files:**
- Create: `apps/backend/core/services/paperclip_provisioning.py`
- Create: `apps/backend/tests/test_paperclip_provisioning.py`

- [ ] **Step 1: Implement.**

```python
"""Orchestrator for provisioning Paperclip companies on Clerk user.created.

Idempotent on user_id. Each step checks for existing artifacts and skips
re-creation. On any failure, sets repo status="failed" and re-raises so
the webhook handler can return 5xx for Clerk to retry.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from core.config import settings
from core.encryption import encrypt, decrypt
from core.repositories.paperclip_repo import PaperclipCompany, PaperclipRepo
from core.services import service_token
from core.services.paperclip_admin_client import PaperclipAdminClient, PaperclipApiError

logger = logging.getLogger(__name__)


def _ws_gateway_url(env_name: str) -> str:
    return f"wss://ws-{env_name}.isol8.co" if env_name != "prod" else "wss://ws.isol8.co"


class PaperclipProvisioning:
    def __init__(self, admin_client: PaperclipAdminClient, repo: PaperclipRepo, env_name: str):
        self._admin = admin_client
        self._repo = repo
        self._env_name = env_name

    async def provision(self, *, user_id: str, email: str) -> PaperclipCompany:
        existing = self._repo.get(user_id)
        if existing and existing.status == "active":
            logger.info("paperclip_provisioning: %s already active, skipping", user_id)
            return existing

        now = datetime.now(timezone.utc)
        # 1. Create company (idempotent via key)
        try:
            company = await self._admin.create_company(
                name=email,
                owner_email=email,
                idempotency_key=f"company:{user_id}",
            )
            company_id = company["id"]
        except PaperclipApiError as e:
            self._mark_failed(user_id, f"create_company failed: {e}")
            raise

        # 2. Mint board API key
        try:
            key_resp = await self._admin.mint_board_api_key(
                company_id=company_id,
                user_email=email,
                name="isol8-proxy",
                idempotency_key=f"board-key:{user_id}",
            )
            board_token = key_resp["token"]
        except PaperclipApiError as e:
            self._mark_failed(user_id, f"mint_board_api_key failed: {e}")
            raise

        # 3. Mint OpenClaw service token
        svc_token = service_token.mint(user_id)

        # 4. Seed main agent with openclaw-gateway adapter
        try:
            await self._admin.create_agent(
                company_id=company_id,
                name="Main Agent",
                role="ceo",
                adapter_config={
                    "adapter": "openclaw-gateway",
                    "url": _ws_gateway_url(self._env_name),
                    "authToken": svc_token,
                    "sessionKeyStrategy": "fixed",
                    "sessionKey": user_id,
                },
                idempotency_key=f"agent:{user_id}",
            )
        except PaperclipApiError as e:
            self._mark_failed(user_id, f"create_agent failed: {e}")
            raise

        # 5. Persist
        company_record = PaperclipCompany(
            user_id=user_id,
            company_id=company_id,
            board_api_key_encrypted=encrypt(board_token),
            service_token_encrypted=encrypt(svc_token),
            status="active",
            created_at=now,
            updated_at=now,
        )
        self._repo.put(company_record)
        logger.info("paperclip_provisioning: %s active (company=%s)", user_id, company_id)
        return company_record

    async def disable(self, *, user_id: str, grace_days: int = 30) -> None:
        existing = self._repo.get(user_id)
        if not existing:
            return
        from datetime import timedelta
        purge_at = datetime.now(timezone.utc) + timedelta(days=grace_days)
        try:
            await self._admin.disable_company(company_id=existing.company_id)
        except PaperclipApiError as e:
            logger.warning("paperclip_provisioning.disable: API error (continuing): %s", e)
        self._repo.update_status(user_id, status="disabled", scheduled_purge_at=purge_at)

    async def purge(self, *, user_id: str) -> None:
        existing = self._repo.get(user_id)
        if not existing:
            return
        try:
            await self._admin.delete_company(company_id=existing.company_id)
        except PaperclipApiError as e:
            logger.warning("paperclip_provisioning.purge: API error (continuing): %s", e)
        self._repo.delete(user_id)

    def _mark_failed(self, user_id: str, reason: str) -> None:
        existing = self._repo.get(user_id)
        if existing:
            self._repo.update_status(user_id, status="failed", last_error=reason)
        else:
            now = datetime.now(timezone.utc)
            self._repo.put(PaperclipCompany(
                user_id=user_id,
                company_id="",
                board_api_key_encrypted="",
                service_token_encrypted="",
                status="failed",
                created_at=now,
                updated_at=now,
                last_error=reason,
            ))
```

- [ ] **Step 2: Write tests.**

```python
"""Tests for PaperclipProvisioning. Mocks admin client + repo with stand-ins."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone

from core.services.paperclip_provisioning import PaperclipProvisioning
from core.repositories.paperclip_repo import PaperclipCompany


@pytest.fixture(autouse=True)
def env_vars(monkeypatch):
    monkeypatch.setenv("PAPERCLIP_SERVICE_TOKEN_KEY", "test-key")
    monkeypatch.setenv("ENCRYPTION_KEY", "wHc3hAOcLlFzWyu3Ph7xIyClIdVQTrIzFOZDtu_pIEY=")  # Fernet 32-byte key b64url


@pytest.fixture
def admin_client():
    client = AsyncMock()
    client.create_company.return_value = {"id": "co_abc"}
    client.mint_board_api_key.return_value = {"token": "board-token-secret", "id": "key_1"}
    client.create_agent.return_value = {"id": "agent_1"}
    return client


@pytest.fixture
def repo():
    storage = {}
    repo = MagicMock()
    def get(uid): return storage.get(uid)
    def put(c): storage[c.user_id] = c
    def update_status(uid, **kwargs):
        if uid in storage:
            existing = storage[uid]
            for k, v in kwargs.items():
                setattr(existing, k, v)
    def delete(uid): storage.pop(uid, None)
    repo.get.side_effect = get
    repo.put.side_effect = put
    repo.update_status.side_effect = update_status
    repo.delete.side_effect = delete
    return repo


@pytest.mark.asyncio
async def test_provision_happy_path(admin_client, repo):
    p = PaperclipProvisioning(admin_client, repo, env_name="dev")
    result = await p.provision(user_id="user_123", email="u@example.com")
    assert result.status == "active"
    assert result.company_id == "co_abc"
    admin_client.create_company.assert_awaited_once()
    admin_client.mint_board_api_key.assert_awaited_once()
    admin_client.create_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_provision_idempotent_on_active(admin_client, repo):
    p = PaperclipProvisioning(admin_client, repo, env_name="dev")
    await p.provision(user_id="user_123", email="u@example.com")
    await p.provision(user_id="user_123", email="u@example.com")  # second call
    admin_client.create_company.assert_awaited_once()  # NOT called twice


@pytest.mark.asyncio
async def test_provision_failure_marks_failed_and_raises(admin_client, repo):
    from core.services.paperclip_admin_client import PaperclipApiError
    admin_client.create_company.side_effect = PaperclipApiError("boom", 503, "")
    p = PaperclipProvisioning(admin_client, repo, env_name="dev")
    with pytest.raises(PaperclipApiError):
        await p.provision(user_id="user_x", email="x@y.com")
    record = repo.get("user_x")
    assert record.status == "failed"
    assert "create_company failed" in record.last_error
```

- [ ] **Step 3: Commit.**

```bash
git add apps/backend/core/services/paperclip_provisioning.py apps/backend/tests/test_paperclip_provisioning.py
git commit -m "feat(backend): paperclip provisioning orchestrator

provision/disable/purge flows. Idempotent on user_id. Failures mark
repo status=failed and re-raise for webhook retry."
```

---

### Task 12: Webhook integration (Clerk + Stripe)

**Files:**
- Modify: `apps/backend/routers/webhooks.py`
- Modify: `apps/backend/core/config.py` (add Paperclip settings)

- [ ] **Step 1: Add settings to config.py.**

In `core/config.py`, inside the `Settings` class:

```python
# Paperclip integration
PAPERCLIP_INTERNAL_URL: str = ""              # e.g., http://paperclip.internal.isol8.local
PAPERCLIP_PUBLIC_URL: str = ""                # e.g., https://company.isol8.co
PAPERCLIP_ADMIN_TOKEN: str = ""               # populated from Secrets Manager at startup
PAPERCLIP_SERVICE_TOKEN_KEY: str = ""         # populated from Secrets Manager at startup
```

- [ ] **Step 2: Read existing webhook handlers to find where to plug in.**

```bash
grep -n "user.created\|user.deleted\|customer.subscription.deleted\|customer.subscription.canceled" apps/backend/routers/webhooks.py
```

- [ ] **Step 3: Add Paperclip provisioning call to Clerk `user.created`.**

```python
# In the user.created branch, after existing user creation:
from core.services.paperclip_provisioning import PaperclipProvisioning
from core.services.paperclip_admin_client import PaperclipAdminClient
from core.repositories.paperclip_repo import PaperclipRepo
import httpx

# Build provisioner (could be a FastAPI dependency for testability — match existing patterns)
async def _get_paperclip_provisioning() -> PaperclipProvisioning:
    http = httpx.AsyncClient(base_url=settings.PAPERCLIP_INTERNAL_URL, timeout=15.0)
    admin = PaperclipAdminClient(http_client=http, admin_token=settings.PAPERCLIP_ADMIN_TOKEN)
    repo = PaperclipRepo(table_name=f"isol8-{settings.ENVIRONMENT}-paperclip-companies")
    return PaperclipProvisioning(admin, repo, env_name=settings.ENVIRONMENT)

# In handle_user_created:
provisioning = await _get_paperclip_provisioning()
try:
    await provisioning.provision(user_id=user_id, email=email)
except Exception as e:
    logger.exception("paperclip provisioning failed for %s: %s", user_id, e)
    # Enqueue retry in pending-updates rather than 5xx-ing the entire webhook —
    # the user-creation path is the priority here. Cron will retry.
    pending_updates.enqueue("paperclip_provision", {"user_id": user_id, "email": email})
```

- [ ] **Step 4: Add disable call to Clerk `user.deleted` AND Stripe `customer.subscription.deleted`/`canceled`.**

```python
# Clerk user.deleted:
provisioning = await _get_paperclip_provisioning()
await provisioning.disable(user_id=user_id)

# Stripe webhook (in webhooks.py /webhooks/stripe handler), on subscription.deleted/canceled:
user_id = await user_repo.find_by_stripe_customer(event.customer)
if user_id:
    provisioning = await _get_paperclip_provisioning()
    await provisioning.disable(user_id=user_id)
```

- [ ] **Step 5: Commit.**

```bash
git add apps/backend/routers/webhooks.py apps/backend/core/config.py
git commit -m "feat(backend): provision Paperclip on Clerk user.created, disable on cancel

user.created → PaperclipProvisioning.provision (eager, async retry on failure).
user.deleted + Stripe subscription cancellation → disable with 30-day grace."
```

---

### Task 13: Cleanup cron extension

**Files:**
- Modify: `apps/backend/core/services/update_service.py`

- [ ] **Step 1: Read the existing scheduled worker.**

```bash
grep -n "run_scheduled_worker\|pending_updates\|sleep" apps/backend/core/services/update_service.py
```

- [ ] **Step 2: Add a once-per-day Paperclip purge step.**

```python
# Inside the scheduled worker loop (or as a separate periodic task):
async def _paperclip_purge_pass():
    from datetime import datetime, timezone
    from core.repositories.paperclip_repo import PaperclipRepo
    from core.config import settings

    repo = PaperclipRepo(table_name=f"isol8-{settings.ENVIRONMENT}-paperclip-companies")
    due = repo.scan_purge_due(datetime.now(timezone.utc))
    if not due:
        return
    provisioning = await _get_paperclip_provisioning()  # extract or import
    for company in due:
        try:
            await provisioning.purge(user_id=company.user_id)
            logger.info("paperclip purge: deleted %s", company.user_id)
        except Exception as e:
            logger.exception("paperclip purge failed for %s: %s", company.user_id, e)


# Schedule: call _paperclip_purge_pass once per loop iteration if last-run > 24h.
```

- [ ] **Step 3: Add a paperclip_provision retry to the same worker** (handles failed provisioning from Task 12).

```python
async def _paperclip_provision_retry_pass():
    """Retry paperclip provisioning rows that are stuck in status=failed."""
    # Fetch failed rows (small set; full scan acceptable for now)
    # ... iterate, call provisioning.provision(...), update status if success
```

- [ ] **Step 4: Commit.**

```bash
git add apps/backend/core/services/update_service.py
git commit -m "feat(backend): cleanup + retry pass for Paperclip in scheduled worker

Daily purge of disabled companies past their grace window.
Retry pass for status=failed provisioning rows."
```

---

## Phase 3 — Backend proxy

### Task 14: paperclip_proxy.py — HTTP forwarding + brand-rewrite

**Files:**
- Create: `apps/backend/routers/paperclip_proxy.py`
- Create: `apps/backend/tests/test_paperclip_proxy.py`

- [ ] **Step 1: Read `routers/control_ui_proxy.py` carefully — your proxy should mirror its session and proxy patterns where applicable.**

```bash
cat apps/backend/routers/control_ui_proxy.py
```

- [ ] **Step 2: Implement HTTP forwarding (no WebSocket yet — Task 15).**

```python
"""Reverse proxy for company.isol8.co → internal Paperclip server.

Validates Clerk session, looks up the user's encrypted Board API key,
injects Authorization: Bearer, streams the upstream response back.
HTML responses get a brand-rewrite pass.
"""
from __future__ import annotations

import logging
import re
from typing import AsyncIterator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from core.auth import AuthContext, get_current_user
from core.config import settings
from core.encryption import decrypt
from core.repositories.paperclip_repo import PaperclipRepo

logger = logging.getLogger(__name__)
router = APIRouter()

_HOP_BY_HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
}


def _filter_request_headers(req: Request) -> dict:
    out = {k: v for k, v in req.headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}
    out.pop("host", None)  # httpx sets this from base_url
    out.pop("authorization", None)  # we'll inject our own
    return out


def _filter_response_headers(headers: httpx.Headers) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in _HOP_BY_HOP_HEADERS}


_BRAND_REWRITES = [
    (re.compile(rb"<title>Paperclip</title>", re.IGNORECASE), b"<title>Isol8 Teams</title>"),
    (re.compile(rb'(<meta[^>]*property=["\']og:site_name["\'][^>]*content=["\'])Paperclip', re.IGNORECASE), rb"\1Isol8"),
]


def _brand_rewrite_html(body: bytes) -> bytes:
    out = body
    for pattern, replacement in _BRAND_REWRITES:
        out = pattern.sub(replacement, out)
    return out


def _get_repo() -> PaperclipRepo:
    return PaperclipRepo(table_name=f"isol8-{settings.ENVIRONMENT}-paperclip-companies")


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
)
async def proxy(
    path: str,
    request: Request,
    auth: AuthContext = Depends(get_current_user),
):
    repo = _get_repo()
    company = repo.get(auth.user_id)
    if not company or company.status != "active":
        raise HTTPException(
            status_code=503,
            detail="Your team workspace is being set up. Refresh in a moment.",
        )

    board_token = decrypt(company.board_api_key_encrypted)

    upstream_url = f"{settings.PAPERCLIP_INTERNAL_URL}/{path}"
    body = await request.body()

    async with httpx.AsyncClient(timeout=30.0) as client:
        upstream = await client.request(
            method=request.method,
            url=upstream_url,
            params=request.query_params,
            content=body,
            headers={
                **_filter_request_headers(request),
                "Authorization": f"Bearer {board_token}",
                "X-Forwarded-Host": request.headers.get("host", ""),
                "X-Forwarded-Proto": "https",
                "X-Forwarded-For": request.client.host if request.client else "",
            },
        )

    response_body = upstream.content
    content_type = upstream.headers.get("content-type", "")
    if "text/html" in content_type and response_body:
        try:
            response_body = _brand_rewrite_html(response_body)
        except Exception as e:
            logger.warning("brand-rewrite failed (passing through): %s", e)

    return Response(
        content=response_body,
        status_code=upstream.status_code,
        headers=_filter_response_headers(upstream.headers),
        media_type=content_type or None,
    )
```

- [ ] **Step 3: Write tests.**

```python
import pytest
import httpx
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

# Light approach: spin up app with overridden deps, mock httpx.AsyncClient via respx.

# (Detailed implementation depends on existing test fixtures in apps/backend/tests/conftest.py.
#  Read conftest to find how Clerk auth + DynamoDB are mocked there, then mirror.)


def test_brand_rewrite_html_replaces_title():
    from routers.paperclip_proxy import _brand_rewrite_html
    out = _brand_rewrite_html(b"<html><title>Paperclip</title></html>")
    assert b"<title>Isol8 Teams</title>" in out


def test_brand_rewrite_passes_through_non_html():
    from routers.paperclip_proxy import _brand_rewrite_html
    out = _brand_rewrite_html(b'{"data":"json"}')
    assert out == b'{"data":"json"}'


def test_brand_rewrite_idempotent():
    from routers.paperclip_proxy import _brand_rewrite_html
    once = _brand_rewrite_html(b"<title>Paperclip</title>")
    twice = _brand_rewrite_html(once)
    assert once == twice


# Full proxy round-trip integration test deferred to docker-compose integration tests.
```

- [ ] **Step 4: Add module-level circuit breaker** (per spec §6).

Add to `paperclip_proxy.py`:

```python
import time
from collections import deque

_FAILURE_WINDOW_SECONDS = 30
_FAILURE_THRESHOLD_PCT = 0.5
_OPEN_STATE_SECONDS = 60

_recent_5xx: deque[float] = deque(maxlen=200)
_recent_total: deque[float] = deque(maxlen=200)
_circuit_open_until: float = 0.0


def _record_outcome(status_code: int) -> None:
    now = time.time()
    _recent_total.append(now)
    if status_code >= 500:
        _recent_5xx.append(now)


def _circuit_open() -> bool:
    global _circuit_open_until
    now = time.time()
    if now < _circuit_open_until:
        return True
    cutoff = now - _FAILURE_WINDOW_SECONDS
    fives = sum(1 for t in _recent_5xx if t >= cutoff)
    total = sum(1 for t in _recent_total if t >= cutoff)
    if total >= 10 and (fives / total) >= _FAILURE_THRESHOLD_PCT:
        _circuit_open_until = now + _OPEN_STATE_SECONDS
        return True
    return False
```

In the `proxy()` handler, before reaching for httpx:

```python
if _circuit_open():
    return Response(
        content=b"<html><body><h1>Teams temporarily unavailable</h1><p>Try again in a minute.</p></body></html>",
        status_code=503,
        media_type="text/html",
    )
```

After receiving the upstream response:

```python
_record_outcome(upstream.status_code)
```

- [ ] **Step 5: Commit.**

```bash
git add apps/backend/routers/paperclip_proxy.py apps/backend/tests/test_paperclip_proxy.py
git commit -m "feat(backend): paperclip reverse proxy (HTTP) + circuit breaker

Clerk-validated, Board-API-key-injecting reverse proxy for HTTP traffic.
HTML responses get brand-rewrite. Failed-status users see a 503 onboarding page.
Circuit breaker opens for 60s if upstream 5xx rate > 50% in 30s window."
```

---

### Task 15: paperclip_proxy.py — WebSocket relay

**Files:**
- Modify: `apps/backend/routers/paperclip_proxy.py`

- [ ] **Step 1: Add a WebSocket route to the same router that bidirectionally relays frames.**

Append to `paperclip_proxy.py`:

```python
import asyncio
from fastapi import WebSocket, WebSocketDisconnect
from websockets import connect as ws_connect

@router.websocket("/{path:path}")
async def proxy_ws(websocket: WebSocket, path: str):
    # NOTE: WS routes can't depend on `Depends(get_current_user)` directly because
    # the auth context comes from cookies in the upgrade request. Validate manually.
    from core.auth import _decode_token  # private helper used same way in control_ui_proxy.py

    token = websocket.cookies.get("__session")  # adjust to actual Clerk cookie name
    if not token:
        await websocket.close(code=4401)
        return
    try:
        claims = _decode_token(token)
        user_id = claims["sub"]
    except Exception:
        await websocket.close(code=4401)
        return

    repo = _get_repo()
    company = repo.get(user_id)
    if not company or company.status != "active":
        await websocket.close(code=4503)
        return

    board_token = decrypt(company.board_api_key_encrypted)
    upstream_url = (
        settings.PAPERCLIP_INTERNAL_URL
        .replace("http://", "ws://")
        .replace("https://", "wss://")
        + f"/{path}"
    )

    await websocket.accept()

    try:
        async with ws_connect(
            upstream_url,
            additional_headers={"Authorization": f"Bearer {board_token}"},
        ) as upstream:
            async def client_to_upstream():
                try:
                    while True:
                        msg = await websocket.receive_text()
                        await upstream.send(msg)
                except WebSocketDisconnect:
                    return

            async def upstream_to_client():
                try:
                    async for msg in upstream:
                        if isinstance(msg, bytes):
                            await websocket.send_bytes(msg)
                        else:
                            await websocket.send_text(msg)
                except Exception:
                    return

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
```

- [ ] **Step 2: Commit.**

```bash
git add apps/backend/routers/paperclip_proxy.py
git commit -m "feat(backend): paperclip reverse proxy (WebSocket)

Bidirectional WS relay for Paperclip live-events. Auth via Clerk cookie
on the upgrade request, then Bearer-injection on the upstream connection."
```

---

### Task 16: Host-header middleware in main.py

**Files:**
- Modify: `apps/backend/main.py`

- [ ] **Step 1: Read existing main.py to find where routers are mounted.**

```bash
grep -n "include_router\|app =" apps/backend/main.py
```

- [ ] **Step 2: Add host-conditional routing.**

```python
# main.py — after existing app = FastAPI(...) and before mounting /api/v1 routers:
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

PAPERCLIP_PROXY_HOSTS = {
    "company.isol8.co",
    "company-dev.isol8.co",
    "company-staging.isol8.co",
    "company.localhost",  # local dev
}


class HostDispatcherMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        host = request.headers.get("host", "").split(":")[0].lower()
        if host in PAPERCLIP_PROXY_HOSTS:
            # Rewrite scope so the path lines up with the paperclip_proxy router
            request.scope["path"] = "/_paperclip_proxy" + request.scope["path"]
        return await call_next(request)


app.add_middleware(HostDispatcherMiddleware)

# Mount the paperclip proxy router at the rewritten prefix:
from routers.paperclip_proxy import router as paperclip_proxy_router
app.include_router(paperclip_proxy_router, prefix="/_paperclip_proxy")
```

> **Alternative simpler pattern:** if FastAPI's host-routing or sub-app mounting is already used elsewhere, prefer that. The middleware-rewrite approach above is one of several; check existing main.py for established patterns first.

- [ ] **Step 3: Commit.**

```bash
git add apps/backend/main.py
git commit -m "feat(backend): host-header dispatcher routes company.isol8.co to paperclip proxy

Backend handles api.isol8.co (existing) and company.isol8.co (NEW)
out of the same FastAPI app, dispatched by Host header."
```

---

## Phase 4 — Frontend

### Task 17: Add "Teams" link to chat sidebar

**Files:**
- Modify: `apps/frontend/src/components/chat/ChatLayout.tsx` (or the actual sidebar component — read it first)

- [ ] **Step 1: Find the existing sidebar nav structure.**

```bash
grep -rln "ChatLayout\|sidebar" apps/frontend/src/components/chat/ | head -5
cat apps/frontend/src/components/chat/ChatLayout.tsx | head -80
```

- [ ] **Step 2: Add a "Teams" link that opens `company.isol8.co` in a new tab.**

Locate the navigation list and add:

```tsx
// Determine company subdomain by env. NEXT_PUBLIC_COMPANY_URL injected at build time.
const companyUrl = process.env.NEXT_PUBLIC_COMPANY_URL ?? "https://company.isol8.co";

// Inside the sidebar nav JSX:
<a
  href={companyUrl}
  target="_self"
  rel="noopener"
  className="..."  // match sibling nav items
>
  <UsersIcon className="h-4 w-4" />
  <span>Teams</span>
</a>
```

- [ ] **Step 3: Add the env var to Vercel project config (per env).**

```bash
# Document the Vercel env var addition in apps/frontend/.env.example:
echo 'NEXT_PUBLIC_COMPANY_URL="https://company.isol8.co"' >> apps/frontend/.env.example
```

- [ ] **Step 4: (Optional, deferrable) Add a "Setting up your team workspace" step to `ProvisioningStepper.tsx`.**

The spec §4.3 mentions this as optional. Provisioning is eager and typically completes in 2–5 seconds inside the Clerk webhook, so the step is rarely visible. **Skip for v1** — only add if user testing reveals a noticeable gap. Add a follow-up issue so it isn't lost.

- [ ] **Step 5: Commit.**

```bash
git add apps/frontend/src/components/chat/ChatLayout.tsx apps/frontend/.env.example
git commit -m "feat(frontend): Teams link in chat sidebar

Opens company.isol8.co (per-env via NEXT_PUBLIC_COMPANY_URL).
User's Clerk session cookie is already scoped to .isol8.co so no re-auth."
```

---

## Phase 5 — Verification

### Task 18: Local end-to-end smoke test

**Files:**
- Create: `apps/backend/tests/integration/test_paperclip_smoke.py`

- [ ] **Step 1: Spin up Paperclip locally against an embedded Postgres + pgvector.**

```bash
docker run --rm -d --name paperclip-smoke \
  -e DATABASE_URL=postgres://paperclip:paperclip@host.docker.internal:5432/paperclip \
  -e PAPERCLIP_DEPLOYMENT_MODE=authenticated \
  -e PAPERCLIP_DEPLOYMENT_EXPOSURE=public \
  -e PAPERCLIP_PUBLIC_URL=http://localhost:3100 \
  -e BETTER_AUTH_SECRET=smoke-test-secret \
  -e PAPERCLIP_AUTH_DISABLE_SIGN_UP=true \
  -p 3100:3100 \
  paperclipai/paperclip:latest
```

(The plan assumes a local Postgres with pgvector is running on host port 5432. If not, also spin one up: `docker run --rm -d -p 5432:5432 -e POSTGRES_PASSWORD=paperclip -e POSTGRES_USER=paperclip -e POSTGRES_DB=paperclip pgvector/pgvector:pg16`.)

- [ ] **Step 2: Bootstrap an instance admin user manually** (or via Paperclip's `pnpm paperclipai onboard` if available).

```bash
# Read Paperclip's bootstrap docs for the actual mechanism:
grep -rn "instance_admin\|bootstrap\|first user" ~/Desktop/paperclip/doc/ | head
```

- [ ] **Step 3: Mint an admin Board API key and store as environment var.**

Document the exact CLI/HTTP commands here once Paperclip's admin endpoints are confirmed in Task 10. Treat this step as the source of truth for the production runbook.

- [ ] **Step 4: Run the provisioning flow end-to-end.**

```python
# tests/integration/test_paperclip_smoke.py
"""Skipped by default; run manually against a local Paperclip + Postgres."""
import os
import pytest
import httpx
import asyncio

pytestmark = pytest.mark.skipif(
    not os.environ.get("PAPERCLIP_SMOKE_LOCAL"),
    reason="set PAPERCLIP_SMOKE_LOCAL=1 with local Paperclip running",
)


@pytest.mark.asyncio
async def test_provision_smoke():
    from core.services.paperclip_admin_client import PaperclipAdminClient
    from core.services.paperclip_provisioning import PaperclipProvisioning
    from core.repositories.paperclip_repo import PaperclipRepo

    http = httpx.AsyncClient(base_url="http://localhost:3100", timeout=15.0)
    admin = PaperclipAdminClient(http_client=http, admin_token=os.environ["PAPERCLIP_ADMIN_TOKEN"])
    repo = PaperclipRepo(table_name="isol8-local-paperclip-companies")
    p = PaperclipProvisioning(admin, repo, env_name="local")

    result = await p.provision(user_id="smoke_user", email="smoke@example.com")
    assert result.status == "active"
    assert result.company_id

    # Verify the proxy can use the minted Board API key to fetch a Paperclip page
    headers = {"Authorization": f"Bearer {result.board_api_key_encrypted}"}  # decrypt in real test
    resp = await http.get("/api/agents/me", headers=headers)
    # Or any company-scoped endpoint that should succeed for a board user
```

- [ ] **Step 5: Verify the OpenClaw gateway adapter wiring** — manually create a chat run inside the Paperclip UI and confirm the agent successfully reaches your local OpenClaw container via the gateway WebSocket.

- [ ] **Step 6: Commit (test file + smoke runbook).**

```bash
git add apps/backend/tests/integration/test_paperclip_smoke.py
git commit -m "test(backend): paperclip end-to-end smoke test (skipped by default)

Manual gate: run with PAPERCLIP_SMOKE_LOCAL=1 against a local Paperclip
+ Postgres. Validates the full provision → proxy → agent run path."
```

---

### Task 19: Run full test suite + lint

- [ ] **Step 1: Run backend pytest suite.**

```bash
cd apps/backend && uv run pytest tests/ -v --tb=short
```

Expected: all tests pass. If any fail, identify whether the failure is in the new code (fix it) or in pre-existing code (note + ask user).

- [ ] **Step 2: Run frontend tests + lint.**

```bash
cd apps/frontend && pnpm run lint && pnpm test
```

- [ ] **Step 3: Run CDK synth on dev to confirm infra compiles.**

```bash
cd apps/infra && pnpm cdk synth dev/* 2>&1 | tail -20
```

- [ ] **Step 4: Run turbo across the repo.**

```bash
turbo run test lint
```

- [ ] **Step 5: If anything failed, stop and triage with the user before proceeding to deploy.**

No commit for this task.

---

### Task 20: Deploy + manual verification checklist

This task is ungated — wait for explicit user approval before pushing or deploying anything.

- [ ] **Step 1: Push the branch.**

```bash
git push -u origin feat/paperclip-rebuild
```

- [ ] **Step 2: Open a PR (do NOT merge).**

```bash
gh pr create --base main --title "feat: Paperclip rebuild — Paperclip-as-a-Service" \
  --body "$(cat <<'EOF'
## Summary

Rebuild of Paperclip integration following the architecture in
`docs/superpowers/specs/2026-04-27-paperclip-rebuild-design.md`.

Replaces (and supersedes) PR #186, which is parked in draft.

## Test plan

- [ ] CDK synth passes for dev + prod stages
- [ ] `paperclip_admin_client` unit tests pass against MockTransport
- [ ] `paperclip_provisioning` unit tests pass with mocked admin client + repo
- [ ] `paperclip_repo` round-trip tests pass against moto DynamoDB
- [ ] `service_token` mint/verify round-trip + tampered-token rejection passes
- [ ] Local smoke test (PAPERCLIP_SMOKE_LOCAL=1) provisions a company and reaches the proxy
- [ ] After dev deploy: company-dev.isol8.co loads Paperclip UI for a signed-in user
- [ ] After dev deploy: a Paperclip agent run reaches the user's OpenClaw container

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Watch CI.**

```bash
gh run watch --exit-status
```

- [ ] **Step 4: Deploy CDK to dev (after CI is green and user approves).**

```bash
cd apps/infra && pnpm cdk deploy dev/* --require-approval never
```

- [ ] **Step 5: Run the migrations one-shot task** (per `apps/infra/paperclip/RUNBOOK.md`).

- [ ] **Step 6: Bootstrap the instance admin Board API key** and store it in Secrets Manager:

```bash
# (Exact command depends on Paperclip's first-run admin claim flow — see
#  ~/Desktop/paperclip/doc/DEPLOYMENT-MODES.md §7 "Local Trusted -> Authenticated Claim Flow")
aws secretsmanager put-secret-value \
  --secret-id isol8-dev-paperclip-admin-board-key \
  --secret-string "<minted-token>" \
  --profile isol8-admin --region us-east-1
```

- [ ] **Step 7: Deploy backend** (force a new ECS deployment so it picks up new env vars).

```bash
gh workflow run backend.yml --ref feat/paperclip-rebuild
gh run watch --exit-status
```

- [ ] **Step 8: Manual verification checklist on dev.**

- [ ] Sign up a new test user via Clerk → confirm `paperclip-companies` row appears with `status=active`
- [ ] As that user, navigate to `https://company-dev.isol8.co` → see the Paperclip UI with brand-rewritten title
- [ ] Inside Paperclip, find the seeded "Main Agent" with adapter=openclaw-gateway
- [ ] Trigger an agent run → confirm it reaches the user's OpenClaw container (check container logs)
- [ ] Cancel the user's Stripe subscription → confirm `paperclip-companies` row flips to `status=disabled`, `scheduled_purge_at` set 30 days out
- [ ] Resubscribe within grace → confirm provisioning resumes (idempotent)
- [ ] CloudWatch: confirm Paperclip task is healthy, Aurora idle ACU > 0 only during active windows

- [ ] **Step 9: Park PR until ready for prod cutover.** Mark approved on dev; coordinate prod deploy with a user-approved deploy window (Stripe billing path is on the line).

---

## Open verification points (from spec §8)

These are the four discovery items the spec called out. Resolve them as part of executing the relevant task, NOT as separate tasks:

1. **Paperclip admin API surface** — Resolved during Task 10. If the assumed endpoints don't exist, update both the client and provisioning service.
2. **`openclaw-gateway` adapter dynamic `authToken`** — Resolved during Task 18 smoke test. Confirm an agent created with `authToken=<svc_token>` actually authenticates against our Lambda Authorizer.
3. **Aurora Serverless v2 + pgvector availability** — Resolved during Task 1 + Task 5. If `CREATE EXTENSION vector` fails on the cluster, switch to a region/engine version that supports it.
4. **Service-token format/TTL** — Resolved during Task 9. Plan defaults to HS256 + 1-year expiry + jti for revocation.

---

## What this plan does NOT cover

- Any custom Isol8-branded React UI for Paperclip features (deferred to v2).
- Annual / discount pricing for the Paperclip-included tier (deferred to v2 of the flat-fee spec).
- Cross-company collaboration or multi-org per Isol8 user (the Isol8 invariant `single-org-per-user` holds).
- Mobile-app access to Paperclip (deferred).
- Custom domain support (`*.isol8.co` only for v1).
