# Echo — First Run Bootstrap

This file runs once on first activation. Complete the steps below, then delete this file.

Echo does not interrogate the user during bootstrap. Meeting platforms, PM tools, CRMs, meeting type templates, commitment thresholds, and recording consent are all click-to-connect / click-to-configure surfaces in the Isol8 settings UI — Echo only mentions them when the user actually asks for something that needs them.

## Step 1: Validate Prerequisites

Required environment:
- `OPENCLAW_HOOK_TOKEN`

That's it. No transcription service, PM tool, or CRM is required at bootstrap — the user connects one from the settings UI before asking Echo to process anything. If Echo is invoked on a meeting before a meeting platform is connected, it responds per the click-to-connect pattern in AGENTS.md.

## Step 2: Initialize Default State

Create fast-io keys with defaults:
- `echo-config/consent` → `{}` (populated from the settings UI's consent acknowledgement flow; `meeting-process.lobster` hard-blocks if `consent.confirmed` is not true)
- `echo-config/templates` → `{}` (formatter falls back to built-in TEMPLATE_DEFAULTS when empty)
- `echo-config/commitment-thresholds` → `{}` (classifier falls back to built-in defaults when empty)
- `echo-config/connected-meeting-platforms` → `{}` (settings webhook writes this key when the user click-to-connects Zoom, Google Meet, or Teams)
- `echo-config/connected-pm-tool` → `{}` (settings webhook writes this key when the user click-to-connects Asana, Linear, or Jira)
- `echo-config/connected-crm` → `{}` (settings webhook writes this key when the user click-to-connects HubSpot, Salesforce, Attio, or Pipedrive)
- `echo-state/commitment-overrides` → `{}`
- `echo-state/template-edits` → `{}`

## Step 3: Verify Slack Channel

Verify or request creation of:
- `#echo-meetings` — reviewer queue, action item notifications, deadline alerts, weekly digest

## Step 4: Register Cron Jobs

```
openclaw cron add --name "echo-calendar-sweep" --cron "0 18 * * 1-5" --tz "$USER_TIMEZONE" --session isolated --message "Check calendar for meetings that ended today and need processing" --thinking low --light-context

openclaw cron add --name "echo-weekly-digest" --cron "0 8 * * 1" --tz "$USER_TIMEZONE" --session isolated --message "Run weekly-digest pipeline — action item status report" --thinking low --light-context

openclaw cron add --name "echo-deadline-alerts" --cron "0 9 * * 1-5" --tz "$USER_TIMEZONE" --session isolated --message "Check action item deadlines — alert on approaching and overdue" --thinking low --light-context
```

Each cron job reads the relevant click-to-connect config keys at the start of its pipeline and no-ops gracefully if no platform is connected yet.

## Step 5: Security Checks

Run `skill-vetter` against every skill in the stack. Enable `sona-security-audit` for runtime monitoring. Meeting content is among the most sensitive data Echo handles — board deliberations, personnel discussions, client commitments, financial projections. Any unexpected network call from a skill processing a transcript is an immediate confidentiality breach.

## Step 6: Run Activation Check

Run `echo-activation-check.js`. It verifies:
- `OPENCLAW_HOOK_TOKEN` is set
- Default fast-io keys exist
- The 3 cron jobs are registered
- `#echo-meetings` is accessible

Exit code 0 means go. Exit code 1 means a blocker — surface to the user.

## Step 7: Announce Readiness

Post to `#echo-meetings`:

"Echo is live. I turn meetings into accountable records — decisions attributed correctly, action items tracked, and nothing distributed until a human says it's right. When you're ready for me to process a meeting, just point me at it. If you haven't connected a meeting platform yet, I'll let you know when it's time — no setup paperwork up front."

## Step 8: Delete This File

Delete BOOTSTRAP.md after all steps are complete.
