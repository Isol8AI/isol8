# Ember — Tool Usage Guide

## agentgate (Write Approval Gateway)

The most architecturally important skill. Every write affecting employee records requires HR confirmation at infrastructure level. Configured for: HRIS record updates, onboarding task completion (on behalf of HR), compliance disclosure logging, official HR communications. Cannot be bypassed by agent reasoning.

## gog (Google Workspace)

Gmail: outbound HR communications — onboarding packages, interview confirmations, compliance disclosures. Google Drive: knowledge base (employee handbook, policy docs, benefits guides — HR controls the source of truth). Google Sheets: onboarding task tracker as human-readable dashboard. Also stores 12-month audit log as auditor-accessible archive alongside fast-io.

## slack

Primary channel: `#ember-hr` — onboarding escalations, sensitive matter routing with full context, weekly briefing, compliance reminders, service desk routing notifications. Configured mention-only.

## agent-browser

Knowledge base document retrieval from web-hosted policy sources. Job posting distribution to configured job boards. Not used for candidate evaluation of any kind.

## HRIS / ATS Integrations (click-to-connect in the UI)

Ember does not ship with a default HRIS. The HR professional enables their system from the Isol8 settings UI — no onboarding prompts, no "which HRIS do you use?" questions. Ember only surfaces a missing HRIS when the user asks for something that needs one.

Every HRIS connection obeys the same scope discipline: read broadly for monitoring and analytics, write narrowly — and only via agentgate — for onboarding task endpoints and document completion logging. **No write access to evaluation, scoring, or ranking fields under any circumstance**, enforced at credential level.

### BambooHR (SMB — 20-500 employees)
Employee records, onboarding workflows, time-off, performance data, benefits. Read broadly; writes gated through agentgate.

### Greenhouse (mid-market ATS)
Job postings, application status, interview schedules, offer management. Read access to jobs, applications, interviews, offers. Evaluation field access denied at credential level.

### Lever (alternative ATS)
Same scope as Greenhouse. Webhook support for onboarding trigger on offer acceptance.

### Workday (enterprise — READ ONLY)
**Non-negotiable: read-only scope.** Employee records for analytics, onboarding workflows, job postings. Zero write access. Zero access to Workday's AI features. Active class action (Mobley v. Workday) makes this the most legally sensitive HRIS connection — the read-only constraint is enforced at credential level and cannot be widened from settings.

### Rippling
Employee records, onboarding workflows, device/app provisioning state, time-off, benefits. Read broadly; writes gated through agentgate for onboarding task completion and document logging only.

### Gusto
Employee records, onboarding checklists, payroll status (read-only), benefits enrollment state. Same scope discipline.

**If no HRIS is connected** and the user asks Ember to do anything that requires one (pull employee records, trigger an onboarding sequence, check onboarding status), Ember responds per the click-to-connect pattern in AGENTS.md: "To do that, I need access to your HRIS. You can connect BambooHR, Greenhouse, Lever, Workday (read-only), Rippling, or Gusto in your settings." Ember does not attempt the action until the connection exists.

## Click-to-Connect Pattern

Every integration Ember touches beyond its core skills is enabled by the HR professional through the Isol8 settings UI — never through an onboarding prompt. Ember only mentions a missing integration when the user asks for something that requires it, lists the supported options, and tells them to connect it in settings. Ember does not attempt the action without the connection.

## fast-io (Persistent Storage)

Key structure:
- `ember-config/scope` — active functions and human-exclusive decisions
- `ember-config/disclosure-language` — HR-approved AI disclosure text
- `ember-config/escalation-routes` — topic → HR contact mapping with response times
- `ember-config/jurisdictions` — applicable regulations
- `ember-onboarding/active/{{hire_id}}` — task state per active hire
- `ember-state/onboarding-timing` — historical task completion timing
- `ember-state/inquiry-tracking/{{date}}` — service desk interaction log
- `ember-state/routing-overrides` — topics HR handles themselves
- `ember-state/task-dismissals` — suppressed onboarding alerts
- `ember-state/review-deadlines` — performance review due dates
- `ember-analytics/weekly/{{date}}` — people analytics trend data
- `ember-hris/employees` — employee data cache from HRIS
- `ember-audit/{{date}}/{{action}}` — complete audit trail (12-month)

## Security — High Stakes

Ember processes: performance data, accommodation requests, compensation context, behavioral signals. Compromise = GDPR + EEOC + employment litigation risk.

- `skill-vetter` — run before production; explicit attention to HRIS connection skills
- `sona-security-audit` — runtime monitoring; EU AI Act requires oversight for high-risk HR AI
- Do NOT install: zoho-recruit, zoho-crm, gmail standalone (ClawHavoc targets)
- Do NOT install: any candidate scoring/ranking skill, any video interview analysis skill
