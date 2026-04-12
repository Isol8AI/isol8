# On-Call Setup Guide

This guide covers the one-time setup steps required before the ObservabilityStack can send page-tier SMS alerts.

## Prerequisites

- AWS CLI configured with the `isol8-admin` profile
- Access to the on-call phone number

## 1. Create the on-call phone secret

The page-tier SNS topic sends SMS to the on-call phone number stored in Secrets Manager. Create the secret for each environment:

```bash
# Dev
aws secretsmanager create-secret \
  --name isol8/dev/oncall/phone \
  --secret-string '{"phone":"+15551234567"}' \
  --profile isol8-admin --region us-east-1

# Prod
aws secretsmanager create-secret \
  --name isol8/prod/oncall/phone \
  --secret-string '{"phone":"+15551234567"}' \
  --profile isol8-admin --region us-east-1
```

Replace `+15551234567` with the actual on-call phone number (E.164 format).

## 2. Confirm email subscriptions

After the first deploy of the ObservabilityStack, AWS SNS sends confirmation emails to:

- `oncall@isol8.co` (page topic)
- `alerts@isol8.co` (warn topic)

Click the confirmation link in each email. Until confirmed, no alerts are delivered to that address.

## 3. Verify SMS delivery

After the stack is deployed and the secret exists, manually publish a test message:

```bash
# Get the page topic ARN
PAGE_TOPIC=$(aws cloudformation describe-stacks \
  --stack-name isol8-dev-observability \
  --query 'Stacks[0].Outputs[?OutputKey==`PageTopicArn`].OutputValue' \
  --output text --profile isol8-admin --region us-east-1)

# Send test page
aws sns publish \
  --topic-arn "$PAGE_TOPIC" \
  --message "Test page from ORR setup validation" \
  --profile isol8-admin --region us-east-1
```

The on-call phone should receive an SMS within 30 seconds. The email should arrive within a few minutes.

## 4. Future: PagerDuty integration

When a PagerDuty account is set up, add an HTTPS subscription to the page topic pointing at the PagerDuty Events API v2 endpoint. This can be done in the ObservabilityStack code or manually via the AWS Console.

## 5. Future: Slack integration

When a Slack workspace with an incoming webhook URL is available, add an HTTPS subscription to the warn topic. Store the webhook URL in Secrets Manager at `isol8/{env}/slack/webhook_url`.
