# Alarm P6: billing-pricing-missing-model

**Severity:** Page
**SNS topic:** isol8-{env}-alerts-page

## What it means
A chat used an LLM model that has no pricing row in the bedrock pricing table. Usage for this chat will not be billed.

## Customer impact
The user is not being billed correctly for their usage — revenue leakage.

## Immediate actions
1. Check the logs for the model ID that triggered this.
2. Add a pricing row for the model in `core/services/bedrock_pricing.py`.
3. Estimate the unbilled usage and backfill if significant.

## Investigation
- Dashboard: CloudWatch dashboard, billing widget
- Logs query (CloudWatch Insights):
  ```
  fields @timestamp, request_id, user_id, message
  | filter message like /No pricing for model/
  | sort @timestamp desc
  ```
- Recent deploys: `gh run list --repo Isol8AI/isol8 --workflow=deploy --limit=10`

## Escalation
- Primary: on-call (you)
- Secondary: TBD when team grows

## Known false positives
{List as observed}
