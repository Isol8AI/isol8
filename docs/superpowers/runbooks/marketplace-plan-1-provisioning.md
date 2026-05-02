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

`stripe_connect_webhook_secret` is **CDK-managed** (created by AuthStack with a
placeholder value); the operator updates it post-deploy with the real signing
secret from Stripe (see §3). `stripe_connect_client_id` is created manually
because it isn't referenced by the backend at runtime — it's used at the Stripe
dashboard layer for OAuth.

```bash
# DEV — manually create the Connect client_id (used by the OAuth flow,
# not read from the backend container).
aws secretsmanager create-secret \
  --name "isol8/dev/stripe_connect_client_id" \
  --secret-string "ca_test_..." \
  --profile isol8-admin --region us-east-1
```

Repeat for prod with the live-mode value.

## 3. Stripe dashboard — Enable Connect Express + register webhook

1. https://dashboard.stripe.com/test/connect → enable Express in test mode.
2. Settings → Connect → register a webhook endpoint:
   - URL: `https://api-dev.isol8.co/api/v1/marketplace/webhooks/stripe-marketplace`
   - Events: `checkout.session.completed`, `charge.refunded`, `account.updated`,
     `transfer.failed`, `payout.paid`, `payout.failed`
3. Copy the webhook signing secret → paste it into the CDK-managed secret:
   ```bash
   aws secretsmanager update-secret \
     --secret-id "isol8/dev/stripe_connect_webhook_secret" \
     --secret-string "whsec_test_..." \
     --profile isol8-admin --region us-east-1
   ```
4. Repeat for live mode when promoting to prod (use the prod-mode endpoint URL
   `https://api.isol8.co/api/v1/marketplace/webhooks/stripe-marketplace` and
   the matching Secrets Manager id `isol8/prod/stripe_connect_webhook_secret`).

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
