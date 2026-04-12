# Alarm P2: stripe-webhook-sig-fail

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
A Stripe webhook payload failed signature verification. Either the webhook secret was rotated without updating the backend, or someone is sending forged payloads.

## Customer impact
Billing events (subscription created/updated/deleted) may be silently lost, causing state divergence between Stripe and DynamoDB.

## Immediate actions
1. Check if the STRIPE_WEBHOOK_SECRET was recently rotated in the Stripe dashboard.
2. Verify the secret in AWS Secrets Manager matches the one in the Stripe webhook settings.
3. If secret mismatch, update Secrets Manager and redeploy the backend.
4. Check Stripe dashboard for failed webhook deliveries and replay them after fixing.

## Investigation
- Dashboard: CloudWatch dashboard, Stripe webhook widget
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, message
  | filter message like /Stripe webhook signature verification failed/
  | sort @timestamp desc
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
