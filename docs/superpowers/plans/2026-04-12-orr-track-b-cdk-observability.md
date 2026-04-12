# ORR Track B: CDK Observability + IAM Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the CDK observability stack (SNS, 65 alarms, dashboard, 3 canaries), tighten IAM, enable AWS-account hardening (GuardDuty, Access Analyzer, Budgets), and clean up dead infrastructure.

**Architecture:** New `ObservabilityStack` in CDK consumes references from existing stacks. Uses a helper method to stamp out alarms from a flat definition array. All metric names reference the master spec taxonomy exactly. Canary code lives in `apps/infra/canaries/`.

**Tech Stack:** TypeScript, AWS CDK v2 (aws-cdk-lib 2.190.0), CloudWatch, SNS, Synthetics, GuardDuty, IAM Access Analyzer, AWS Budgets

**Spec:** `docs/superpowers/specs/2026-04-11-orr-track-b-cdk-observability-design.md`
**Master spec:** `docs/superpowers/specs/2026-04-11-operational-readiness-review-design.md` (alarm catalog in section 7)

---

### Task 1: Create ObservabilityStack skeleton + SNS topics

**Files:**
- Create: `apps/infra/lib/stacks/observability-stack.ts`

- [ ] **Step 1: Read existing stacks to understand patterns**

Read `apps/infra/lib/stacks/service-stack.ts` and `apps/infra/lib/app.ts` (NOT `bin/app.ts`) to understand the stack constructor patterns, how props are typed, and how stacks reference each other.

Also read `apps/infra/lib/isol8-stage.ts` and `apps/infra/lib/local-stage.ts` to understand how stacks are wired into stages.

- [ ] **Step 2: Create the stack file with SNS topics**

```typescript
// apps/infra/lib/stacks/observability-stack.ts
import * as cdk from "aws-cdk-lib";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as cloudwatch_actions from "aws-cdk-lib/aws-cloudwatch-actions";
import * as sns from "aws-cdk-lib/aws-sns";
import * as subs from "aws-cdk-lib/aws-sns-subscriptions";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import { Construct } from "constructs";

// Import stack types for props
import { ServiceStack } from "./service-stack";
import { ApiStack } from "./api-stack";
import { DatabaseStack } from "./database-stack";
import { ContainerStack } from "./container-stack";

interface ObservabilityStackProps extends cdk.StackProps {
  envName: string;
  serviceStack: ServiceStack;
  apiStack: ApiStack;
  databaseStack: DatabaseStack;
  containerStack: ContainerStack;
}

export class ObservabilityStack extends cdk.Stack {
  public readonly pageTopic: sns.Topic;
  public readonly warnTopic: sns.Topic;
  private readonly envName: string;

  constructor(scope: Construct, id: string, props: ObservabilityStackProps) {
    super(scope, id, props);
    this.envName = props.envName;

    // Page tier: SMS + email
    this.pageTopic = new sns.Topic(this, "AlertsPage", {
      topicName: `isol8-${props.envName}-alerts-page`,
      displayName: "Isol8 Page",
    });

    // Read on-call phone from Secrets Manager
    const oncallPhoneSecret = secretsmanager.Secret.fromSecretNameV2(
      this, "OncallPhone",
      `isol8/${props.envName}/oncall/phone`,
    );
    // Email subscription (always)
    this.pageTopic.addSubscription(
      new subs.EmailSubscription(`oncall@isol8.co`),
    );

    // Warn tier: email only (Slack TODO)
    this.warnTopic = new sns.Topic(this, "AlertsWarn", {
      topicName: `isol8-${props.envName}-alerts-warn`,
      displayName: "Isol8 Warn",
    });
    this.warnTopic.addSubscription(
      new subs.EmailSubscription(`alerts@isol8.co`),
    );

    // Build alarms, dashboard, canaries (subsequent tasks)
    this.createAlarms(props);
    this.createDashboard(props);
  }

  // Alarm helper and alarm definitions go here (Task 2-5)
  private createAlarms(props: ObservabilityStackProps) {}
  private createDashboard(props: ObservabilityStackProps) {}
}
```

- [ ] **Step 3: Commit skeleton**

```bash
git add apps/infra/lib/stacks/observability-stack.ts
git commit -m "feat(infra): add ObservabilityStack skeleton with SNS topics"
```

---

### Task 2: Add alarm helper + page-tier alarms (P1-P11)

**Files:**
- Modify: `apps/infra/lib/stacks/observability-stack.ts`

- [ ] **Step 1: Add the alarm creation helper**

```typescript
private createSingleAlarm(def: {
  id: string;
  name: string;
  metricName: string;
  namespace?: string;
  statistic?: string;
  threshold: number;
  evaluationPeriods: number;
  periodMinutes: number;
  comparisonOperator: cloudwatch.ComparisonOperator;
  treatMissingData?: cloudwatch.TreatMissingData;
  dimensions?: Record<string, string>;
  severity: "page" | "warn";
  description: string;
}): cloudwatch.Alarm {
  // Auto-inject env and service dimensions to match EMF emitter
  const dimensions = {
    env: this.envName,
    service: "isol8-backend",
    ...(def.dimensions ?? {}),
  };

  const metric = new cloudwatch.Metric({
    namespace: def.namespace ?? "Isol8",
    metricName: def.metricName,
    statistic: def.statistic ?? "Sum",
    period: cdk.Duration.minutes(def.periodMinutes),
    dimensionsMap: dimensions,
  });

  const alarm = new cloudwatch.Alarm(this, def.id, {
    alarmName: `isol8-${this.envName}-${def.id}-${def.name}`,
    alarmDescription: def.description,
    metric,
    threshold: def.threshold,
    evaluationPeriods: def.evaluationPeriods,
    comparisonOperator: def.comparisonOperator,
    treatMissingData: def.treatMissingData ?? cloudwatch.TreatMissingData.NOT_BREACHING,
  });

  alarm.addAlarmAction(
    new cloudwatch_actions.SnsAction(
      def.severity === "page" ? this.pageTopic : this.warnTopic,
    ),
  );

  return alarm;
}
```

- [ ] **Step 2: Define all 11 page-tier alarms in `createAlarms`**

Use master spec §7.1 verbatim for metric names and thresholds. Example for P1:

```typescript
this.createSingleAlarm({
  id: "P1", name: "container-error-state",
  metricName: "container.error_state",
  threshold: 0, evaluationPeriods: 1, periodMinutes: 1,
  comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
  severity: "page",
  description: "Per-user OpenClaw container in stuck/error state",
});
```

Repeat for P2-P6 (same pattern: threshold 0, 1 period, 1 min).

For P7 (heartbeat absence): use `treatMissingData: cloudwatch.TreatMissingData.BREACHING`.

For P8 (dynamodb throttle): `evaluationPeriods: 2` (2 consecutive minutes).

For P9 and P10 (ALB/APIGW 5xx rate): use `cloudwatch.MathExpression` — these are AWS-native metrics, not custom. Don't add `env`/`service` dimensions. Use the ALB/API GW namespace and metric names directly.

P11 (chat canary) is added in Task 7 (after canary is created).

- [ ] **Step 3: Commit**

```bash
git add apps/infra/lib/stacks/observability-stack.ts
git commit -m "feat(infra): add alarm helper + 11 page-tier alarms"
```

---

### Task 3: Add warn-tier custom metric alarms (W1-W27)

**Files:**
- Modify: `apps/infra/lib/stacks/observability-stack.ts`

- [ ] **Step 1: Add all 27 warn-tier custom metric alarms**

Follow master spec §7.2. Each alarm uses the same `createSingleAlarm` helper with `severity: "warn"`. Use metric math expressions for rate-based alarms (W1, W8, W10, W18).

Example for W9 (chat latency p99):
```typescript
this.createSingleAlarm({
  id: "W9", name: "chat-e2e-latency-p99",
  metricName: "chat.e2e.latency",
  statistic: "p99",
  threshold: 20000, evaluationPeriods: 1, periodMinutes: 5,
  comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
  severity: "warn",
  description: "Chat p99 latency exceeds 20s SLO target",
});
```

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(infra): add 27 warn-tier custom metric alarms"
```

---

### Task 4: Add warn-tier AWS-native alarms (W28-W48) + cost alarms (W49-W51)

**Files:**
- Modify: `apps/infra/lib/stacks/observability-stack.ts`

- [ ] **Step 1: Add infrastructure alarms**

These use AWS-native namespaces (`AWS/ApplicationELB`, `AWS/ApiGateway`, `AWS/ECS`, `AWS/DynamoDB`, `AWS/EFS`, `AWS/Bedrock`). Do NOT add `env`/`service` dimensions — those are only for custom `Isol8` namespace metrics.

Get resource identifiers (ALB ARN, cluster name, table names, etc.) from stack props.

For W39 (Fargate TaskStopped): create an EventBridge rule that captures `aws.ecs` `Task State Change` events with `lastStatus: "STOPPED"`, targets a custom CloudWatch metric, then alarm on that metric.

- [ ] **Step 2: Add budget alarms (W49a + W49b)**

```typescript
import * as budgets from "aws-cdk-lib/aws-budgets";

// W49a: 80% warning
new budgets.CfnBudget(this, "MonthlyBudgetWarn", {
  budget: {
    budgetType: "COST",
    timeUnit: "MONTHLY",
    budgetLimit: { amount: 500, unit: "USD" },  // Check current spend first
    budgetName: `isol8-${this.envName}-monthly`,
  },
  notificationsWithSubscribers: [{
    notification: {
      notificationType: "ACTUAL",
      comparisonOperator: "GREATER_THAN",
      threshold: 80,
      thresholdType: "PERCENTAGE",
    },
    subscribers: [{ subscriptionType: "EMAIL", address: "alerts@isol8.co" }],
  }, {
    notification: {
      notificationType: "ACTUAL",
      comparisonOperator: "GREATER_THAN",
      threshold: 100,
      thresholdType: "PERCENTAGE",
    },
    subscribers: [{ subscriptionType: "EMAIL", address: "oncall@isol8.co" }],
  }],
});
```

W50 and W51: use CloudWatch Anomaly Detection on Bedrock and NAT GW cost metrics.

- [ ] **Step 3: Commit**

```bash
git commit -am "feat(infra): add AWS-native + cost alarms"
```

---

### Task 5: Add CloudWatch dashboard

**Files:**
- Modify: `apps/infra/lib/stacks/observability-stack.ts`

- [ ] **Step 1: Build the dashboard with ~30 widgets**

```typescript
private createDashboard(props: ObservabilityStackProps) {
  const dashboard = new cloudwatch.Dashboard(this, "OrrDashboard", {
    dashboardName: `isol8-${this.envName}-orr`,
  });

  // Row 1: SLOs (2 widgets)
  dashboard.addWidgets(
    new cloudwatch.GraphWidget({
      title: "Chat success rate (SLO: 99.5%)",
      left: [new cloudwatch.MathExpression({
        expression: "100 * (1 - errors / total)",
        usingMetrics: {
          errors: new cloudwatch.Metric({ namespace: "Isol8", metricName: "chat.error", statistic: "Sum", dimensionsMap: { env: this.envName, service: "isol8-backend" } }),
          total: new cloudwatch.Metric({ namespace: "Isol8", metricName: "chat.message.count", statistic: "Sum", dimensionsMap: { env: this.envName, service: "isol8-backend" } }),
        },
        period: cdk.Duration.hours(1),
      })],
      width: 12, height: 6,
    }),
    new cloudwatch.GraphWidget({
      title: "Chat p99 latency (SLO: <20s)",
      left: [new cloudwatch.Metric({ namespace: "Isol8", metricName: "chat.e2e.latency", statistic: "p99", dimensionsMap: { env: this.envName, service: "isol8-backend" } })],
      width: 12, height: 6,
    }),
  );

  // Row 2-6: Add widgets for containers, gateways, channels, billing, auth, infra, cost
  // Follow the same pattern — one GraphWidget per metric group
}
```

Fill in all ~30 widgets. Group by domain as outlined in Track B spec §6.

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(infra): add CloudWatch dashboard with SLO + domain widgets"
```

---

### Task 6: Create `/health` canary

**Files:**
- Modify: `apps/infra/lib/stacks/observability-stack.ts`

- [ ] **Step 1: Add the health canary**

```typescript
import * as synthetics from "aws-cdk-lib/aws-synthetics";

const healthCanary = new synthetics.Canary(this, "HealthCanary", {
  canaryName: `isol8-${this.envName}-health`,
  schedule: synthetics.Schedule.rate(cdk.Duration.minutes(1)),
  test: synthetics.Test.custom({
    code: synthetics.Code.fromInline(`
      const https = require('https');
      exports.handler = async () => {
        return new Promise((resolve, reject) => {
          const req = https.get('https://api-${this.envName}.isol8.co/health', (res) => {
            if (res.statusCode !== 200) {
              reject(new Error('Expected 200, got ' + res.statusCode));
            } else {
              resolve();
            }
          });
          req.on('error', reject);
        });
      };
    `),
    handler: "index.handler",
  }),
  runtime: synthetics.Runtime.SYNTHETICS_NODEJS_PUPPETEER_7_0,
  // Verify the latest runtime: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Synthetics_Canaries_Library.html
});
```

Add alarm W52 on canary failure.

- [ ] **Step 2: Commit**

```bash
git commit -am "feat(infra): add /health synthetic canary"
```

---

### Task 7: Create chat round-trip canary

**Files:**
- Create: `apps/infra/canaries/chat-roundtrip/index.js`
- Modify: `apps/infra/lib/stacks/observability-stack.ts`

- [ ] **Step 1: Write the canary script**

```javascript
// apps/infra/canaries/chat-roundtrip/index.js
const https = require('https');
const { SecretsManagerClient, GetSecretValueCommand } = require('@aws-sdk/client-secrets-manager');
const WebSocket = require('ws');

const sm = new SecretsManagerClient({});

exports.handler = async () => {
  // 1. Get credentials from Secrets Manager
  const secretName = process.env.CANARY_CREDENTIALS_SECRET;
  const { SecretString } = await sm.send(new GetSecretValueCommand({ SecretId: secretName }));
  const { email, password, agent_id } = JSON.parse(SecretString);

  // 2. Sign in to Clerk (dev sign-in API)
  // ... implementation depends on Clerk's API

  // 3. Open WebSocket, send ping, await response
  // ... WebSocket connect + message + assert final within 20s

  // 4. Clean up
  console.log('Chat round-trip canary passed');
};
```

The full implementation requires understanding Clerk's dev sign-in API and the WebSocket message format. The teammate should read `apps/backend/routers/websocket_chat.py` for the expected message format and `apps/frontend/src/hooks/useGateway.tsx` for the WebSocket connection pattern.

- [ ] **Step 2: Wire into CDK and add alarm P11**

```typescript
const chatCanary = new synthetics.Canary(this, "ChatRoundTripCanary", {
  canaryName: `isol8-${this.envName}-chat-rt`,
  schedule: synthetics.Schedule.rate(cdk.Duration.minutes(15)),
  test: synthetics.Test.custom({
    code: synthetics.Code.fromAsset("canaries/chat-roundtrip"),
    handler: "index.handler",
  }),
  environmentVariables: {
    CANARY_CREDENTIALS_SECRET: `isol8/${this.envName}/canary/credentials`,
    CANARY_WS_URL: `wss://ws-${this.envName}.isol8.co/`,
  },
});
```

- [ ] **Step 3: Commit**

```bash
git add apps/infra/canaries/ apps/infra/lib/stacks/observability-stack.ts
git commit -m "feat(infra): add chat round-trip canary with P11 alarm"
```

---

### Task 8: Wire stack into stages + add ALERT_PAGE_TOPIC_ARN to service

**Files:**
- Modify: `apps/infra/lib/isol8-stage.ts`
- Modify: `apps/infra/lib/local-stage.ts`
- Modify: `apps/infra/lib/stacks/service-stack.ts`

- [ ] **Step 1: Read the stage files to understand the pattern**

- [ ] **Step 2: Add ObservabilityStack to both stages**

```typescript
import { ObservabilityStack } from "./stacks/observability-stack";

// After service and api stacks:
const observability = new ObservabilityStack(this, "observability", {
  env: stackEnv,
  envName,
  serviceStack: service,
  apiStack: api,
  databaseStack: database,
  containerStack: container,
});
```

- [ ] **Step 3: Add ALERT_PAGE_TOPIC_ARN to service stack**

In `service-stack.ts`, find the ECS task definition container environment variables and add:

```typescript
environment: {
  // ... existing env vars ...
  ALERT_PAGE_TOPIC_ARN: props.observabilityStack?.pageTopic.topicArn ?? "",
},
```

This requires adding `observabilityStack` to the ServiceStack props (or passing the topic ARN as a CfnOutput/import). Handle the circular dependency carefully — if service depends on observability which depends on service, use a stack output + import instead.

- [ ] **Step 4: Commit**

```bash
git add apps/infra/lib/
git commit -m "feat(infra): wire ObservabilityStack into stages + pass page topic ARN to service"
```

---

### Task 9: IAM tightening in service-stack.ts

**Files:**
- Modify: `apps/infra/lib/stacks/service-stack.ts`

- [ ] **Step 1: Read the current IAM grants**

Read `service-stack.ts` and identify each grant listed in Track B spec §8.

- [ ] **Step 2: Tighten each grant**

For each item, read the current code, apply the minimal-scope fix from the spec. Specifically:

1. **ECS (~lines 159-179):** add resource constraint to task definition ARN + service name pattern
2. **Secrets Manager (~lines 205-217):** replace wildcard with per-secret grants
3. **DynamoDB (~lines 219-226):** add `LeadingKeys` condition where applicable
4. **Cloud Map (~lines 282-295):** constrain to namespace ARN
5. **KMS (~lines 297-309):** constrain to AuthStack key ARN
6. **S3 (~lines 363-376):** keep bucket-level grant, add comment explaining why per-user scoping via IAM variables isn't feasible

- [ ] **Step 3: Run `cdk diff` to review changes**

```bash
cd apps/infra && npx cdk diff 'dev/*' 2>&1 | head -200
```

Review for any unexpected removals.

- [ ] **Step 4: Commit**

```bash
git add apps/infra/lib/stacks/service-stack.ts
git commit -m "security(infra): tighten IAM grants per #190 §3 item 10"
```

---

### Task 10: GuardDuty + Access Analyzer + cleanup

**Files:**
- Modify: `apps/infra/lib/stacks/observability-stack.ts`
- Delete: `apps/terraform/` (if it exists)
- Create: `docs/ops/setup-oncall.md`
- Create: `docs/ops/setup-canary.md`

- [ ] **Step 1: Add GuardDuty and Access Analyzer to observability stack**

```typescript
import * as guardduty from "aws-cdk-lib/aws-guardduty";
import * as accessanalyzer from "aws-cdk-lib/aws-accessanalyzer";

new guardduty.CfnDetector(this, "GuardDuty", {
  enable: true,
  findingPublishingFrequency: "FIFTEEN_MINUTES",
});

new accessanalyzer.CfnAnalyzer(this, "AccessAnalyzer", {
  type: "ACCOUNT",
  analyzerName: `isol8-${this.envName}-access-analyzer`,
});
```

- [ ] **Step 2: Delete `apps/terraform/` if it exists**

```bash
rm -rf apps/terraform/
```

Check `pnpm-workspace.yaml` and `turbo.json` for references and remove.

- [ ] **Step 3: Write setup docs**

Create `docs/ops/setup-oncall.md` with instructions for creating the Secrets Manager phone secret.

Create `docs/ops/setup-canary.md` with instructions for creating the canary Clerk account and storing credentials.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(infra): add GuardDuty + Access Analyzer, delete terraform dir, add setup docs"
```

---

### Task 11: Snapshot tests + final validation

**Files:**
- Create: `apps/infra/test/observability-stack.test.ts`

- [ ] **Step 1: Write CDK snapshot test**

```typescript
import * as cdk from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { ObservabilityStack } from "../lib/stacks/observability-stack";
// ... mock props

test("ObservabilityStack creates expected resources", () => {
  // ... construct stack with mock props
  const template = Template.fromStack(stack);
  template.resourceCountIs("AWS::SNS::Topic", 2);
  template.resourceCountIs("AWS::CloudWatch::Alarm", 65);
  template.resourceCountIs("AWS::CloudWatch::Dashboard", 1);
});
```

- [ ] **Step 2: Run CDK synth + tests**

```bash
cd apps/infra && npx cdk synth && npm test
```

- [ ] **Step 3: Run lint**

```bash
cd apps/infra && npm run lint
```

- [ ] **Step 4: Final commit**

```bash
git add -A
git commit -m "test(infra): add ObservabilityStack snapshot tests, synth passes"
```

- [ ] **Step 5: Report to lead**

SendMessage to the team lead with branch name, summary, test results, any deviations.
