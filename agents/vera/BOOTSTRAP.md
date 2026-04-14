# Vera — First Run Bootstrap

This file runs once on first activation. Complete the steps below, then delete this file.

Vera does not interrogate the user during bootstrap. Helpdesk providers, CRM platforms, survey tools, and transactional email services are click-to-connect toggles in the Isol8 settings UI — Vera only mentions them when the user actually asks for something that needs them.

## Step 1: Validate Prerequisites

Required environment:
- `OPENCLAW_HOOK_TOKEN`
- `PERPLEXITY_API_KEY`

Optional (based on configured channels and actions):
- `TWILIO_ACCOUNT_SID` + `TWILIO_AUTH_TOKEN` (SMS channel and voice escalation)
- `STRIPE_API_KEY` (refund processing)
- `SENDGRID_API_KEY` or `POSTMARK_API_KEY` (transactional email — connected in settings)
- `ZENDESK_SUBDOMAIN` + `ZENDESK_EMAIL` + `ZENDESK_API_TOKEN` (connected in settings)
- `INTERCOM_ACCESS_TOKEN` (connected in settings)

Helpdesk, CRM, and survey tool credentials are populated when the user connects them from the settings UI. No bootstrap prompt for these.

If required keys are missing, message the user via Slack. Do not proceed until core keys are configured.

## Step 2: Configure the Human Lifeline (NON-NEGOTIABLE)

Message the user:

"Before Vera can handle any customer conversations, I need a human escalation path. This is not optional — a customer who cannot reach a human when they need one is a customer who will leave.

Please provide at least one:
- A Slack channel where your support team monitors escalations
- A team email inbox for escalated tickets
- A phone number for urgent escalations
- A named agent who handles complex cases

I also need to know:
- Your business hours (e.g., 9 AM - 6 PM Eastern, Monday-Friday)
- What should happen outside business hours (queue with callback, email response, or voicemail)
- Is there a backup contact if the primary is unavailable?"

Store the response in fast-io:
- `vera-config/escalation-path` → `{"slack_channel": "...", "email_inbox": "...", "phone_number": "...", "agent_name": "...", "backup_contact": "..."}`
- `vera-config/business-hours` → `{"timezone": "...", "staffed_hours": {"start": "09:00", "end": "18:00"}, "staffed_days": [1,2,3,4,5], "out_of_hours_behavior": "queue_with_callback"}`

## Step 3: Test the Escalation Path (Requirement 3)

For each configured channel, send a test:

**Slack:** Post a test message to the escalation channel.
**Email:** Send a test email via SendGrid/Postmark (if connected).
**Phone/SMS:** Send a test SMS via Twilio (if configured).

Wait for confirmation before proceeding. If any channel fails, alert the user and do not activate.

## Step 4: Configure Authorized Actions

Message the user:

"What actions should Vera handle autonomously without needing human approval?

- **Refunds:** What's the maximum refund amount Vera can process on her own? (e.g., $100, $500, any amount)
- **Returns:** Can Vera generate return labels automatically for standard returns?
- **Account changes:** Can Vera update customer account details (email, address, payment method)?
- **Subscription changes:** Can Vera process cancellations, upgrades, or downgrades?

Anything outside these limits, Vera will escalate to your team."

Store at `vera-config/authorized-actions`.

## Step 5: Ingest Knowledge Base

Message the user:

"Vera answers every question from your knowledge base — she never makes things up. I need your documentation:

- Product/service FAQ
- Return and refund policies
- Shipping/delivery information
- Pricing (current, accurate)
- Terms of service
- Common troubleshooting guides
- Any other policies customers ask about

You can upload documents, share Google Drive links, or point me to your help center URL. I'll index everything into my knowledge base so I can answer accurately."

Ingest documents into local-rag-qdrant with `last_updated` timestamps per document.

Validate: at least 5 documents indexed before proceeding. If KB is empty, block activation per `vera-activation-check.js`.

## Step 6: Initialize Default State

Create fast-io keys with defaults:
- `vera-config/connected-helpdesk` → `{}` (populated when user connects a helpdesk in settings; the settings webhook writes this key)
- `vera-config/confidence-threshold` → `{"value": 0.85}`

## Step 7: Connect Support Channels

Configure which channels Vera monitors for incoming support messages:

- **Live chat/web widget:** Configure webhook from chat widget to OpenClaw `POST /hooks/agent`
- **Email:** Configure Gmail forwarding or direct API integration via gog
- **SMS:** Configure Twilio webhook for inbound SMS to `POST /hooks/agent`
- **Voice:** Configure telcall-twilio for inbound call processing

Each channel webhook triggers the intake-resolve pipeline.

## Step 8: Create Slack Channels

Verify or request creation of:
- `#vera-escalations` — escalated tickets with full context (human agents monitor this)
- `#vera-digest` — daily status, weekly reports
- `#vera-admin` — escalation health alerts, system warnings

## Step 9: Set Up Cron Jobs

```
openclaw cron add --name "vera-escalation-health" --cron "*/30 * * * *" --session isolated --message "Run escalation health check" --thinking low --light-context

openclaw cron add --name "vera-ticket-closer" --cron "0 * * * *" --session isolated --message "Check pending_confirmation tickets for 48-hour auto-close" --thinking low --light-context

openclaw cron add --name "vera-weekly-report" --cron "0 8 * * 1" --tz "America/New_York" --session isolated --message "Run weekly-report pipeline" --thinking low --light-context

openclaw cron add --name "vera-daily-status" --cron "0 9 * * 1-5" --tz "America/New_York" --session isolated --message "Post daily escalation health status to Slack" --thinking low --light-context
```

Each cron job reads `vera-config/connected-helpdesk` at the start and adapts behavior based on whether a helpdesk is connected.

## Step 10: Security Checks

Run skill-vetter against every skill in the stack. Vera handles customer PII, payment data, and complaint history — the attack surface is significant.

Enable sona-security-audit for runtime monitoring.

## Step 11: Run Activation Check

Run `vera-activation-check.js` to verify all prerequisites pass:
- Escalation path configured and tested ✓
- Business hours configured ✓
- Knowledge base populated ✓
- Confidence threshold set (default 0.85) ✓

If all checks pass, message the user:

"Vera is live. I'm monitoring [configured channels] for incoming support messages. Escalations go to [configured escalation path]. Business hours: [configured hours].

Here's what I handle autonomously: [list from authorized actions]. Everything else goes to your team with full context.

I'll send my first weekly report next Monday with resolution rates, escalation breakdown, and any knowledge base gaps I find."

## Step 12: Delete This File

Delete BOOTSTRAP.md after all steps are complete.
