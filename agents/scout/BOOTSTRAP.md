# Scout — First Run Bootstrap

This file runs once on first activation. Complete all steps, then delete this file.

## Step 1: Validate Prerequisites

Check that the following environment variables are set:
- `APOLLO_API_KEY`
- `PERPLEXITY_API_KEY`
- `OPENCLAW_HOOK_TOKEN`

If required keys are missing, message the user via Slack explaining which are needed. Do not proceed until required keys are configured.

## Step 2: Detect Pitch Agent

Check if Pitch is installed on this gateway:
```
gateway config.get → check agents.list for id: "pitch"
```
Store result in fast-io:
- `scout-config/pitch-installed` → `true` or `false`

If Pitch is installed, Scout deposits leads to fast-io queues that Pitch reads.
If Pitch is not installed, Scout deposits directly to CRM and notifies via Slack.

## Step 3: Initialize Fast-io Keys

Create the following with default values:
- `scout-config/volume-limit` → `{"daily_limit": 50}`
- `scout-config/signal-weights` → `{}` (populated by capability-evolver after first week)
- `scout-config/exclusivity-weights` → default exclusivity map from scout-icp-scorer.js
- `scout-config/connected-crm` → `null` (user connects via settings)
- `scout-config/connected-enterprise` → `{}` (user connects optional services via settings)
- `scout-state/today-deposits` → `{"count": 0, "date": "{{today}}"}`
- `competitor-list` → `[]` (user populates)

## Step 4: Create Slack Channels

Verify or request creation of:
- `#scout-leads` — lead dossiers (used when Pitch not installed)
- `#scout-alerts` — urgent leads, source health alerts, match rate warnings
- `#scout-digest` — daily completion summary, weekly intelligence report

## Step 5: Set Up Cron Jobs

```
openclaw cron add --name "scout-daily-source" --cron "0 6 * * *" --tz "America/New_York" --session isolated --message "Run daily-source pipeline" --thinking low --light-context

openclaw cron add --name "scout-signal-monitor" --cron "0 */4 * * *" --tz "America/New_York" --session isolated --message "Run signal-monitor pipeline" --thinking low --light-context

openclaw cron add --name "scout-weekly-report" --cron "0 8 * * 1" --tz "America/New_York" --session isolated --message "Run weekly-report pipeline" --thinking low --light-context

openclaw cron add --name "scout-source-health" --cron "0 9 * * *" --tz "America/New_York" --session isolated --message "Run source health check" --thinking low --light-context
```

## Step 6: Configure Webhooks

Wire external webhooks into OpenClaw's webhook endpoint:

**Leadfeeder/Clearbit Reveal visitor webhook** → `POST /hooks/agent`
```json
{"message": "Website visitor detected: {{company_domain}} visited {{page}}. Run visitor-alert pipeline.", "name": "scout-visitor"}
```

**CRM deal stage change webhook** → `POST /hooks/agent`
```json
{"message": "Deal closed for {{domain}} — stage: {{new_stage}}. Log outcome for Scout conversion tracking.", "name": "scout-outcome"}
```

## Step 7: Security Checks

Run skill-vetter against every skill in the stack:
- Especially `last30days` — flagged for prompt-injection pattern
- Verify all skills have VirusTotal clearance
- Confirm no skills under 30 days old on ClawHub are installed

Enable sona-security-audit for runtime monitoring.

## Step 8: Announce Readiness

Post to `#scout-alerts`:

"Scout is live. When you're ready to start sourcing, tell me about your ideal customer and I'll set up signal monitors and database routing automatically. If you haven't connected a CRM yet, I'll let you know when it's time — no setup paperwork up front."

## Step 9: Delete This File

Delete BOOTSTRAP.md after all steps complete.
