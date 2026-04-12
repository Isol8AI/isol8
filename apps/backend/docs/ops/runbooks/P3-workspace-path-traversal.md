# Alarm P3: workspace-path-traversal

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
A path traversal attempt was blocked in the workspace file handler. Someone tried to read/write outside their user directory boundary.

## Customer impact
None — the attempt was blocked. This is a security event.

## Immediate actions
1. Check the structured logs for the user_id and the attempted path.
2. Determine if the request came from a legitimate user (misconfigured agent) or an attacker.
3. If suspicious, consider temporarily suspending the user's container.
4. File a security incident report.

## Investigation
- Dashboard: CloudWatch dashboard, security events widget
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, user_id, message
  | filter message like /path_traversal|Path traversal denied/
  | sort @timestamp desc
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
