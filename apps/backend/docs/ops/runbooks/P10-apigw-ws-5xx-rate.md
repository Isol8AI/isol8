# Alarm P10: apigw-ws-5xx-rate

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
The WebSocket API Gateway is returning 5xx errors at a rate above 5% for 5 minutes. Real-time chat is broken.

## Customer impact
Users cannot connect or send chat messages. Active conversations are disconnected.

## Immediate actions
1. Check the Lambda authorizer logs — JWT validation failures cause 5xx at the gateway level.
2. Check NLB health targets — if the backend is unreachable, all WS connections fail.
3. Verify the VPC Link is healthy in the API Gateway console.
4. Check if the Management API endpoint is reachable.

## Investigation
- Dashboard: CloudWatch dashboard, WebSocket API widget
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, message
  | filter message like /Lambda.*error|NLB.*unhealthy|VPC Link/
  | sort @timestamp desc
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
