# Alarm P11: chat-canary-fail

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
The end-to-end chat canary failed 2 out of 3 consecutive runs. The full chat path (auth -> WebSocket -> container -> Bedrock -> response) is broken.

## Customer impact
Users cannot chat with their agents. This is a full outage for the core product feature.

## Immediate actions
1. This is a full incident. Check each layer in order:
   - ALB health: is the backend responding to `/health`?
   - API Gateway: are WebSocket connections succeeding?
   - Container pool: are gateway connections open?
   - Bedrock: is the LLM inference endpoint responding?
2. Check the canary logs in CloudWatch Synthetics for the specific failure step.
3. If a recent deploy caused this, rollback immediately.

## Investigation
- Dashboard: CloudWatch dashboard, canary widget + all system health widgets
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, user_id, message, level
  | filter level in ["ERROR", "WARNING"]
  | sort @timestamp desc
  | limit 100
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
