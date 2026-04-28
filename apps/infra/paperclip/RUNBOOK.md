# Paperclip Migrations Runbook

After every `cdk deploy` of the Paperclip stack, run the database
migrations one-shot ECS task. This task:

1. Connects to the Paperclip Aurora cluster using the CDK-generated
   master credentials (`isol8-{env}-paperclip-db-credentials`,
   auto-injected into the container as `PGPASSWORD`).
2. Creates the `vector` extension if not already present (idempotent —
   safe to re-run).
3. Runs `pnpm --filter @paperclipai/db migrate` from `/app`, which
   applies any new Drizzle migrations.

The task definition is `isol8-{env}-paperclip-migrate` (CFN output
`PaperclipMigrateTaskDefArn`). It is a **one-shot task** — there is no
ECS service backing it. Operators must invoke it manually.

## Prerequisites

- AWS SSO logged in: `aws sso login --profile isol8-admin`
- The Paperclip stack has been deployed (`isol8-{env}-paperclip`)
- Have these values from CFN outputs (or the AWS console):
  - Cluster ARN — from `isol8-{env}-container` outputs
  - Two private-subnet IDs — from `isol8-{env}-network` outputs
  - Paperclip task SG ID — `isol8-{env}-paperclip` output
    `PaperclipTaskSecurityGroupId`

## Run Command

Replace `<placeholders>` with the values above. `--task-definition` uses
just the family — ECS resolves to the latest revision automatically.

```bash
aws ecs run-task \
  --cluster <cluster-arn> \
  --launch-type FARGATE \
  --task-definition isol8-<env>-paperclip-migrate \
  --network-configuration "awsvpcConfiguration={subnets=[<priv-subnet-1>,<priv-subnet-2>],securityGroups=[<paperclip-task-sg>],assignPublicIp=DISABLED}" \
  --profile isol8-admin --region us-east-1
```

The command prints the started task ARN. Capture it (e.g. `TASK_ARN=...`)
for the status + log commands below.

## Wait for Completion

The migrate task should reach `STOPPED` with exit code `0`:

```bash
aws ecs describe-tasks \
  --cluster <cluster-arn> \
  --tasks "$TASK_ARN" \
  --query 'tasks[0].{status:lastStatus,exitCode:containers[0].exitCode,reason:stoppedReason}' \
  --profile isol8-admin --region us-east-1
```

Repeat until `status` is `STOPPED`. A non-zero `exitCode` (or a non-empty
`reason` other than the normal `Essential container in task exited`)
means the run failed — see "Failure Recovery" below.

## Tail Logs

While the task is running, or after it stops, stream CloudWatch logs:

```bash
aws logs tail /isol8/<env>/paperclip-migrate --follow \
  --profile isol8-admin --region us-east-1
```

The first lines should show `apt-get` installing `postgresql-client`,
followed by `CREATE EXTENSION` output, followed by the Drizzle migrate
runner.

## When to Run

- **Once on first deploy**, before treating the Paperclip service as
  healthy. The main service starts up immediately on `cdk deploy`, but
  it will hit empty/missing tables until migrations have run.
- **After every `cdk deploy`** of `isol8-{env}-paperclip` that bumps the
  Paperclip image tag — a new release may include schema changes.

## Failure Recovery

If the task exits non-zero:

1. Read the task's container logs in
   `/isol8/<env>/paperclip-migrate` (the `aws logs tail` command above).
2. Common failure modes:
   - **Stale schema lock from a previous failed run.** Connect to the
     database via `psql` (from a separate one-shot ECS exec session, or
     a bastion) and inspect `__drizzle_migrations`. The most recent row
     with no `finished_at` is the partial state.
   - **`vector` extension not available.** The Aurora cluster must be on
     a Postgres version that supports `pg_vector`. The cluster is
     provisioned with engine version pinned in `database-stack.ts`; a
     downgrade would be unusual.
   - **Network — task can't reach Aurora.** Verify the migrate task was
     launched with the Paperclip task SG, and that the `Aurora ←
     Paperclip` ingress rule exists on the Aurora SG.
3. Re-run the same `aws ecs run-task` command — Drizzle migrations are
   idempotent for already-applied steps, so a partial-success retry is
   safe.

## Why Manual?

A CDK custom resource (Lambda) could automate this on every deploy, but
adds significant complexity (Lambda image, IAM, longer deploy cycle,
rollback semantics on failed migrations). The team has chosen the
manual run-task path for the initial cutover; the
`migrateTaskDefinition` is exposed publicly on `PaperclipStack` so a
future custom resource can wire to it without re-defining the task.
