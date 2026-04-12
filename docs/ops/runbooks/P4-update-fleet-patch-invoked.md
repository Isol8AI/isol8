# Alarm P4: update-fleet-patch-invoked

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
The fleet-wide config patch endpoint (`PATCH /container/config`) was called, modifying openclaw.json for every active user.

## Customer impact
All users' agent configurations were changed. If the patch was incorrect, all agents may behave unexpectedly.

## Immediate actions
1. Verify the patch was intentional — check the audit log for the actor and payload hash.
2. If unintentional, prepare a rollback patch and apply it via the same endpoint.
3. Spot-check a few users' openclaw.json files on EFS to verify the merge was correct.

## Investigation
- Dashboard: CloudWatch dashboard, update system widget
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, user_id, message, action, payload_hash
  | filter action = "fleet_patch"
  | sort @timestamp desc
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
