# Canary Setup Guide

This guide covers the one-time setup steps required before the chat round-trip and Stripe webhook replay canaries can run.

## Chat Round-Trip Canary

### 1. Create a dedicated Clerk account

Create a new Clerk account specifically for the canary. Do NOT reuse `isol8-e2e-testing@mailsac.com` (reserved for E2E gate tests) or any personal account.

1. Go to https://dev.isol8.co/sign-up (for dev) or https://isol8.co/sign-up (for prod)
2. Sign up with email: `isol8-canary@isol8.co` (or a similar dedicated address)
3. Set a strong password
4. Complete the onboarding flow:
   - Select a billing plan (Starter or higher — the canary needs an always-on container)
   - Wait for container provisioning to complete
   - Note the default agent ID from the chat sidebar

### 2. Store credentials in Secrets Manager

```bash
# Dev
aws secretsmanager create-secret \
  --name isol8/dev/canary/credentials \
  --secret-string '{
    "email": "isol8-canary@isol8.co",
    "password": "YOUR_PASSWORD_HERE",
    "agent_id": "AGENT_UUID_HERE",
    "clerk_frontend_api": "up-moth-55.clerk.accounts.dev"
  }' \
  --profile isol8-admin --region us-east-1
```

For production, use the prod Clerk frontend API domain:
```bash
# Prod
aws secretsmanager create-secret \
  --name isol8/prod/canary/credentials \
  --secret-string '{
    "email": "isol8-canary@isol8.co",
    "password": "YOUR_PASSWORD_HERE",
    "agent_id": "AGENT_UUID_HERE",
    "clerk_frontend_api": "clerk.isol8.co"
  }' \
  --profile isol8-admin --region us-east-1
```

### 3. Verify the canary runs

After deploying the ObservabilityStack, check that the canary is running:

```bash
aws synthetics get-canary-runs \
  --name isol8-dev-chat-rt \
  --profile isol8-admin --region us-east-1
```

The canary runs every 15 minutes. Check the first few runs to ensure they succeed.

### 4. Troubleshooting

- **Auth failures:** Verify the Clerk frontend API domain and credentials are correct in the secret
- **WebSocket timeout:** Ensure the canary account has a running container (check the Isol8 dashboard)
- **Agent not found:** Verify the agent_id in the secret matches an existing agent on the canary account

## Stripe Webhook Replay Canary

### 1. No additional setup required

The Stripe webhook replay canary uses the existing Stripe webhook signing secret (`isol8/{env}/stripe_webhook_secret`) which is already provisioned by the AuthStack.

### 2. Verify the canary runs

The canary runs daily at 03:00 UTC:

```bash
aws synthetics get-canary-runs \
  --name isol8-dev-stripe-replay \
  --profile isol8-admin --region us-east-1
```

### 3. What the canary tests

1. Constructs a test Stripe webhook payload (customer.subscription.updated event)
2. Signs it with the Stripe webhook secret
3. POSTs it to `/api/v1/billing/webhooks/stripe`
4. Asserts a 200 or 400 response (400 = idempotency dedup, which is fine)

A failure means the webhook handler is broken — signature verification, payload parsing, or endpoint routing has regressed.
