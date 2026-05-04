# Marketplace Plan 1 — Operational Provisioning

This runbook covers steps that `cdk deploy` does NOT do. Run these once per
environment (dev, then prod when ready) before deploying Plan 2.

## 1. Vercel — Create marketplace.isol8.co project

1. https://vercel.com/dashboard → New Project
2. Import the `Isol8AI/isol8` GitHub repo.
3. Project name: `isol8-marketplace`
4. Root directory: `apps/marketplace`
5. Domain: assign `marketplace.dev.isol8.co` (dev) or `marketplace.isol8.co` (prod).
   DNS records added to Route 53 separately — see DNS section below.
6. Environment variables (per env): set after step 5 (Algolia provisioning).
7. Note: do NOT enable auto-deploy on push until Plan 5 ships.

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

## 5. Algolia — Create app + provision keys

_Algolia was removed in Round 2 of the v0 reduction (see design spec). Browse + search now use an in-process backend service backed by `marketplace_search.py` — TTL-cached scan + tokenized scoring. No external SaaS to provision._

Vercel project env vars for the storefront (per env):

| Name | Value |
|------|-------|
| `NEXT_PUBLIC_API_URL` | `https://api-dev.isol8.co` (dev) or `https://api.isol8.co` (prod) |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | The Clerk pub key shared with the chat app |
| `NEXT_PUBLIC_APP_URL` | `https://app.isol8.co` (used by the post-deploy "Open in Isol8" deep-link) |

## 6. Verify

```bash
aws secretsmanager describe-secret --name "isol8/dev/stripe_connect_client_id" \
  --profile isol8-admin --region us-east-1
# Expect: returns metadata, secret exists.

curl -I https://marketplace.dev.isol8.co
# Expect: 404 from Vercel (project exists, no deployment yet — that's correct)
```

## When Plan 1 is "done"

- `cdk deploy isol8-pipeline-dev/Database` succeeds; the 4 marketplace
  tables visible via `aws dynamodb list-tables | grep marketplace`
  (listings, purchases, payout-accounts, takedowns).
- `cdk deploy isol8-pipeline-dev/Service` succeeds; the marketplace
  artifacts bucket is created. (No Lambdas — Algolia removed in Round 2;
  no MCP service — removed in Round 1.)
- `scripts/validate-stripe-connect-sandbox.py` exits 0 against a real `sk_test_...` key.
- Vercel project shell exists; DNS resolves.
- Secrets Manager has both Stripe Connect secrets per env.

Plans 2-6 can now begin.
