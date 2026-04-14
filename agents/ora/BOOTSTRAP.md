# Ora — First Run Bootstrap

This file runs once on first activation. Complete the steps below, then delete this file.

Ora does not interrogate the user during bootstrap. Calendar providers, conferencing platforms, and optional integrations are click-to-connect toggles in the Isol8 settings UI — Ora only mentions them when the user actually asks for something that needs them.

## Step 1: Validate Prerequisites

Required environment:
- `OPENCLAW_HOOK_TOKEN`

That's it. No calendar platform is required at bootstrap — the user connects one from the settings UI before asking Ora to schedule anything. If the user asks Ora to do scheduling work before connecting a calendar, Ora responds per the click-to-connect pattern in AGENTS.md.

## Step 2: Initialize Default State

Create fast-io keys with defaults:
- `ora-config/scheduling-rules` → `{}` (populated when the user first sets rules, either via settings or by replying to Ora's first real scheduling interaction)
- `ora-config/meeting-types` → `{}` (populated on demand)
- `ora-config/user-calendar` → `{}` (populated when a calendar is connected in settings; the settings webhook writes this key)
- `ora-state/exception-history` → `{}`
- `ora-state/agenda-dismissals` → `{}`

## Step 3: Verify Slack Channels

Verify or request creation of:
- `#ora-calendar` — morning briefings, scheduling suggestions, confirmations, weekly digest
- `#ora-alerts` — connection health warnings, critical conflicts

## Step 4: Register Cron Jobs

```
openclaw cron add --name "ora-morning-briefing" --cron "0 7 * * 1-5" --tz "$USER_TIMEZONE" --session isolated --message "Run morning-briefing pipeline" --thinking low --light-context

openclaw cron add --name "ora-conflict-scan" --cron "0 9,11,13,15 * * 1-5" --tz "$USER_TIMEZONE" --session isolated --message "Run conflict detection — only message me if you find something" --thinking low --light-context

openclaw cron add --name "ora-connection-health" --cron "0 */2 * * *" --session isolated --message "Check calendar connection health" --thinking low --light-context

openclaw cron add --name "ora-weekly-digest" --cron "30 7 * * 1" --tz "$USER_TIMEZONE" --session isolated --message "Run weekly-digest pipeline" --thinking low --light-context

openclaw cron add --name "ora-evening-preview" --cron "0 18 * * 0-4" --tz "$USER_TIMEZONE" --session isolated --message "Preview tomorrow's calendar — only message if there are issues or prep needed" --thinking low --light-context
```

Each cron job reads `ora-config/user-calendar` at the start of its pipeline and no-ops if no calendar is connected yet.

## Step 5: Security Checks

Run `skill-vetter` against every skill in the Nexus stack. Enable `sona-security-audit` for runtime monitoring. Calendar OAuth tokens are the most sensitive credentials Ora holds — a compromised skill with write access can create, modify, or delete any event.

## Step 6: Run Activation Check

Run `ora-activation-check.js`. It verifies:
- `OPENCLAW_HOOK_TOKEN` is set
- Default fast-io keys exist
- All 5 cron jobs are registered
- `#ora-calendar` and `#ora-alerts` are accessible

Exit code 0 means go. Exit code 1 means a blocker — surface to the user.

## Step 7: Announce Readiness

Post to `#ora-calendar`:

"Ora is live. I protect your time, coordinate meetings, and surface intelligence about how your calendar is actually working. When you want me to schedule, reschedule, cancel, or block time, just tell me. If you haven't connected a calendar yet, I'll let you know when it's time — no setup paperwork up front."

## Step 8: Delete This File

Delete BOOTSTRAP.md after all steps are complete.
