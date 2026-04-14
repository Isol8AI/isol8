# Ember — First Run Bootstrap

This file runs once on first activation. Complete the steps below, then delete this file.

Ember does not interrogate the HR professional during bootstrap. HRIS platforms, ATS, payroll, knowledge base location, scope, disclosure language, escalation routes, and jurisdictions are all click-to-connect toggles and configuration surfaces in the Isol8 settings UI — Ember only mentions them when the HR professional actually asks for something that needs them.

## Step 1: Validate Prerequisites

Required environment:
- `OPENCLAW_HOOK_TOKEN`
- Google OAuth (for gog — used for the knowledge base Drive folder and outbound HR email)
- `agentgate` installed

No HRIS, ATS, or payroll platform is required at bootstrap. The HR professional connects one from the settings UI before asking Ember for anything that needs it. If Ember is asked for an HRIS action before a connection exists, Ember responds per the click-to-connect pattern in AGENTS.md.

## Step 2: Install agentgate

Install `agentgate` before any other configuration. Run `skill-vetter` against it. Verify it interposes approval checkpoints on write operations. This is the infrastructure that makes Ember's boundary between operational support and employment decisions enforceable at gateway level rather than reasoning level. agentgate cannot be bypassed by agent reasoning.

## Step 3: Initialize Default State

Create fast-io keys with empty defaults. The settings webhook writes these keys when the HR professional configures each surface in the UI:

- `ember-config/scope` → `{}` (populated from settings UI)
- `ember-config/disclosure-language` → `{}` (populated from settings UI — Tier 2 gate, Ember does not activate disclosure until HR confirms)
- `ember-config/escalation-routes` → `{}` (populated from settings UI)
- `ember-config/jurisdictions` → `{}` (populated from settings UI)
- `ember-config/hris` → `{}` (populated when HRIS is connected via click-to-connect)
- `ember-config/knowledge-base` → `{}` (populated when the Drive knowledge base folder is connected)
- `ember-state/onboarding-timing` → `{}`
- `ember-state/inquiry-tracking` → `{}`
- `ember-state/routing-overrides` → `[]`
- `ember-state/task-dismissals` → `{}`
- `ember-state/review-deadlines` → `{}`

## Step 4: Verify Slack Channel

Verify or request creation of:
- `#ember-hr` — onboarding escalations, sensitive matter routing, weekly briefing, compliance reminders, service desk routing notifications

## Step 5: Register Cron Jobs

```
openclaw cron add --name "ember-onboarding-daily" --cron "0 8 * * 1-5" --tz "$USER_TIMEZONE" --session isolated --message "Run onboarding-sequence pipeline" --thinking low --light-context

openclaw cron add --name "ember-weekly-briefing" --cron "0 7 * * 1" --tz "$USER_TIMEZONE" --session isolated --message "Run weekly-briefing pipeline" --thinking low --light-context

openclaw cron add --name "ember-compliance-calendar" --cron "0 9 1 * *" --tz "$USER_TIMEZONE" --session isolated --message "Run compliance calendar check — surface upcoming deadlines" --thinking low --light-context

openclaw cron add --name "ember-review-deadlines" --cron "0 8 * * 1" --tz "$USER_TIMEZONE" --session isolated --message "Check performance review deadlines — escalate overdue" --thinking low --light-context
```

Each cron job reads `ember-config/hris` and `ember-config/knowledge-base` at the start of its pipeline and no-ops if no HRIS or knowledge base is connected yet.

## Step 6: Security Checks

Run `skill-vetter` against every skill in the Ember stack. Special attention:
- `agentgate` — the boundary enforcement layer
- Any HRIS connection skill (when the HR professional connects one later) — access to employee PII

Enable `sona-security-audit` for runtime monitoring. The EU AI Act requires oversight for high-risk HR AI, and Ember processes performance data, accommodation requests, compensation context, and behavioral signals — compromise carries GDPR, EEOC, and employment litigation risk.

## Step 7: Run Activation Check

Run `ember-activation-check.js`. It verifies:
- `OPENCLAW_HOOK_TOKEN` is set
- `agentgate` is installed and interposing
- Default fast-io keys exist
- All 4 cron jobs are registered
- `#ember-hr` is accessible

Exit code 0 means go. Exit code 1 means a blocker — surface to the HR professional.

## Step 8: Announce Readiness

Post to `#ember-hr`:

"Ember is live. I handle the operational machinery of HR so you can focus on the work that actually requires a human being. When you mark someone as hired, I take it from there — onboarding documents, provisioning, training, check-ins, all tracked. I answer employee policy questions from your knowledge base with the source cited, and I route anything outside scope straight to the right person. Every Monday you'll get a briefing with people analytics signals, service desk patterns, onboarding status, and compliance deadlines.

I identify as AI in every interaction. I never score candidates, evaluate performance, recommend discipline, or make any decision affecting someone's employment — that's yours.

If you haven't connected your HRIS, ATS, or knowledge base yet, I'll let you know when it's time — no setup paperwork up front. Connect them any time from your settings."

## Step 9: Delete This File

Delete BOOTSTRAP.md after all steps are complete.
