# Alarm P8: dynamodb-throttle-sustained

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
DynamoDB is throttling requests for 2 or more consecutive minutes. Read/write capacity is insufficient for current traffic.

## Customer impact
Degraded performance — API requests may be slow or fail. Chat messages may time out.

## Immediate actions
1. Check which table(s) are throttling in the CloudWatch DynamoDB metrics.
2. If using provisioned capacity, increase read/write capacity units.
3. If using on-demand, check for hot partitions (single owner_id getting hammered).
4. Consider enabling auto-scaling if not already configured.

## Investigation
- Dashboard: CloudWatch dashboard, DynamoDB widget
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, user_id, message
  | filter message like /ThrottlingException|dynamodb.*throttle/
  | sort @timestamp desc
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
