# Alarm P7: update-worker-stalled

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
The background update worker has not emitted a heartbeat for 5 minutes. Scheduled updates (tier changes, image updates) are not being applied.

## Customer impact
Users who changed their subscription tier or have pending container updates will not see changes applied.

## Immediate actions
1. Check ECS task logs for the backend service — look for the worker task.
2. Check if the backend service has restarted recently (the worker runs as an asyncio task).
3. If the backend is healthy but the worker died, restart the backend service.

## Investigation
- Dashboard: CloudWatch dashboard, update worker widget
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, message
  | filter message like /scheduled update worker|Error in scheduled update/
  | sort @timestamp desc
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
