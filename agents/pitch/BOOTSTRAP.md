# Pitch — First Run Bootstrap

This file runs once on first activation. Complete all steps, then delete this file.

Pitch does not interrogate the user during bootstrap. Outbound email platforms, CRMs, and optional integrations are click-to-connect toggles in the Isol8 settings UI — Pitch only mentions them when the user actually asks for something that needs them.

## Step 1: Validate Prerequisites

Required environment:
- `PERPLEXITY_API_KEY`
- `APOLLO_API_KEY`
- `OPENCLAW_HOOK_TOKEN`

That's it. No outbound platform or CRM key is required at bootstrap — the user connects one from the settings UI before asking Pitch to send outreach or sync CRM data.

## Step 2: Initialize Fast-io Keys

Create the following keys in fast-io with empty/default values:
- `pitch-config/icp` — empty object (rep must populate before outreach begins)
- `pitch-config/launch-state` — `{"phase": "test_cohort", "accounts_processed": 0, "cohort_reviewed": false}`
- `pitch-config/activation` — will be populated by activation check
- `pitch-config/connected-outbound` — `null` (user connects via settings)
- `pitch-config/connected-crm` — `null` (user connects via settings)
- `competitor-list` — empty array (rep populates with competitor names)
- `timing-weights/` — default timing rules

## Step 3: Create Slack Channels

Verify or request creation of:
- `#pitch-approvals` — approval gate delivery
- `#pitch-signals` — signal notifications
- `#pitch-pipeline` — pipeline health and MEDDIC alerts
- `#pitch-quarantine` — low-confidence prospect alerts

## Step 4: Set Up Cron Jobs

Create the following scheduled jobs:

```
openclaw cron add --name "pitch-signal-sweep" --cron "0 */4 * * *" --tz "America/New_York" --session isolated --message "Run signal-sweep pipeline" --thinking low --light-context

openclaw cron add --name "pitch-sequence-execute" --cron "0 * * * *" --session isolated --message "Run sequence-execute pipeline" --thinking low --light-context

openclaw cron add --name "pitch-meddic-scan" --cron "0 8 * * 1-5" --tz "America/New_York" --session isolated --message "Run meddic-scan pipeline" --thinking low --light-context

openclaw cron add --name "pitch-bounce-check" --cron "0 9 * * 1" --tz "America/New_York" --session isolated --message "Run bounce rate health check" --thinking low --light-context

openclaw cron add --name "pitch-capability-evolve" --cron "0 6 * * 0" --tz "America/New_York" --session isolated --message "Run capability-evolver: analyze draft approval patterns, signal dismissal patterns, and engagement timing patterns. Update voice model, signal thresholds, and timing weights in fast-io." --thinking low --light-context
```

## Step 5: Configure Webhooks

Wire the user's outbound platform webhooks into OpenClaw's webhook endpoint. The user configures their outbound platform (Instantly, SmartLead, Mailshake, or Lemlist) to send webhook notifications to:

**Outbound platform reply webhook** → `POST /hooks/agent`
```json
{"message": "Reply received from {{prospect_domain}}. Run reply-handler pipeline.", "name": "pitch-reply"}
```

**Outbound platform unsubscribe webhook** → `POST /hooks/agent`
```json
{"message": "Unsubscribe from {{prospect_domain}}. Run opt-out-handler pipeline.", "name": "pitch-optout"}
```

**CRM deal stage change webhook** (HubSpot/Salesforce/Attio/Pipedrive) → `POST /hooks/agent`
```json
{"message": "Deal stage changed for {{prospect_domain}} from {{old_stage}} to {{new_stage}}. Run meddic-stage-check pipeline.", "name": "pitch-stage-change"}
```

**CRM contact status change webhook** → `POST /hooks/agent`
```json
{"message": "Contact status changed for {{prospect_domain}} to {{new_status}}. Check for active sequences to interrupt.", "name": "pitch-status-change"}
```

## Step 6: Run Security Checks

Run skill-vetter and sona-security-audit on all installed skills.

## Step 7: Confirm and Clean Up

Once all steps are complete:
1. Run the activation check to verify all prerequisites pass
2. Post a ready message to Slack:
   "Pitch is live. I detect buying signals, research prospects, draft outreach, manage sequences, and track deal progress through MEDDIC — all while keeping you in the loop at the moments that carry relationship risk. When you want me to start, just tell me. If you haven't connected your outbound platform or CRM yet, I'll let you know when it's time — no setup paperwork up front."
3. Delete this BOOTSTRAP.md file
