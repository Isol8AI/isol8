# ORR Track B — CDK Observability + IAM Hardening Design

**Status:** Draft
**Date:** 2026-04-11
**Master spec:** [2026-04-11-operational-readiness-review-design.md](./2026-04-11-operational-readiness-review-design.md)
**Parent issue:** Isol8AI/isol8#190
**Branch:** `worktree-track-b-cdk-infra` (when teammate runs)

---

## 1. Goal

Build the CDK observability stack: SNS topics, alarms, dashboards, metric filters, and synthetic canaries. Tighten IAM in the existing service stack (#190 §3 item 10). Enable AWS-account hardening (GuardDuty, Access Analyzer, AWS Budgets). Add a TTL to the `pending-updates` DynamoDB table. Delete the empty `apps/terraform/` directory.

**Does not touch backend code or frontend.** All work is in `apps/infra/`.

The success criterion: after this track ships, all 64 alarms from master spec §7 exist in CloudWatch in the `OK` state (or `Insufficient data` until Track A emits the underlying metric), the dashboard renders cleanly, and a manual SNS publish to the page topic delivers an SMS to the on-call phone.

## 2. Reads (do not duplicate)

- [Master spec §5](./2026-04-11-operational-readiness-review-design.md#5-severity-tiers) — SNS topics & subscriptions
- [Master spec §6.3](./2026-04-11-operational-readiness-review-design.md#63-full-metric-catalog) — Metric names to alarm against
- [Master spec §7](./2026-04-11-operational-readiness-review-design.md#7-alarm-catalog) — All 64 alarm definitions
- [Master spec §9](./2026-04-11-operational-readiness-review-design.md#9-synthetic-canaries) — Canary specs
- Issue #190 §3 item 10 — IAM tightening checklist
- Existing CDK stacks: `apps/infra/lib/stacks/{auth,network,database,container,service,api}-stack.ts`

**Do not redefine alarm thresholds.** They are frozen in the master spec §7. If a threshold needs to change mid-implementation, update the master spec and SendMessage the lead.

## 3. Architecture

### 3.1 New stack: `ObservabilityStack`

```
apps/infra/lib/stacks/observability-stack.ts
```

Single new CDK stack containing:

- 2 SNS topics (`isol8-{env}-alerts-page`, `isol8-{env}-alerts-warn`)
- 65 `cloudwatch.Alarm` constructs (W49 is 2 CDK constructs: 80% warn + 100% page)
- 1 `cloudwatch.Dashboard`
- Log metric filters (for any legacy unstructured log patterns)
- 3 CloudWatch Synthetics canaries (`/health`, chat round-trip, Stripe webhook replay)
- Subscriptions on the SNS topics:
  - `EmailSubscription` for both topics
  - `SmsSubscription` for the page topic, fed from a Secrets Manager value

The stack consumes references from existing stacks (cluster ARN, log group, ALB, API GW, DynamoDB tables, EFS file system) via stack props.

**Important:** Track B must also add the page topic ARN as an environment variable (`ALERT_PAGE_TOPIC_ARN`) to the service stack's ECS task definition (in `service-stack.ts`), so the backend can publish SNS notifications from code (e.g., Track C's fleet-patch audit alert). This is a cross-stack output from observability → service.

### 3.2 Stack dependency graph

**7 existing stacks** (not 6 — `dns-stack.ts` was missed in the original audit):

```
auth → {dns, network} → {database, container} → {api, service}
```

New, added at the end:
```
{api, service} → observability
```

Note: `api` and `service` are independent of each other (both depend on earlier stacks but not on each other). `observability` depends on both.

### 3.3 Wiring in `apps/infra/lib/app.ts`

**Note:** the CDK entry point is `apps/infra/lib/app.ts` (NOT `bin/app.ts`). Stage files are at `apps/infra/lib/isol8-stage.ts` and `apps/infra/lib/local-stage.ts` (NOT in a `stages/` subdirectory).

Add the new stack to both stages:

```typescript
const observability = new ObservabilityStack(this, 'observability', {
  env: stackEnv,
  envName,
  serviceStack: service,
  apiStack: api,
  databaseStack: database,
  containerStack: container,
});
```

## 4. SNS topics & subscriptions

### 4.1 Page topic

```typescript
const pageTopic = new sns.Topic(this, 'AlertsPage', {
  topicName: `isol8-${envName}-alerts-page`,
  displayName: 'Isol8 Page',
});

// Email subscription
pageTopic.addSubscription(new subs.EmailSubscription('oncall@<your-domain>'));

// SMS subscription — phone number from Secrets Manager
const oncallPhoneSecret = secretsmanager.Secret.fromSecretNameV2(
  this, 'OncallPhone',
  `isol8/${envName}/oncall/phone`,
);
pageTopic.addSubscription(new subs.SmsSubscription(
  oncallPhoneSecret.secretValueFromJson('phone').unsafeUnwrap()
));
```

**Note on the unsafe unwrap:** SMS subscription requires a literal string at synth time. Stored in Secrets Manager so it's not in code; the unwrap happens during synth, the resulting CloudFormation has the phone number inline. Acceptable trade-off — the secret only ever lives in CFN templates that are deployed by trusted IAM, and the SMS subscription itself doesn't expose the number externally.

### 4.2 Warn topic

```typescript
const warnTopic = new sns.Topic(this, 'AlertsWarn', {
  topicName: `isol8-${envName}-alerts-warn`,
  displayName: 'Isol8 Warn',
});

warnTopic.addSubscription(new subs.EmailSubscription('alerts@<your-domain>'));

// TODO: when Slack workspace is set up, add an HttpsSubscription pointing
// at the Slack incoming webhook URL (also stored in Secrets Manager).
```

### 4.3 Manual creation step (operator runbook)

Before deploying this stack, the operator must:

1. Create the secret in Secrets Manager:
   ```bash
   aws secretsmanager create-secret \
     --name isol8/dev/oncall/phone \
     --secret-string '{"phone":"+15551234567"}' \
     --profile isol8-admin --region us-east-1
   ```
   Repeat for `isol8/prod/oncall/phone`.

2. Subscribe to the email addresses (after first deploy, AWS sends a confirmation link to each — operator clicks it once).

This is documented in `docs/ops/setup-oncall.md` (created by this track).

## 5. Alarms — implementation pattern

Each alarm is defined via a small helper to avoid 64 lines of boilerplate:

```typescript
// observability-stack.ts

interface AlarmDef {
  id: string;        // e.g., "P1"
  name: string;      // e.g., "container-error-state"
  metricName: string;
  namespace?: string; // default "Isol8"
  statistic?: string; // default "Sum"
  threshold: number;
  evaluationPeriods: number;
  periodMinutes: number;
  comparisonOperator: cloudwatch.ComparisonOperator;
  treatMissingData?: cloudwatch.TreatMissingData;
  dimensions?: Record<string, string>;
  severity: 'page' | 'warn';
  description: string;
}

private createAlarm(def: AlarmDef): cloudwatch.Alarm {
  // Auto-inject standard dimensions (env, service) to match EMF emitter output
  const dimensions = {
    env: this.envName,
    service: 'isol8-backend',
    ...(def.dimensions ?? {}),
  };

  const metric = new cloudwatch.Metric({
    namespace: def.namespace ?? 'Isol8',
    metricName: def.metricName,
    statistic: def.statistic ?? 'Sum',
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

  alarm.addAlarmAction(new cloudwatch_actions.SnsAction(
    def.severity === 'page' ? this.pageTopic : this.warnTopic,
  ));

  return alarm;
}
```

Then alarms are defined as a flat array fed into `createAlarm`. Example for P1:

```typescript
this.createAlarm({
  id: 'P1',
  name: 'container-error-state',
  metricName: 'container.error_state',
  threshold: 0,
  evaluationPeriods: 1,
  periodMinutes: 1,
  comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
  severity: 'page',
  description: 'Per-user OpenClaw container in stuck/error state',
});
```

**The teammate must implement all 64 alarms from master spec §7.** Use the master spec's alarm IDs and thresholds verbatim.

### 5.1 Special cases

**Metric-math alarms** (P9, P10, W10, W18) need `cloudwatch.MathExpression`:

```typescript
const errorRate = new cloudwatch.MathExpression({
  expression: '100 * errors / total',
  usingMetrics: {
    errors: new cloudwatch.Metric({ /* chat.error */ }),
    total: new cloudwatch.Metric({ /* chat.message.count */ }),
  },
  period: cdk.Duration.minutes(5),
});
```

**Anomaly detection alarms** (W5, W32, W45, W50) use `cloudwatch.Alarm` with `CloudWatchAnomalyDetector`.

**EventBridge → metric filter alarm** (W39 Fargate TaskStopped) requires:
1. An EventBridge rule on `aws.ecs` source matching `Task State Change` events with `lastStatus = STOPPED` and a non-essential `stoppedReason`
2. A target that publishes a CloudWatch metric (`isol8.ecs.task_stopped_unexpected`)
3. An alarm on that metric

**Heartbeat-absence alarm** (P7 update-worker-stalled): use `treatMissingData: BREACHING` so missing heartbeats trigger the alarm.

## 6. Dashboard

One CloudWatch dashboard, `isol8-{env}-orr`, with widgets organized by domain:

```typescript
const dashboard = new cloudwatch.Dashboard(this, 'OrrDashboard', {
  dashboardName: `isol8-${envName}-orr`,
});

dashboard.addWidgets(
  // Row 1: SLOs
  new cloudwatch.GraphWidget({
    title: 'Chat success rate (SLO: 99.5%)',
    left: [chatSuccessRateMetric],
    width: 12, height: 6,
  }),
  new cloudwatch.GraphWidget({
    title: 'Chat p99 latency (SLO: <20s)',
    left: [chatP99LatencyMetric],
    width: 12, height: 6,
  }),

  // Row 2: Container & gateway
  // Row 3: Channels & billing
  // Row 4: Auth & security
  // Row 5: Infrastructure (ALB, API GW, ECS, DynamoDB)
  // Row 6: Cost
);
```

Full widget list in implementation. Aim for ~30 widgets organized by domain. Each widget shows the metric over the last 24h with relevant alarm thresholds annotated.

## 7. Synthetic canaries

CloudWatch Synthetics canaries are defined in CDK via the `aws-cdk-lib/aws-synthetics` module.

### 7.1 `/health` canary

```typescript
const healthCanary = new synthetics.Canary(this, 'HealthCanary', {
  canaryName: `isol8-${envName}-health`,
  schedule: synthetics.Schedule.rate(cdk.Duration.minutes(1)),
  test: synthetics.Test.custom({
    code: synthetics.Code.fromInline(`
      const synthetics = require('Synthetics');
      const log = require('SyntheticsLogger');

      exports.handler = async () => {
        const url = 'https://api-${envName}.isol8.co/health';
        await synthetics.executeHttpStep('Health check', {
          hostname: 'api-${envName}.isol8.co',
          method: 'GET',
          path: '/health',
          protocol: 'https:',
          headers: { 'User-Agent': 'CloudWatchSynthetics-Isol8-Health' },
        }, async (res) => {
          if (res.statusCode !== 200) {
            throw new Error('Expected 200, got ' + res.statusCode);
          }
        });
      };
    `),
    handler: 'index.handler',
  }),
  runtime: synthetics.Runtime.SYNTHETICS_NODEJS_PUPPETEER_7_0,
  // NOTE: Verify the latest available Synthetics runtime at implementation time.
  // Runtime versions change frequently. Check: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Synthetics_Canaries_Library.html
});
```

Alarm W52 fires on canary failure rate.

### 7.2 Chat round-trip canary

More involved — needs to authenticate to Clerk, open a WebSocket, send a chat message, and assert a response. Implementation outline:

```typescript
const chatCanary = new synthetics.Canary(this, 'ChatRoundTripCanary', {
  canaryName: `isol8-${envName}-chat-rt`,
  schedule: synthetics.Schedule.rate(cdk.Duration.minutes(15)),
  test: synthetics.Test.custom({
    code: synthetics.Code.fromAsset('canaries/chat-roundtrip'),
    handler: 'index.handler',
  }),
  runtime: synthetics.Runtime.SYNTHETICS_NODEJS_PUPPETEER_7_0,
  environmentVariables: {
    CANARY_API_BASE: `https://api-${envName}.isol8.co`,
    CANARY_WS_URL: `wss://ws-${envName}.isol8.co/`,
    CANARY_CREDENTIALS_SECRET: `isol8/${envName}/canary/credentials`,
  },
});

// Grant the canary's IAM role read access to the credentials secret
canaryCredentialsSecret.grantRead(chatCanary.role);
```

Canary code lives in `apps/infra/canaries/chat-roundtrip/index.js`. The teammate must write this. The script:

1. Reads Clerk credentials from Secrets Manager (`isol8/{env}/canary/credentials`)
2. POSTs to Clerk's dev sign-in API to get a session JWT
3. Connects to the WebSocket API with the JWT in the auth header
4. Sends a synthetic `agent_chat` message: `{type:"agent_chat", agent_id:"<canary-agent>", message:"ping"}`
5. Awaits a `chat.final` event (timeout: 20s)
6. Closes the WebSocket
7. Logs success

Alarm P11 fires on 2-of-3 consecutive failures.

**Pre-requisite (operator action, documented in `docs/ops/setup-canary.md`):**

1. Create Clerk account `isol8-canary@<your-domain>` via Clerk dashboard
2. Sign in once to complete onboarding (provision a container, create a default agent)
3. Note the agent ID
4. Store credentials in Secrets Manager:
   ```bash
   aws secretsmanager create-secret \
     --name isol8/dev/canary/credentials \
     --secret-string '{"email":"isol8-canary@<your-domain>","password":"...","agent_id":"..."}' \
     --profile isol8-admin --region us-east-1
   ```

### 7.3 Stripe webhook replay canary

```typescript
const stripeCanary = new synthetics.Canary(this, 'StripeReplayCanary', {
  canaryName: `isol8-${envName}-stripe-replay`,
  schedule: synthetics.Schedule.cron({ hour: '3', minute: '0' }),  // 03:00 UTC daily
  test: synthetics.Test.custom({
    code: synthetics.Code.fromAsset('canaries/stripe-replay'),
    handler: 'index.handler',
  }),
  // ...
});
```

Script POSTs a known-good test webhook payload (signed with the test mode secret) to `/api/v1/billing/webhooks/stripe`, asserts 200 + idempotency dedup (i.e., second call returns 200 but does not re-process).

The test payload is checked into the canary asset, signed at deploy time (or pre-signed and committed — easier).

Alarm W53 fires on canary failure.

## 8. IAM tightening (#190 §3 item 10)

Edits to `apps/infra/lib/stacks/service-stack.ts`:

| Current | Change |
|---|---|
| ECS `CreateService/UpdateService/DeleteService` not constrained by task-definition ARN (~lines 160-177) | Add `resources: [taskDef.taskDefinitionArn, \`arn:aws:ecs:${region}:${account}:service/${cluster.clusterName}/openclaw-*\`]` |
| Secrets Manager wildcard `isol8/{env}/*` (~lines 205-216) | Split into per-secret grants. Keep `isol8/{env}/clerk/*`, `isol8/{env}/stripe/*`, `isol8/{env}/encryption-key`, `isol8/{env}/oncall/phone` (added in this track), `isol8/{env}/canary/credentials` (added in this track). Drop the wildcard. |
| DynamoDB `grantReadWriteData` on all 6 tables with no `LeadingKeys` condition (~lines 219-224) | Add `dynamodb:LeadingKeys = ${aws:userid}` condition where the table has a per-user PK (users, containers, billing-accounts, api-keys, usage-counters). For tables shared across users (pending-updates, ws-connections), keep the broad grant but add a comment explaining why. |
| Cloud Map `DiscoverInstances/ListInstances` unrestricted (~lines 280-293) | Constrain to the namespace ARN |
| KMS `Decrypt/GenerateDataKey` unrestricted (~lines 296-302) | Constrain to the existing AuthStack KMS key ARN |
| S3 `isol8-{env}-openclaw-configs` not path-scoped (~lines 363-376) | **Cannot use `${aws:userid}` — it resolves to IAM role unique ID, not app user ID.** Instead, keep the bucket-level grant (the bucket is already constrained to `isol8-${envName}-openclaw-configs`) and add a comment documenting that per-user path scoping is not feasible via IAM policy variables because the paths are keyed by Clerk user IDs. Alternatively, scope to `*/openclaw.json` pattern via `s3:prefix` condition if all writes follow that naming convention. |

After each change, run `cdk diff` and review. Some changes may break the running service if the IAM is wrong — the teammate must validate against the existing E2E suite (currently disabled) and a manual chat smoke test before declaring done.

## 9. AWS-account hardening

In `observability-stack.ts` (or a sibling `account-hardening-stack.ts` if it gets too crowded):

### 9.1 GuardDuty
```typescript
new guardduty.CfnDetector(this, 'GuardDuty', {
  enable: true,
  findingPublishingFrequency: 'FIFTEEN_MINUTES',
});
```

Subscribe the warn SNS topic to GuardDuty findings via EventBridge.

### 9.2 IAM Access Analyzer
```typescript
new accessanalyzer.CfnAnalyzer(this, 'AccessAnalyzer', {
  type: 'ACCOUNT',
  analyzerName: `isol8-${envName}-access-analyzer`,
});
```

Subscribe warn topic to findings.

### 9.3 AWS Budgets

```typescript
new budgets.CfnBudget(this, 'MonthlyBudget', {
  budget: {
    budgetType: 'COST',
    timeUnit: 'MONTHLY',
    budgetLimit: { amount: 500, unit: 'USD' },  // adjust to current spend baseline
    budgetName: `isol8-${envName}-monthly`,
  },
  notificationsWithSubscribers: [
    {
      notification: { /* 80% threshold */ },
      subscribers: [{ subscriptionType: 'EMAIL', address: 'alerts@<your-domain>' }],
    },
    {
      notification: { /* 100% threshold */ },
      subscribers: [{ subscriptionType: 'EMAIL', address: 'oncall@<your-domain>' }],
    },
  ],
});
```

## 10. DynamoDB pending-updates TTL

**Status: CDK side already done.** The `pending-updates` table already has `timeToLiveAttribute: "ttl"` (line 108 of `database-stack.ts`). No CDK change needed.

**Remaining work (Track A or C):** verify that the backend write path sets the `ttl` attribute on every `pending-updates` item. Search `update_repo.py` for the put/update calls and confirm each includes `"ttl": int(time.time()) + 30 * 86400`. If missing, add it. Coordinate via SendMessage with the Track A or Track C teammate who owns the write path.

## 11. Delete `apps/terraform/`

The directory contains only `.terraform/` cache metadata (no tracked `.tf` files), so `git rm` will fail. Use:

```bash
rm -rf apps/terraform/
```

Then check `pnpm-workspace.yaml` and `turbo.json` for any references and remove them. Check `.gitignore` for terraform-specific entries. Update `CLAUDE.md` (Track C owns the CLAUDE.md edit).

## 12. Test strategy

### Snapshot tests
```bash
cd apps/infra && pnpm test
```

CDK snapshot tests for the new stack — confirms it synths to the expected resources.

### `cdk synth` + `cdk diff`
```bash
cd apps/infra && pnpm cdk synth && pnpm cdk diff dev/observability
```

Review every change before deploying.

### Deploy to dev
```bash
cd apps/infra && pnpm cdk deploy dev/observability --profile isol8-admin
```

Then verify:

1. **SNS topics exist:**
   ```bash
   aws sns list-topics --profile isol8-admin --region us-east-1 | jq '.Topics[].TopicArn' | grep alerts
   ```

2. **Manual SNS test (page tier):**
   ```bash
   aws sns publish \
     --topic-arn arn:aws:sns:us-east-1:877352799272:isol8-dev-alerts-page \
     --message "Test page from ORR Track B deploy validation" \
     --profile isol8-admin
   ```
   Phone should receive an SMS within ~30s. Email should arrive within minutes.

3. **Alarms exist:**
   ```bash
   aws cloudwatch describe-alarms --profile isol8-admin --region us-east-1 \
     --alarm-name-prefix isol8-dev-
   ```
   Should return all 64.

4. **Dashboard renders:**
   - Open AWS Console → CloudWatch → Dashboards → `isol8-dev-orr`
   - Some widgets will be empty until Track A is merged and traffic flows. That's expected.

5. **`/health` canary fires:**
   ```bash
   aws synthetics get-canary-runs --name isol8-dev-health --profile isol8-admin
   ```
   Should show successful runs starting ~1 min after deploy.

6. **GuardDuty active:**
   ```bash
   aws guardduty list-detectors --profile isol8-admin --region us-east-1
   ```

7. **IAM E2E sanity:**
   - Manually run a chat session in dev frontend → verify it still works (catches any IAM regression from §8 tightening)
   - If it breaks, the failing IAM grant is in §8 — review and add the missing permission with the smallest possible scope

## 13. Files affected (summary)

**New files:**
- `apps/infra/lib/stacks/observability-stack.ts`
- `apps/infra/canaries/chat-roundtrip/index.js`
- `apps/infra/canaries/stripe-replay/index.js`
- `apps/infra/test/observability-stack.test.ts`
- `docs/ops/setup-oncall.md`
- `docs/ops/setup-canary.md`

**Modified files:**
- `apps/infra/lib/app.ts` — wire new stack into both stages
- `apps/infra/lib/local-stage.ts` — add observability
- `apps/infra/lib/isol8-stage.ts` — add observability
- `apps/infra/lib/stacks/service-stack.ts` — IAM tightening (§8)
- `apps/infra/lib/stacks/database-stack.ts` — pending-updates TTL
- `apps/infra/package.json` — add `@aws-cdk/aws-synthetics`, `aws-cdk-lib/aws-budgets` if needed

**Deleted:**
- `apps/terraform/` (whole directory)

## 14. Risks & mitigations

| Risk | Mitigation |
|---|---|
| New IAM constraints break the running backend (a needed permission was tightened too far) | Deploy to dev first, run manual chat smoke test, watch CloudWatch logs for `AccessDenied`; revert and add the permission with minimal scope if it fails |
| Phone-number SMS unwrap exposes the secret in CFN templates | Acceptable trade-off (CFN templates are accessible only to trusted IAM); flag in PR for user awareness |
| Canary cost overruns (chat round-trip × 96 runs/day × Bedrock fees) | Spec defaults to 15-min cadence; user can dial down. Add a CloudWatch billing alarm specifically on Synthetics + Bedrock spend (W50). |
| Track A's metrics not yet flowing → alarms in `Insufficient data` state forever | Set `treatMissingData: NOT_BREACHING` for most alarms (so they don't false-page); for the heartbeat alarm (P7) use `BREACHING` (the whole point is to fire when data is missing) |
| Track A → Track B name drift (e.g., teammate emits `chat.errors` instead of `chat.error`) | Master spec is the source of truth. Lead validates by listing `Isol8` namespace post-deploy and cross-checking against §6.3. Any drift is fixed in Track A. |
| Budget threshold of $500 may be too low or too high for current dev spend | Teammate checks current dev spend via Cost Explorer before committing the threshold; adjusts to 1.5× of current monthly average. |

## 15. Definition of done

- [ ] `ObservabilityStack` exists and synths cleanly
- [ ] All 64 alarms from master spec §7 created
- [ ] Both SNS topics exist with correct subscriptions
- [ ] Manual SMS test verified (operator received page on phone)
- [ ] Dashboard renders in CloudWatch console
- [ ] All 3 canaries deployed and running (`/health` succeeding; chat may need Track A's metric flow)
- [ ] IAM tightening from §8 deployed; manual chat smoke test still passes
- [ ] GuardDuty + Access Analyzer + Budgets active
- [ ] `pending-updates` table has TTL attribute
- [ ] `apps/terraform/` deleted
- [ ] CDK snapshot tests pass
- [ ] `cdk diff` reviewed, no unexpected changes
- [ ] Branch builds cleanly under `turbo run lint --filter=@isol8/infra` and `turbo run test --filter=@isol8/infra`
- [ ] `docs/ops/setup-oncall.md` and `docs/ops/setup-canary.md` written

## 16. Open questions for the lead

- **Budget threshold ($500/mo placeholder).** Teammate checks current dev spend via Cost Explorer at start of work; if substantially different, SendMessage lead before committing.
- **Phone number / email addresses.** Teammate uses `<your-domain>` placeholder; lead replaces with real addresses before merge.
- **Slack webhook URL.** Spec marks as TODO. Teammate does not implement the Slack subscription this pass.
