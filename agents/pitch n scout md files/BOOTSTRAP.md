# Pitch & Scout — First Run Bootstrap

This file runs once on first activation. Complete all steps in order, then delete this file.

Neither Pitch nor Scout interrogates the user during bootstrap. Outbound platforms, CRMs, and optional enrichment services are click-to-connect toggles in the Isol8 settings UI — only mention them when the user asks for something that requires them.

---

## Step 1: Validate Prerequisites

Required environment variables:
- `APOLLO_API_KEY`
- `PERPLEXITY_API_KEY`
- `OPENCLAW_HOOK_TOKEN`

If any are missing, message the user via Slack explaining which are needed. Do not proceed until all three are configured.

---

## Step 2: Initialize Fast-io Keys

**Scout config:**
- `scout-config/volume-limit` → `{"daily_limit": 50}`
- `scout-config/signal-weights` → `{}` (populated by capability-evolver after first week)
- `scout-config/exclusivity-weights` → default exclusivity map from scout-icp-scorer.js
- `scout-config/connected-crm` → `null`
- `scout-config/connected-enterprise` → `{}`
- `scout-config/pitch-installed` → `true` (set to false if running Scout without Pitch)
- `scout-state/today-deposits` → `{"count": 0, "date": "{{today}}"}`
- `competitor-list` → `[]`

**Pitch config:**
- `pitch-config/icp` → `{}`
- `pitch-config/launch-state` → `{"phase": "test_cohort", "accounts_processed": 0, "cohort_reviewed": false}`
- `pitch-config/activation` → will be populated by activation check
- `pitch-config/connected-outbound` → `null`
- `pitch-config/connected-crm` → `null`
- `timing-weights/` → default timing rules

---

## Step 3: Create Slack Channels

Verify or request creation of:
- `#pitch-approvals` — approval gate delivery (Pitch)
- `#pitch-signals` — signal notifications (Pitch)
- `#pitch-pipeline` — pipeline health and MEDDIC alerts (Pitch)
- `#pitch-quarantine` — low-confidence prospect alerts (Pitch)
- `#scout-leads` — lead dossiers (Scout, used when Pitch not installed)
- `#scout-alerts` — urgent leads, source health alerts, match rate warnings (Scout)
- `#scout-digest` — daily completion summary, weekly intelligence report (Scout)

---

## Step 4: Set Up Cron Jobs

```
openclaw cron add --name "scout-daily-source" --cron "0 6 * * *" --tz "America/New_York" --session isolated --message "Run daily-source pipeline" --thinking low --light-context

openclaw cron add --name "scout-signal-monitor" --cron "0 */4 * * *" --tz "America/New_York" --session isolated --message "Run signal-monitor pipeline" --thinking low --light-context

openclaw cron add --name "scout-weekly-report" --cron "0 8 * * 1" --tz "America/New_York" --session isolated --message "Run weekly-report pipeline" --thinking low --light-context

openclaw cron add --name "scout-source-health" --cron "0 9 * * *" --tz "America/New_York" --session isolated --message "Run source health check" --thinking low --light-context

openclaw cron add --name "pitch-signal-sweep" --cron "0 */4 * * *" --tz "America/New_York" --session isolated --message "Run signal-sweep pipeline" --thinking low --light-context

openclaw cron add --name "pitch-sequence-execute" --cron "0 * * * *" --session isolated --message "Run sequence-execute pipeline" --thinking low --light-context

openclaw cron add --name "pitch-meddic-scan" --cron "0 8 * * 1-5" --tz "America/New_York" --session isolated --message "Run meddic-scan pipeline" --thinking low --light-context

openclaw cron add --name "pitch-bounce-check" --cron "0 9 * * 1" --tz "America/New_York" --session isolated --message "Run bounce rate health check" --thinking low --light-context

openclaw cron add --name "pitch-capability-evolve" --cron "0 6 * * 0" --tz "America/New_York" --session isolated --message "Run capability-evolver: analyze draft approval patterns, signal dismissal patterns, and engagement timing patterns. Update voice model, signal thresholds, and timing weights in fast-io." --thinking low --light-context
```

---

## Step 5: Configure Webhooks

**Leadfeeder/Clearbit Reveal visitor webhook** → `POST /hooks/agent`
```json
{"message": "Website visitor detected: {{company_domain}} visited {{page}}. Run visitor-alert pipeline.", "name": "scout-visitor"}
```

**CRM deal stage change webhook** → `POST /hooks/agent`
```json
{"message": "Deal closed for {{domain}} — stage: {{new_stage}}. Log outcome for Scout conversion tracking.", "name": "scout-outcome"}
```

**Outbound platform reply webhook** → `POST /hooks/agent`
```json
{"message": "Reply received from {{prospect_domain}}. Run reply-handler pipeline.", "name": "pitch-reply"}
```

**Outbound platform unsubscribe webhook** → `POST /hooks/agent`
```json
{"message": "Unsubscribe from {{prospect_domain}}. Run opt-out-handler pipeline.", "name": "pitch-optout"}
```

**CRM deal stage change webhook (Pitch)** → `POST /hooks/agent`
```json
{"message": "Deal stage changed for {{prospect_domain}} from {{old_stage}} to {{new_stage}}. Run meddic-stage-check pipeline.", "name": "pitch-stage-change"}
```

**CRM contact status change webhook** → `POST /hooks/agent`
```json
{"message": "Contact status changed for {{prospect_domain}} to {{new_status}}. Check for active sequences to interrupt.", "name": "pitch-status-change"}
```

---

## Step 6: Security Checks

Run skill-vetter against every skill in the stack:
- `last30days` — flagged for prompt-injection pattern; verify VirusTotal clearance before enabling
- Confirm no skills under 30 days old on ClawHub are installed without clearance
- Enable sona-security-audit for runtime monitoring

---

## Step 7: Announce Readiness

Post to `#scout-alerts` and `#pitch-approvals`:

> "Pitch & Scout are live. Scout monitors signals, enriches leads, and builds dossiers. Pitch takes those dossiers, drafts outreach, and manages sequences — keeping you in the loop before anything touches a prospect. When you're ready to start, tell me about your ideal customer and I'll set up signal monitors automatically. Connect your CRM and outbound platform in settings when you're ready — no setup paperwork now."

---

## Step 8: Delete This File
