# Alarm P9: alb-5xx-rate

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
The Application Load Balancer is returning 5xx errors at a rate above 5% for 5 minutes. The backend is unhealthy.

## Customer impact
Users see errors when using the platform. Chat, billing, and control panel may all be affected.

## Immediate actions
1. Check the backend ECS task logs for errors and exceptions.
2. Check if a recent deploy is the cause — rollback if so.
3. Verify the backend health check endpoint (`/health`) is responding.
4. Check DynamoDB connectivity (the health check validates this).

## Investigation
- Dashboard: CloudWatch dashboard, ALB widget
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, user_id, message, level
  | filter level = "ERROR"
  | sort @timestamp desc
  | limit 50
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
