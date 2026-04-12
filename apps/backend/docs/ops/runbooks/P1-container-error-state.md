# Alarm P1: container-error-state

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
A user's OpenClaw container is stuck in an error state (ECS task failed to start or entered a crash loop).

## Customer impact
The affected user cannot chat with their agent. Container status shows "error" in the control panel.

## Immediate actions
1. Check the ECS console for the stuck service — look for stopped tasks and their stop reason.
2. Check CloudWatch Logs for the container's task logs (filter by the user's service name).
3. If the task is crash-looping, check for bad config in openclaw.json on EFS.
4. Force-stop the service and re-provision via `DELETE /debug/provision` then `POST /debug/provision` (dev only), or manually via ECS console + DynamoDB status update.

## Investigation
- Dashboard: CloudWatch dashboard, container lifecycle widget
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, user_id, message
  | filter message like /error_state|Failed to start|EcsManagerError/
  | sort @timestamp desc
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
