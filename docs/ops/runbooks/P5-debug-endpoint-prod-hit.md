# Alarm P5: debug-endpoint-prod-hit

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
A debug endpoint was accessed in a production environment. These endpoints should return 403 in production.

## Customer impact
If the 403 guard failed, an attacker could provision/delete containers without Stripe billing.

## Immediate actions
1. Verify the ENVIRONMENT variable is set correctly on the production backend.
2. Check if the request actually succeeded (status 200) or was correctly blocked (403).
3. If it succeeded, investigate how the guard was bypassed and fix immediately.

## Investigation
- Dashboard: CloudWatch dashboard, security events widget
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, user_id, message
  | filter message like /debug.*prod/
  | sort @timestamp desc
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
